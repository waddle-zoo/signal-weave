"""Isolated native MCP setup for a fictional-enterprise journey.

The supplied GitHub Actions artifact is checksum-verified and only the exact
regular ``signalweave`` tar member and bounded regular ``_internal/`` runtime
files are extracted. The real setup wizard and
Codex CLI run with a fresh fake-person HOME/CODEX_HOME. No published installer
is exercised; setup and source-health checks do not request a Jev judgment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pty
import re
import select
import signal
import stat
import subprocess
import tarfile
import termios
import time
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.binary_provenance import verify_binary

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_MEMBER = "signalweave"
MAX_ARCHIVE_BYTES = 1_000_000_000
MAX_BINARY_BYTES = 512_000_000
MAX_ARCHIVE_MEMBERS = 20_003
MAX_TRANSCRIPT_BYTES = 2_000_000
MAX_COMMAND_OUTPUT_BYTES = 2_000_000


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_checksum(path: Path, archive: Path) -> str:
    """Read a conventional sha256sum line, optionally bound to this filename."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("A regular archive checksum sidecar is required")
    fields = path.read_text(encoding="ascii").strip().split()
    if not fields or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]):
        raise ValueError("Checksum sidecar must start with one SHA-256 digest")
    if len(fields) > 2 or len(fields) == 2 and fields[1].lstrip("*") != archive.name:
        raise ValueError("Checksum sidecar names a different archive")
    return fields[0].lower()


def extract_candidate(archive: Path, expected_sha256: str, fake_home: Path) -> dict[str, Any]:
    """Extract one exact regular member without tar path extraction semantics."""
    archive = Path(archive).expanduser().absolute()
    fake_home = Path(fake_home).expanduser().absolute()
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Expected a bounded regular GitHub Actions tar archive")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("Expected a lowercase SHA-256 archive digest")
    archive_sha = _sha256_file(archive)
    if archive_sha != expected_sha256:
        raise ValueError("Downloaded archive checksum does not match")

    resources: dict[str, bytes] = {}
    try:
        with tarfile.open(archive, mode="r:*") as package:
            members = package.getmembers()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise ValueError("Archive has too many members")
            exact = [member for member in members if member.name == ARCHIVE_MEMBER]
            if len(exact) != 1:
                raise ValueError("Archive must contain exactly one member named 'signalweave'")
            member = exact[0]
            member_path = PurePosixPath(member.name)
            if (member_path.is_absolute() or member_path.parts != (ARCHIVE_MEMBER,)
                    or not member.isfile() or member.issparse()
                    or not 0 < member.size <= MAX_BINARY_BYTES):
                raise ValueError("Exact archive member must be a bounded regular executable file")
            stream = package.extractfile(member)
            if stream is None:
                raise ValueError("Archive member could not be read")
            payload = stream.read(MAX_BINARY_BYTES + 1)
            if len(payload) != member.size or len(payload) > MAX_BINARY_BYTES:
                raise ValueError("Archive member size did not match its header")
            total_bytes = len(payload)
            for resource in members:
                if not resource.name.startswith("_internal/"):
                    continue
                relative = PurePosixPath(resource.name)
                if (not resource.isfile() or resource.issparse()
                        or str(relative) != resource.name or ".." in relative.parts
                        or resource.name in resources or resource.size < 0):
                    raise ValueError("Runtime members must be unique regular bounded paths")
                total_bytes += resource.size
                if total_bytes > MAX_BINARY_BYTES:
                    raise ValueError("Expanded runtime exceeds its byte limit")
                resource_stream = package.extractfile(resource)
                if resource_stream is None:
                    raise ValueError("Runtime file could not be read")
                data = resource_stream.read(resource.size + 1)
                if len(data) != resource.size:
                    raise ValueError("Runtime file size did not match its header")
                resources[resource.name] = data
            if any(str(parent) in resources for name in resources
                   for parent in PurePosixPath(name).parents):
                raise ValueError("Runtime file conflicts with a parent directory")
    except (tarfile.TarError, OSError) as error:
        raise ValueError("Could not safely read the supplied tar archive") from error

    if fake_home.exists() or fake_home.is_symlink():
        raise ValueError("Fake-person home must be fresh and absent")
    fake_home.mkdir(mode=0o700, parents=False)
    local = fake_home / ".local"
    local.mkdir(mode=0o700)
    install_dir = local / "bin"
    install_dir.mkdir(mode=0o700)
    binary = install_dir / ARCHIVE_MEMBER
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(binary, flags, 0o700)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        binary.chmod(0o700)
        for name, data in resources.items():
            destination = install_dir / name
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(destination, flags, 0o700)
            with os.fdopen(fd, "wb") as output:
                output.write(data)
    except BaseException:
        binary.unlink(missing_ok=True)
        raise
    return {
        "archive_sha256": archive_sha,
        "archive_member": ARCHIVE_MEMBER,
        "member_size": len(payload),
        "binary_sha256": _sha256_file(binary),
        "binary_path": str(binary),
        "runtime_files": len(resources),
        "install_scope": "fresh fake-person HOME/.local/bin; no published installer",
    }


