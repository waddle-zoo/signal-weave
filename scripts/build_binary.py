"""Build the local platform's standalone SignalWeave executable."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

if __package__:
    from .binary_provenance import build_metadata, source_fingerprint
else:
    from binary_provenance import build_metadata, source_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    from importlib.metadata import version

    metadata = build_metadata()
    if version("signal-weave") != metadata["version"]:
        raise RuntimeError("Installed package metadata is stale; sync the environment before building")
    manifest = ROOT / "build" / "signalweave-build.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(metadata, indent=2) + "\n")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile",
        "--name", "signalweave", "--paths", str(ROOT / "src"),
        "--specpath", str(ROOT / "build"), "--workpath", str(ROOT / "build" / "binary"),
        "--distpath", str(ROOT / "dist"),
        "--collect-submodules", "signalweave", "--collect-all", "typesafe_sdk",
        "--copy-metadata", "mcp", "--copy-metadata", "signal-weave",
        "--add-data", str(manifest) + os.pathsep + ".",
        str(ROOT / "scripts" / "frozen_entrypoint.py"),
    ], cwd=ROOT, env={**os.environ, "PYINSTALLER_CONFIG_DIR": str(ROOT / "build" / "pyinstaller-cache")}, check=True)
    if source_fingerprint() != metadata["source_sha256"]:
        raise RuntimeError("Source changed during the build; rebuild before testing or packaging")


if __name__ == "__main__":
    main()
