"""Package a native, already smoke-tested binary without overwriting artifacts."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import re
import subprocess
import tarfile
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {("Darwin", "arm64"): "darwin-arm64", ("Darwin", "x86_64"): "darwin-x86_64",
           ("Linux", "x86_64"): "linux-x86_64"}


def package(binary: Path, output: Path, version: str, target: str) -> Path:
    expected = "v" + tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    if not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(rc[1-9][0-9]*)?", version) or version != expected:
        raise ValueError("Release tag must be vMAJOR.MINOR.PATCH[rcN] and match pyproject.toml")
    if TARGETS.get((platform.system(), platform.machine())) != target:
        raise ValueError("Native platform does not match the requested artifact target")
    if binary.is_symlink() or not binary.is_file() or not binary.stat().st_size:
        raise ValueError("Expected a nonempty regular binary")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    metadata = json.dumps({"version": version, "target": target, "commit": commit,
                           "python": platform.python_version()}, indent=2).encode() + b"\n"
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / f"signalweave-{version}-{target}.tar.gz"
    checksum = artifact.with_name(artifact.name + ".sha256")
    if artifact.exists() or checksum.exists() or artifact.is_symlink() or checksum.is_symlink():
        raise FileExistsError("Refusing to overwrite release artifacts")
    with artifact.open("xb") as stream, tarfile.open(fileobj=stream, mode="w:gz", format=tarfile.USTAR_FORMAT) as archive:
        for name, data, mode in [("signalweave", binary.read_bytes(), 0o755),
                                 ("LICENSE", (ROOT / "LICENSE").read_bytes(), 0o644),
                                 ("build-info.json", metadata, 0o644)]:
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), mode, 0
            archive.addfile(info, io.BytesIO(data))
    with checksum.open("x") as stream:
        stream.write(f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}\n")
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "dist/signalweave")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/release")
    parser.add_argument("--version", required=True)
    parser.add_argument("--target", choices=sorted(TARGETS.values()), required=True)
    args = parser.parse_args()
    print(package(args.binary, args.output, args.version, args.target))


if __name__ == "__main__":
    main()
