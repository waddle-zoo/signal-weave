from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest

from evaluations import enterprise_native_setup as setup


def _archive(path: Path, members: list[tuple[str, bytes, str]]) -> str:
    with tarfile.open(path, "w:gz") as package:
        for name, payload, kind in members:
            info = tarfile.TarInfo(name)
            info.mode = 0o755
            if kind == "file":
                info.size = len(payload)
                package.addfile(info, io.BytesIO(payload))
            else:
                info.type = tarfile.SYMTYPE
                info.linkname = payload.decode()
                package.addfile(info)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_extract_candidate_installs_only_the_exact_regular_member(tmp_path: Path) -> None:
    archive = tmp_path / "candidate.tar.gz"
    digest = _archive(archive, [("signalweave", b"native-test-payload", "file")])
    person = tmp_path / "person"

    evidence = setup.extract_candidate(archive, digest, person)

    binary = person / ".local/bin/signalweave"
    assert binary.read_bytes() == b"native-test-payload"
    assert binary.stat().st_mode & 0o777 == 0o700
    assert evidence["binary_path"] == str(binary)


@pytest.mark.parametrize(
    "members",
    [
        [("signalweave", b"one", "file"), ("signalweave", b"two", "file")],
        [("signalweave", b"../outside", "symlink")],
        [("nested/signalweave", b"not-the-exact-member", "file")],
    ],
)
def test_extract_candidate_rejects_ambiguous_or_nonregular_target(
    tmp_path: Path, members: list[tuple[str, bytes, str]],
) -> None:
    archive = tmp_path / "candidate.tar.gz"
    digest = _archive(archive, members)
    person = tmp_path / "person"

    with pytest.raises(ValueError):
        setup.extract_candidate(archive, digest, person)
    assert not person.exists()


def test_isolated_environment_sets_provider_deny_and_source_import_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    person = tmp_path / "person"
    person.mkdir()
    codex = tmp_path / "codex" / "codex"
    codex.parent.mkdir()
    codex.write_text("#!/bin/sh\nexit 0\n")
    codex.chmod(0o700)
    monkeypatch.setenv("JEV_API_KEY", "must-not-inherit")

    env = setup.isolated_environment(person, codex)

    assert env["HOME"] == str(person)
    assert env["SIGNALWEAVE_HOME"] == str(person / ".signalweave")
    assert env["PINE_SOURCE_PYTHONPATH"] == str(setup.ROOT)
    assert env["TYPESAFE_BASE_URL"] == "http://127.0.0.1:9"
    assert "JEV_API_KEY" not in env


def test_install_and_setup_uses_person_root_and_never_launches_a_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "candidate.tar.gz"
    _archive(archive, [("signalweave", b"not-executed", "file")])
    (tmp_path / f"{archive.name}.sha256").write_text(
        f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n",
    )
    manifest = tmp_path / "sources.json"
    manifest.write_text(json.dumps({"connections": []}))
    key_file = tmp_path / "key"
    key_file.write_text("fake-key-value\n")
    key_file.chmod(0o600)
    codex = tmp_path / "codex-bin" / "codex"
    codex.parent.mkdir()
    codex.write_text("#!/bin/sh\nexit 99\n")
    codex.chmod(0o700)
    person = tmp_path / "signalweave" / "person"
    person.parent.mkdir()
    observed: dict[str, Any] = {}

    def fake_verify(binary: Path, root: Path) -> dict[str, Any]:
        observed["verified_binary"] = binary
        return {"verified": True}

    def fake_terminal(binary: Path, home: Path, env: dict[str, str], key: str,
                      selected_manifest: Path) -> dict[str, Any]:
        observed.update(binary=binary, home=home, env=env, key=key, manifest=selected_manifest)
        return {"returncode": 0, "timed_out": False, "pending_prompts": [],
                "transcript_truncated": False, "prompts": [], "transcript": "[REDACTED]"}

    monkeypatch.setattr(setup, "verify_binary", fake_verify)
    monkeypatch.setattr(setup, "terminal_setup", fake_terminal)
    monkeypatch.setattr(setup, "_codex_inventory", lambda *args: {
        "parseable": True, "only_expected_signalweave_entry": True,
    })
    monkeypatch.setattr(setup, "_skill_check", lambda *args: {"matches_native_bundle": True})
    monkeypatch.setattr(setup, "_run_json", lambda binary, command, *args, **kwargs: {
        "returncode": 0,
        "result": ({"status": "ready_for_agent"} if command[0] == "status" else {"healthy": True}),
    })

    result = setup.install_and_setup(archive, person, manifest, key_file, codex)

    assert result["status"] == "setup_verified"
    assert result["candidate"]["binary_path"] == str(person / ".local/bin/signalweave")
    assert observed["binary"] == person / ".local/bin/signalweave"
    assert observed["home"] == person / ".signalweave"
    assert observed["env"]["TYPESAFE_BASE_URL"] == "http://127.0.0.1:9"
    assert observed["env"]["PINE_SOURCE_PYTHONPATH"] == str(setup.ROOT)
    assert observed["manifest"] == manifest.resolve()
    assert "fake-key-value" not in json.dumps(result)


def test_terminal_setup_drives_prompts_through_mocked_pty_without_execution(
    tmp_path: Path,
) -> None:
    person = tmp_path / "person"
    person.mkdir()
    manifest = tmp_path / "sources.json"
    manifest.write_text("{}")
    key = "fake-secret-not-for-output"
    plan = setup.setup_prompt_plan(key, manifest)
    state = {"read": False, "writes": [], "spawn_args": None}

    class FakeProcess:
        pid = 999_999_999

        def poll(self) -> int | None:
            return 0 if state["read"] else None

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            raise AssertionError("completed mock process must not be killed")

    def fake_popen(args: list[str], **kwargs: Any) -> FakeProcess:
        state["spawn_args"] = (args, kwargs)
        return FakeProcess()

    def fake_select(readers: list[int], writers: list[int], errors: list[int],
                    timeout: float) -> tuple[list[int], list[int], list[int]]:
        return ([readers[0]], [], []) if not state["read"] else ([], [], [])

    def fake_read(fd: int, size: int) -> bytes:
        state["read"] = True
        return ("\n".join(item["needle"] for item in plan) + "\n" + key).encode()

    def fake_write(fd: int, payload: bytes) -> int:
        state["writes"].append(payload)
        return len(payload)

    result = setup.terminal_setup(
        tmp_path / "not-executed", person / ".signalweave",
        {"HOME": str(person)}, key, manifest, prompt_plan=plan,
        popen_factory=fake_popen, select_fn=fake_select,
        read_fn=fake_read, write_fn=fake_write,
    )

    assert result["returncode"] == 0
    assert result["pending_prompts"] == []
    assert len(result["prompts"]) == len(plan)
    assert len(state["writes"]) == len(plan)
    assert key not in result["transcript"]
    assert state["spawn_args"][1]["cwd"] == str(person)