def isolated_environment(home: Path, codex_cli: Path, *, path: str | None = None) -> dict[str, str]:
    """Build an isolated process environment and resolve the real Codex CLI."""
    home = Path(home).absolute()
    codex_cli = Path(codex_cli).expanduser().resolve(strict=True)
    if codex_cli.name != "codex" or not codex_cli.is_file() or not os.access(codex_cli, os.X_OK):
        raise ValueError("Codex CLI must be an executable named 'codex'")
    codex_home = home / ".codex"
    temp_home = home / ".tmp"
    for directory in (codex_home, temp_home):
        if directory.exists() or directory.is_symlink():
            raise ValueError("Isolated Codex and temporary directories must be fresh")
        directory.mkdir(mode=0o700)
    safe_path = os.pathsep.join(filter(None, (
        str(home / ".local" / "bin"), str(codex_cli.parent),
        "/usr/bin", "/bin", "/usr/sbin", "/sbin",
    )))
    # Preserve locale and certificate locations only; never inherit API keys,
    # the user's HOME, Codex config, proxy credentials, or arbitrary env vars.
    inherited = os.environ if path is None else {"PATH": path}
    env = {name: inherited[name] for name in (
        "LANG", "LC_ALL", "LC_CTYPE", "SSL_CERT_FILE", "SSL_CERT_DIR",
    ) if name in inherited}
    env.update({
        "HOME": str(home),
        "CODEX_HOME": str(codex_home),
        "SIGNALWEAVE_HOME": str(home / ".signalweave"),
        "TMPDIR": str(temp_home),
        "PATH": safe_path,
        "PINE_SOURCE_PYTHONPATH": str(ROOT),
        # Wizard, registration, status, and source health must not reach a
        # Jev endpoint. The later actor run installs its separately audited URL.
        "TYPESAFE_BASE_URL": "http://127.0.0.1:9",
    })
    if shutil_which("codex", safe_path) != str(codex_cli):
        raise ValueError("Isolated PATH did not resolve the requested real Codex CLI")
    return env


def shutil_which(name: str, path: str) -> str | None:
    """Small PATH resolver that does not consult shell aliases or user config."""
    for directory in path.split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    return None


def setup_prompt_plan(key: str, manifest: Path) -> list[dict[str, str]]:
    """Frozen expected human choices for the interactive MCP setup path."""
    return [
        {"id": "decision_provider", "needle": "Decision provider [1]:", "answer": "1\n", "label": "Jev"},
        {"id": "jev_key", "needle": "TypeSafe / Jev API key (hidden):", "answer": key + "\n", "label": "[REDACTED]"},
        {"id": "source", "needle": "Source [skip]:", "answer": "4\n", "label": "Company MCP"},
        {"id": "mcp_manifest", "needle": "Reviewed MCP manifest path (normalized read-only sources only):",
         "answer": str(manifest) + "\n", "label": "supplied manifest path"},
        {"id": "agent", "needle": "Agent [codex]:", "answer": "1\n", "label": "Codex"},
        {"id": "another_source", "needle": "Add another source? [y/N]:", "answer": "n\n", "label": "no"},
        {"id": "register_codex", "needle": "Connect SignalWeave to Codex now? [Y/n]:",
         "answer": "y\n", "label": "yes"},
        {"id": "install_skill", "needle": "Install the bundled SignalWeave skill for Codex in your user scope",
         "answer": "y\n", "label": "yes"},
    ]


def _redact_text(value: str, secrets: tuple[str, ...]) -> str:
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    return value


def redact_value(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        return _redact_text(value, secrets)
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item, secrets) for key, item in value.items()}
    return value


