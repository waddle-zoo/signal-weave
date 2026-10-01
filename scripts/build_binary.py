"""Build the local platform's standalone SignalWeave executable."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile",
        "--name", "signalweave", "--paths", str(ROOT / "src"),
        "--specpath", str(ROOT / "build"), "--workpath", str(ROOT / "build" / "binary"),
        "--distpath", str(ROOT / "dist"),
        "--collect-submodules", "signalweave", "--collect-all", "typesafe_sdk",
        "--copy-metadata", "mcp", "--copy-metadata", "signal-weave",
        str(ROOT / "scripts" / "frozen_entrypoint.py"),
    ], cwd=ROOT, env={**os.environ, "PYINSTALLER_CONFIG_DIR": str(ROOT / "build" / "pyinstaller-cache")}, check=True)


if __name__ == "__main__":
    main()
