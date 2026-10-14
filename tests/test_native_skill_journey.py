from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CANONICAL_SKILL = REPO / "skills" / "signalweave" / "SKILL.md"
SOURCE_CLI = (sys.executable, "-m", "signalweave.cli")


def _isolated_environment(root: Path, *, source_cli: bool) -> tuple[dict[str, str], Path]:
    home = root / "home"
    home.mkdir()
    temp = root / "tmp"
    temp.mkdir()
    environment = {
        "HOME": str(home),
        "PATH": os.defpath,
        "TMPDIR": str(temp),
        "TEMP": str(temp),
        "TMP": str(temp),
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONUTF8": "1",
        "PYTHONNOUSERSITE": "1",
    }
    assert not {
        "TYPESAFE_API_KEY",
        "OPENAI_API_KEY",
        "SIGNALWEAVE_API_TOKEN",
        "CODEX_HOME",
        "CLAUDE_CONFIG_DIR",
    }.intersection(environment)
    if source_cli:
        environment["PYTHONPATH"] = str(REPO / "src")
    return environment, home


def _run_cli(
    command: tuple[str, ...],
    *arguments: str,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*command, *arguments],
        cwd=cwd,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )


def _exercise_project_skill_journey(
    command: tuple[str, ...], root: Path, *, source_cli: bool
) -> None:
    environment, home = _isolated_environment(root, source_cli=source_cli)
    expected = CANONICAL_SKILL.read_bytes()

    help_result = _run_cli(command, "--help", cwd=root, environment=environment)
    assert help_result.returncode == 0, help_result.stderr
    assert "skills" in help_result.stdout

    show_result = _run_cli(command, "skills", "show", cwd=root, environment=environment)
    assert show_result.returncode == 0, show_result.stderr
    assert show_result.stdout.encode("utf-8") == expected

    for agent, parent in (("codex", ".agents"), ("claude", ".claude")):
        project = root / f"{agent}-project"
        project.mkdir()
        first = _run_cli(
            command,
            "skills",
            "install",
            "--agent",
            agent,
            "--scope",
            "project",
            cwd=project,
            environment=environment,
        )
        assert first.returncode == 0, first.stderr
        assert "skill installed:" in first.stdout.lower()

        target = project / parent / "skills" / "signalweave"
        assert (target / "SKILL.md").read_bytes() == expected
        assert {item.name for item in target.iterdir()} == {"SKILL.md"}
        assert not (project / (".claude" if agent == "codex" else ".agents")).exists()
        assert not (project / ".codex").exists()
        assert not (project / ".mcp.json").exists()

        second = _run_cli(
            command,
            "skills",
            "install",
            "--agent",
            agent,
            "--scope",
            "project",
            cwd=project,
            environment=environment,
        )
        assert second.returncode == 0, second.stderr
        assert "already installed:" in second.stdout.lower()
        assert (target / "SKILL.md").read_bytes() == expected

    old_project = root / "project-with-old-skill"
    old_project.mkdir()
    old_target = old_project / ".agents" / "skills" / "signalweave"
    old_target.mkdir(parents=True)
    old_skill = old_target / "SKILL.md"
    old_content = b"---\nname: signalweave\n---\nOld project-local skill\n"
    old_skill.write_bytes(old_content)

    conflict = _run_cli(
        command,
        "skills",
        "install",
        "--agent",
        "codex",
        "--scope",
        "project",
        cwd=old_project,
        environment=environment,
    )
    assert conflict.returncode != 0
    assert "never overwrites" in conflict.stderr.lower()
    assert old_skill.read_bytes() == old_content

    # Project installs must not fall back to either client's user-level location.
    assert list(home.iterdir()) == []


def test_source_cli_skill_journey_isolated_and_idempotent(tmp_path):
    _exercise_project_skill_journey(SOURCE_CLI, tmp_path, source_cli=True)


@pytest.mark.skipif(
    not os.environ.get("SIGNALWEAVE_TEST_BINARY"),
    reason="set SIGNALWEAVE_TEST_BINARY to opt into the real native executable journey",
)
def test_opt_in_native_binary_skill_journey_isolated_and_idempotent(tmp_path):
    binary = Path(os.environ["SIGNALWEAVE_TEST_BINARY"]).expanduser().resolve()
    assert binary.is_file(), f"SIGNALWEAVE_TEST_BINARY is not a file: {binary}"
    assert os.access(binary, os.X_OK), f"SIGNALWEAVE_TEST_BINARY is not executable: {binary}"
    _exercise_project_skill_journey((str(binary),), tmp_path, source_cli=False)