def terminal_setup(
    binary: Path,
    home: Path,
    env: Mapping[str, str],
    key: str,
    manifest: Path,
    *,
    timeout_seconds: float = 120,
    prompt_plan: list[dict[str, str]] | None = None,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    open_pty: Callable[[], tuple[int, int]] = pty.openpty,
    select_fn: Callable[..., Any] = select.select,
    read_fn: Callable[[int, int], bytes] = os.read,
    write_fn: Callable[[int, bytes], int] = os.write,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Drive the real wizard through a PTY; injected functions keep tests offline."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    plan = prompt_plan if prompt_plan is not None else setup_prompt_plan(key, manifest)
    pending = list(plan)
    seen: list[dict[str, str]] = []
    master, slave = open_pty()
    process = None
    transcript = bytearray()
    started = clock()
    timed_out = False
    truncated = False
    try:
        attrs = termios.tcgetattr(slave)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        process = popen_factory(
            [str(binary), "setup", "--home", str(home)],
            stdin=slave, stdout=slave, stderr=slave, env=dict(env), cwd=env["HOME"],
            start_new_session=True,
        )
        os.close(slave)
        slave = -1
        while clock() - started < timeout_seconds:
            if select_fn([master], [], [], 0.1)[0]:
                try:
                    chunk = read_fn(master, 8192)
                except OSError:
                    break
                if not chunk:
                    break
                transcript.extend(chunk)
                if len(transcript) > MAX_TRANSCRIPT_BYTES:
                    truncated = True
                    break
                displayed = transcript.decode("utf-8", errors="replace")
                while pending and pending[0]["needle"] in displayed:
                    item = pending.pop(0)
                    seen.append({"id": item["id"], "prompt": item["needle"], "response": item["label"]})
                    try:
                        write_fn(master, item["answer"].encode())
                    except OSError:
                        pending.insert(0, item)
                        break
            if process.poll() is not None:
                break
            if truncated:
                break
        else:
            timed_out = True
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
        returncode = process.wait(timeout=10)
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        if slave >= 0:
            os.close(slave)
        os.close(master)
    return {
        "returncode": returncode,
        "elapsed_seconds": round(clock() - started, 3),
        "timed_out": timed_out,
        "transcript_truncated": truncated,
        "pending_prompts": [item["id"] for item in pending],
        "prompts": seen,
        "transcript": _redact_text(transcript.decode("utf-8", errors="replace"), (key,)),
        "transcript_redacted": True,
    }


def _private_json(path: Path, value: dict[str, Any], secrets: tuple[str, ...]) -> None:
    if path.is_symlink():
        raise ValueError("Refusing a symlink result path")
    payload = json.dumps(redact_value(value, secrets), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)


def _run_json(binary: Path, command: tuple[str, ...], home: Path,
              env: Mapping[str, str], secrets: tuple[str, ...], timeout: int = 120) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [str(binary), *command, "--json", "--home", str(home)], cwd=home,
            env=dict(env), capture_output=True, text=True, timeout=timeout, shell=False,
        )
    except subprocess.TimeoutExpired:
        return {"returncode": None, "timed_out": True, "result": None,
                "stderr": "command timed out"}
    stdout = result.stdout[:MAX_COMMAND_OUTPUT_BYTES]
    stderr = _redact_text(result.stderr[:MAX_COMMAND_OUTPUT_BYTES], secrets)
    try:
        payload = json.loads(stdout)
    except (ValueError, TypeError):
        payload = None
    return {
        "returncode": result.returncode,
        "timed_out": False,
        "result": redact_value(payload, secrets) if payload is not None else None,
        "output_parseable": isinstance(payload, dict),
        "stdout_excerpt": _redact_text(stdout[:4000], secrets) if payload is None else None,
        "stderr": stderr,
    }


