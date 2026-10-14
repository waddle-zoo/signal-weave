from __future__ import annotations

import sys
from pathlib import Path

import pytest

from signalweave import cli
from signalweave.skill_install import (
    SkillInstallError,
    install_skill,
    resolve_skill_file,
    skill_text,
)

REPO = Path(__file__).resolve().parents[1]
CANONICAL_SKILL = REPO / "skills" / "signalweave" / "SKILL.md"


def run_cli(monkeypatch, *arguments: str) -> None:
    monkeypatch.setattr(sys, "argv", ["signalweave", *arguments])
    cli.main()


def test_resolver_finds_source_frozen_and_wheel_payloads(tmp_path):
    source_root = tmp_path / "source"
    module = source_root / "src" / "signalweave" / "skill_install.py"
    module.parent.mkdir(parents=True)
    source_skill = source_root / "skills" / "signalweave" / "SKILL.md"
    source_skill.parent.mkdir(parents=True)
    source_skill.write_text("source skill\n")
    assert resolve_skill_file(frozen=False, module_file=module, data_roots=()) == source_skill

    bundle_root = tmp_path / "bundle"
    bundled_skill = bundle_root / "signalweave_skill" / "SKILL.md"
    bundled_skill.parent.mkdir(parents=True)
    bundled_skill.write_text("frozen skill\n")
    assert resolve_skill_file(frozen=True, bundle_dir=bundle_root) == bundled_skill

    wheel_root = tmp_path / "wheel-data"
    wheel_skill = wheel_root / "share" / "signalweave" / "skills" / "signalweave" / "SKILL.md"
    wheel_skill.parent.mkdir(parents=True)
    wheel_skill.write_text("wheel skill\n")
    assert (
        resolve_skill_file(
            frozen=False,
            module_file=tmp_path / "installed" / "signalweave" / "skill_install.py",
            data_roots=(wheel_root,),
        )
        == wheel_skill
    )


def test_show_prints_canonical_skill_without_installing(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    run_cli(monkeypatch, "skills", "show")
    assert capsys.readouterr().out == CANONICAL_SKILL.read_text(encoding="utf-8")
    assert list(tmp_path.iterdir()) == []


def test_project_install_is_explicit_exact_and_idempotent(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    run_cli(monkeypatch, "skills", "install", "--agent", "codex")
    destination = tmp_path / ".agents" / "skills" / "signalweave"
    installed = destination / "SKILL.md"
    expected = CANONICAL_SKILL.read_bytes()
    assert installed.read_bytes() == expected
    assert {item.name for item in destination.iterdir()} == {"SKILL.md"}
    assert "installed:" in capsys.readouterr().out
    assert not (tmp_path / ".codex").exists()

    run_cli(monkeypatch, "skills", "install", "--agent", "codex")
    assert installed.read_bytes() == expected
    assert "already installed:" in capsys.readouterr().out


def test_user_install_uses_selected_agent_directory_only(monkeypatch, capsys, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(Path, "home", lambda: home)

    run_cli(monkeypatch, "skills", "install", "--agent", "claude", "--scope", "user")

    destination = home / ".claude" / "skills" / "signalweave" / "SKILL.md"
    assert destination.read_bytes() == CANONICAL_SKILL.read_bytes()
    assert not (project / ".claude").exists()
    assert not (home / ".agents").exists()
    assert "installed:" in capsys.readouterr().out


@pytest.mark.parametrize("agent,parent", [("codex", ".agents"), ("claude", ".claude")])
@pytest.mark.parametrize("scope", ["project", "user"])
def test_agent_and_scope_map_to_expected_skill_directory(tmp_path, agent, parent, scope):
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home.mkdir()
    root = project if scope == "project" else home

    status, target = install_skill(agent, scope, project_root=project, home=home)

    assert status == "installed"
    assert target == root / parent / "skills" / "signalweave"
    assert (target / "SKILL.md").read_bytes() == CANONICAL_SKILL.read_bytes()


def test_existing_different_content_is_preserved_and_rejected(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = project / ".agents" / "skills" / "signalweave"
    target.mkdir(parents=True)
    skill_file = target / "SKILL.md"
    skill_file.write_text("someone else's skill\n")

    with pytest.raises(SkillInstallError, match="never overwrites"):
        install_skill("codex", project_root=project)

    assert skill_file.read_text() == "someone else's skill\n"


def test_exact_existing_skill_is_idempotent_and_extra_files_conflict(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = project / ".agents" / "skills" / "signalweave"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_bytes(CANONICAL_SKILL.read_bytes())

    assert install_skill("codex", project_root=project)[0] == "already_installed"
    (target / "notes.txt").write_text("keep me\n")
    with pytest.raises(SkillInstallError, match="never overwrites"):
        install_skill("codex", project_root=project)
    assert (target / "notes.txt").read_text() == "keep me\n"


def test_symlink_target_and_parent_are_refused(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = project / ".agents" / "skills" / "signalweave"
    target.parent.mkdir(parents=True)
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SkillInstallError, match="symlink"):
        install_skill("codex", project_root=project)
    assert list(outside.iterdir()) == []

    alternate_project = tmp_path / "alternate-project"
    alternate_project.mkdir()
    (alternate_project / ".agents").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SkillInstallError, match="symlink"):
        install_skill("codex", project_root=alternate_project)
    assert list(outside.iterdir()) == []


def test_existing_skill_directory_with_symlink_is_refused(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = project / ".agents" / "skills" / "signalweave"
    target.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched\n")
    (target / "SKILL.md").symlink_to(outside)

    with pytest.raises(SkillInstallError, match="symlink"):
        install_skill("codex", project_root=project)
    assert outside.read_text() == "untouched\n"


def test_cli_reports_conflicts_without_overwriting(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    conflict = tmp_path / ".claude" / "skills" / "signalweave"
    conflict.mkdir(parents=True)
    (conflict / "SKILL.md").write_text("keep\n")

    with pytest.raises(SystemExit) as error:
        run_cli(monkeypatch, "skills", "install", "--agent", "claude")

    assert error.value.code == 1
    assert (conflict / "SKILL.md").read_text() == "keep\n"
    assert "never overwrites" in capsys.readouterr().err


def test_skill_text_is_the_resolved_payload(monkeypatch, tmp_path):
    bundled = tmp_path / "SKILL.md"
    bundled.write_text("exact payload\n")
    monkeypatch.setattr("signalweave.skill_install.resolve_skill_file", lambda: bundled)
    assert skill_text() == "exact payload\n"
