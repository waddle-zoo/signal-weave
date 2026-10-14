"""Show or explicitly install the bundled SignalWeave agent skill."""

from __future__ import annotations

import shutil
import site
import sys
import sysconfig
import tempfile
from pathlib import Path

SKILL_RELATIVE_PATH = Path("skills") / "signalweave" / "SKILL.md"
BUNDLE_PATH = Path("signalweave_skill") / "SKILL.md"
DATA_PATH = Path("share") / "signalweave" / "skills" / "signalweave" / "SKILL.md"


class SkillInstallError(ValueError):
    """A missing bundle or an unsafe/conflicting installation target."""


def resolve_skill_file(
    *,
    frozen: bool | None = None,
    bundle_dir: Path | None = None,
    module_file: Path | None = None,
    data_roots: tuple[Path, ...] | None = None,
) -> Path:
    """Find the canonical source, frozen payload, or wheel data-file copy."""
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if is_frozen:
        root = bundle_dir if bundle_dir is not None else Path(getattr(sys, "_MEIPASS", ""))
        candidate = root / BUNDLE_PATH
        if candidate.is_symlink() or not candidate.is_file():
            raise SkillInstallError(
                "Bundled SignalWeave skill is missing or unsafe; rebuild the executable"
            )
        return candidate

    module = Path(module_file or __file__).resolve()
    candidates = [module.parents[2] / SKILL_RELATIVE_PATH]
    roots = (
        data_roots
        if data_roots is not None
        else tuple(Path(item) for item in (sysconfig.get_path("data"), site.USER_BASE) if item)
    )
    candidates.extend(root / DATA_PATH for root in roots)
    for candidate in candidates:
        if candidate.is_symlink():
            raise SkillInstallError("SignalWeave skill source must not be a symlink")
        if candidate.is_file():
            return candidate
    raise SkillInstallError(
        "SignalWeave skill is not bundled; install the package or rebuild the executable"
    )


def skill_text() -> str:
    path = resolve_skill_file()
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SkillInstallError("Could not read the bundled SignalWeave skill") from error
    if not content.strip():
        raise SkillInstallError("The bundled SignalWeave skill is empty")
    return content


def _checked_directory(path: Path, *, create: bool) -> None:
    if path.is_symlink():
        raise SkillInstallError(f"Refusing symlink in skill install path: {path}")
    if path.exists():
        if not path.is_dir():
            raise SkillInstallError(f"Skill install path is not a directory: {path}")
    elif create:
        path.mkdir(mode=0o755)


def _target(agent: str, scope: str, project_root: Path | None, home: Path | None) -> Path:
    if agent not in {"codex", "claude"}:
        raise SkillInstallError("Choose --agent codex or --agent claude")
    if scope not in {"project", "user"}:
        raise SkillInstallError("Choose --scope project or --scope user")
    root = (
        (Path(project_root) if scope == "project" else Path(home or Path.home()))
        .expanduser()
        .absolute()
    )
    parent_name = ".agents" if agent == "codex" else ".claude"
    return root / parent_name / "skills" / "signalweave"


def _existing_target(target: Path, content: bytes) -> bool:
    if target.is_symlink():
        raise SkillInstallError(f"Refusing to replace a symlink: {target}")
    if not target.exists():
        return False
    if not target.is_dir():
        raise SkillInstallError(f"A non-directory already occupies {target}")
    children = list(target.iterdir())
    if any(child.is_symlink() for child in children):
        raise SkillInstallError(f"Refusing symlink inside existing skill directory: {target}")
    if len(children) == 1 and children[0].name == "SKILL.md" and children[0].is_file():
        if children[0].read_bytes() == content:
            return True
    raise SkillInstallError(
        f"Existing skill directory differs from the bundled skill: {target}. "
        "Review it manually; SignalWeave never overwrites existing contents."
    )


def _install_file(skill_file: Path, target: Path) -> str:
    if skill_file.is_symlink() or not skill_file.is_file():
        raise SkillInstallError("Bundled SignalWeave skill must be a regular SKILL.md file")
    content = skill_file.read_bytes()
    if not content.strip():
        raise SkillInstallError("The bundled SignalWeave skill is empty")

    root = target.parents[2]
    _checked_directory(root, create=False)
    _checked_directory(target.parents[1], create=True)
    _checked_directory(target.parent, create=True)
    if _existing_target(target, content):
        return "already_installed"

    stage = Path(tempfile.mkdtemp(prefix=".signalweave-skill-", dir=target.parent))
    created_target = False
    created_file = False
    completed = False
    try:
        staged_file = stage / "SKILL.md"
        staged_file.write_bytes(content)
        staged_file.chmod(0o644)
        if {item.name for item in stage.iterdir()} != {
            "SKILL.md"
        } or staged_file.read_bytes() != content:
            raise SkillInstallError("Staged skill verification failed")

        # mkdir is the no-overwrite claim: unlike replace/rename, it fails if a
        # target appeared after the earlier conflict check.
        target.mkdir(mode=0o755)
        created_target = True
        installed_file = target / "SKILL.md"
        with installed_file.open("xb") as stream:
            created_file = True
            stream.write(content)
        installed_file.chmod(0o644)
        if installed_file.is_symlink() or installed_file.read_bytes() != content:
            raise SkillInstallError("Installed skill verification failed")
        completed = True
        return "installed"
    except FileExistsError as error:
        raise SkillInstallError(
            f"An installation target appeared during install: {target}. No existing file was overwritten."
        ) from error
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if created_target and not completed:
            if created_file:
                try:
                    installed_file.unlink()
                except OSError:
                    pass
            try:
                target.rmdir()
            except OSError:
                pass


def install_skill(
    agent: str,
    scope: str = "project",
    *,
    project_root: Path | None = None,
    home: Path | None = None,
) -> tuple[str, Path]:
    """Install only the skill folder; never edits Codex/Claude configuration."""
    skill_file = resolve_skill_file()
    target = _target(agent, scope, project_root or Path.cwd(), home)
    status = _install_file(skill_file, target)
    return status, target