def _inventory_summary(stdout: str, returncode: int, binary: Path, home: Path,
                       secrets: tuple[str, ...]) -> dict[str, Any]:
    expected_args = ["serve", "--transport", "stdio", "--home", str(home)]
    if returncode != 0:
        return {"returncode": returncode, "parseable": False, "entries": [],
                "stderr": "Codex MCP inventory command failed"}
    try:
        rows = json.loads(stdout)
    except (ValueError, TypeError):
        return {"returncode": returncode, "parseable": False, "entries": []}
    if not isinstance(rows, list) or len(rows) > 100:
        return {"returncode": returncode, "parseable": False, "entries": []}
    safe_rows = []
    exact = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            return {"returncode": returncode, "parseable": False, "entries": []}
        transport = row.get("transport")
        if not isinstance(transport, dict):
            return {"returncode": returncode, "parseable": False, "entries": []}
        env_values = transport.get("env")
        env_vars = transport.get("env_vars", [])
        matches = (
            row.get("name") == "signalweave" and row.get("enabled") is True
            and transport.get("type") == "stdio"
            and transport.get("command") == str(binary)
            and transport.get("args") == expected_args
            and env_values in (None, {}) and env_vars in (None, [])
        )
        if row.get("name") == "signalweave":
            exact.append(matches)
        safe_rows.append({
            "name": _redact_text(row["name"], secrets),
            "enabled": row.get("enabled") if type(row.get("enabled")) is bool else None,
            "transport_type": transport.get("type") if isinstance(transport.get("type"), str) else None,
            "is_expected_signalweave_entry": matches,
            "environment_empty": env_values in (None, {}) and env_vars in (None, []),
        })
    return {
        "returncode": returncode,
        "parseable": True,
        "entries": safe_rows,
        "only_expected_signalweave_entry": len(rows) == 1 and exact == [True],
        "expected_entry": {"name": "signalweave", "command": str(binary), "args": expected_args,
                           "transport_type": "stdio", "enabled": True, "environment": "empty"},
    }


def _codex_inventory(codex_cli: Path, home: Path, env: Mapping[str, str],
                     binary: Path, secrets: tuple[str, ...]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [str(codex_cli), "mcp", "list", "--json"], cwd=home, env=dict(env),
            capture_output=True, text=True, timeout=30, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"returncode": None, "parseable": False, "entries": [],
                "error": type(error).__name__}
    summary = _inventory_summary(result.stdout, result.returncode, binary, home / ".signalweave", secrets)
    summary["stderr"] = _redact_text(result.stderr[:4000], secrets)
    summary["cli_path"] = str(codex_cli)
    return summary


def _skill_check(binary: Path, home: Path, env: Mapping[str, str], secrets: tuple[str, ...]) -> dict[str, Any]:
    target = home / ".agents" / "skills" / "signalweave" / "SKILL.md"
    result = subprocess.run([str(binary), "skills", "show"], cwd=home, env=dict(env),
                            capture_output=True, text=True, timeout=30, shell=False)
    installed = target.is_file() and not target.is_symlink()
    bundled = result.stdout.encode("utf-8") if result.returncode == 0 else b""
    content = target.read_bytes() if installed else b""
    return {
        "returncode": result.returncode,
        "installed_path": str(target),
        "installed": installed,
        "matches_native_bundle": bool(installed and bundled and content == bundled),
        "sha256": hashlib.sha256(content).hexdigest() if installed else None,
        "stderr": _redact_text(result.stderr[:4000], secrets),
    }


