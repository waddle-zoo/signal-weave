"""Build the local platform's standalone SignalWeave executable."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

if __package__:
    from .binary_provenance import build_metadata, source_fingerprint
    from .check_ca_bundle import check_bundle, check_installed_certifi
else:
    from binary_provenance import build_metadata, source_fingerprint
    from check_ca_bundle import check_bundle, check_installed_certifi

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    from importlib.metadata import version

    metadata = build_metadata()
    metadata["bundle_layout"] = "directory-v1"
    metadata["tls_trust"] = check_installed_certifi()
    if version("signal-weave") != metadata["version"]:
        raise RuntimeError("Installed package metadata is stale; sync the environment before building")
    skill_file = ROOT / "skills" / "signalweave" / "SKILL.md"
    if skill_file.is_symlink() or not skill_file.is_file() or not skill_file.read_text(encoding="utf-8").strip():
        raise RuntimeError("Canonical SignalWeave skill is missing or invalid; cannot build the executable")
    manifest = ROOT / "build" / "signalweave-build.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(metadata, indent=2) + "\n")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir",
        "--name", "signalweave", "--paths", str(ROOT / "src"),
        "--specpath", str(ROOT / "build"), "--workpath", str(ROOT / "build" / "binary"),
        "--distpath", str(ROOT / "dist"),
        "--collect-submodules", "signalweave", "--collect-submodules", "sqlglot",
        "--collect-all", "typesafe_sdk",
        "--copy-metadata", "mcp", "--copy-metadata", "signal-weave",
        "--add-data", str(manifest) + os.pathsep + ".",
        "--add-data", str(skill_file) + os.pathsep + "signalweave_skill",
        str(ROOT / "scripts" / "frozen_entrypoint.py"),
    ], cwd=ROOT, env={**os.environ, "PYINSTALLER_CONFIG_DIR": str(ROOT / "build" / "pyinstaller-cache")}, check=True)
    check_bundle(ROOT / "dist/signalweave/_internal/certifi/cacert.pem",
                 expected_sha256=metadata["tls_trust"]["bundle_sha256"])
    if source_fingerprint() != metadata["source_sha256"]:
        raise RuntimeError("Source changed during the build; rebuild before testing or packaging")


if __name__ == "__main__":
    main()