def install_and_setup(archive: Path, person: Path, manifest: Path, key_file: Path,
                      codex: Path) -> dict[str, Any]:
    """Install the supplied CI binary and perform its actual isolated setup path.

    ``person`` is the fake person's fresh HOME, not an output wrapper directory:
    the executable lands at ``person/.local/bin/signalweave`` and SignalWeave
    state at ``person/.signalweave``. No provider judgment is requested here.
    """
    archive = Path(archive).expanduser().absolute()
    person = Path(person).expanduser().absolute()
    result: dict[str, Any] = {
        "status": "running",
        "scope": "supplied GitHub Actions CI tar archive; exact member signalweave; not a published release or curl-installer test",
        "setup_mode": "actual native PTY wizard; scripted fake-person inputs; actual isolated Codex CLI registration and bundled user-scope skill",
        "provider_usage": "setup and source-only health do not request Jev judgments",
        "person_home": str(person),
    }
    secret = ""
    try:
        key_path = Path(key_file).expanduser().absolute()
        if key_path.is_symlink() or not key_path.is_file():
            raise ValueError("Jev key must be supplied as a regular private file")
        if stat.S_IMODE(key_path.stat().st_mode) & 0o077:
            raise ValueError("Jev key file must not be accessible to group or other users")
        secret = key_path.read_text(encoding="utf-8").strip()
        if not secret or "\n" in secret or "\r" in secret:
            raise ValueError("Jev key file must contain one nonempty line")
        manifest = Path(manifest).expanduser().resolve(strict=True)
        if manifest.is_symlink() or not manifest.is_file():
            raise ValueError("Reviewed MCP manifest must be a regular file")
        checksum_path = Path(str(archive) + ".sha256")
        expected = read_checksum(checksum_path, archive)
        extracted = extract_candidate(archive, expected, person)
        binary = Path(extracted["binary_path"])
        extracted["binary_identity"] = verify_binary(binary, ROOT)
        result["candidate"] = extracted
        result["manifest_path"] = str(manifest)
        result["source_pythonpath"] = str(ROOT)
        codex_cli = Path(codex).expanduser().resolve(strict=True)
        env = isolated_environment(person, codex_cli)
        result["codex_cli"] = {"path": str(codex_cli), "sha256": _sha256_file(codex_cli),
                               "code_home": env["CODEX_HOME"], "home_isolated": True}

        wizard = terminal_setup(binary, person / ".signalweave", env, secret, manifest)
        result["wizard"] = wizard
        wizard_ok = (wizard["returncode"] == 0 and not wizard["timed_out"]
                     and not wizard["pending_prompts"] and not wizard["transcript_truncated"])
        if not wizard_ok:
            result["status"] = "setup_incomplete"
            return result

        result["codex_inventory"] = _codex_inventory(codex_cli, person, env, binary, (secret,))
        result["skill"] = _skill_check(binary, person, env, (secret,))
        result["status_check"] = _run_json(binary, ("status",), person / ".signalweave", env, (secret,))
        result["health_offline"] = _run_json(binary, ("health",), person / ".signalweave", env, (secret,))
        result["health_live_source_only"] = _run_json(
            binary, ("health", "--live"), person / ".signalweave", env, (secret,), timeout=180,
        )
        expected_status = result["status_check"].get("result") or {}
        offline_health = result["health_offline"].get("result") or {}
        live_health = result["health_live_source_only"].get("result") or {}
        result["status"] = "setup_verified" if (
            result["codex_inventory"].get("only_expected_signalweave_entry") is True
            and result["codex_inventory"].get("parseable") is True
            and result["skill"].get("matches_native_bundle") is True
            and expected_status.get("status") == "ready_for_agent"
            and offline_health.get("healthy") is True
            and live_health.get("healthy") is True
        ) else "setup_needs_review"
        return result
    except Exception as error:  # preserve partial setup evidence without secret-bearing traces
        result["status"] = "setup_failed"
        result["error"] = {"type": type(error).__name__,
                            "message": _redact_text(str(error), (secret,))[:1000]}
        return result


def run_setup(*, archive: Path, checksum_file: Path, key_file: Path, manifest: Path,
              codex_cli: Path, output: Path) -> dict[str, Any]:
    """Small CLI wrapper retained for manual reproduction of the setup helper."""
    output = Path(output).expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("Output root must be fresh; attempts are never overwritten")
    output.mkdir(mode=0o700, parents=True)
    archive = Path(archive).expanduser().absolute()
    supplied_sha = read_checksum(Path(checksum_file).expanduser().absolute(), archive)
    sidecar_sha = read_checksum(Path(str(archive) + ".sha256"), archive)
    if supplied_sha != sidecar_sha:
        raise ValueError("Supplied checksum differs from the archive's adjacent SHA-256 sidecar")
    result = install_and_setup(archive, output / "human-home", manifest, key_file, codex_cli)
    result["output_root"] = str(output)
    _private_json(output / "results.json", result, ())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="Supplied GitHub Actions CI tar archive")
    parser.add_argument("--checksum-file", type=Path, required=True, help="SHA-256 sidecar for the archive")
    parser.add_argument("--key-file", type=Path, required=True, help="Private Jev key file; never passed to Codex")
    parser.add_argument("--manifest", type=Path, required=True, help="Reviewed static MCP source manifest")
    parser.add_argument("--codex", type=Path, required=True, help="Exact real Codex CLI executable named codex")
    parser.add_argument("--output", type=Path, required=True, help="Fresh ignored artifact directory")
    result = run_setup(**vars(parser.parse_args()))
    print(json.dumps({"status": result["status"], "results": str(Path(result["output_root"]) / "results.json")}))


if __name__ == "__main__":
    main()
