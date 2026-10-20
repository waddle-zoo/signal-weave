"""Package a native, already smoke-tested binary without overwriting artifacts."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import tarfile
from pathlib import Path

import tomllib

if __package__:
    from .binary_provenance import verify_binary
else:
    from binary_provenance import verify_binary

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {("Darwin", "arm64"): "darwin-arm64", ("Darwin", "x86_64"): "darwin-x86_64",
           ("Linux", "x86_64"): "linux-x86_64"}


def runtime_members(root: Path):
    """Flatten bundle-local links into regular archive files; never export external targets."""
    bundle = root.parent.resolve()
    pending = [(root, frozenset())]
    count = 0
    while pending:
        path, ancestors = pending.pop()
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(bundle):
            raise ValueError("Runtime link escapes its bundle")
        if resolved.is_dir():
            if resolved in ancestors:
                raise ValueError("Runtime contains a directory-link cycle")
            pending.extend((child, ancestors | {resolved}) for child in sorted(path.iterdir()))
        elif resolved.is_file():
            count += 1
            if count > 20_000:
                raise ValueError("Runtime has too many files")
            yield path.relative_to(root.parent).as_posix(), resolved
        else:
            raise ValueError("Runtime contains a special file")


def package(binary: Path, output: Path, version: str, target: str) -> Path:
    expected = "v" + tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    if not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(rc[1-9][0-9]*)?", version) or version != expected:
        raise ValueError("Release tag must be vMAJOR.MINOR.PATCH[rcN] and match pyproject.toml")
    if TARGETS.get((platform.system(), platform.machine())) != target:
        raise ValueError("Native platform does not match the requested artifact target")
    if binary.is_symlink() or not binary.is_file() or not binary.stat().st_size:
        raise ValueError("Expected a nonempty regular binary")
    identity = verify_binary(binary)
    internal = binary.parent / "_internal"
    resources = []
    if identity.get("bundle_layout") == "directory-v1":
        if internal.is_symlink() or not internal.is_dir():
            raise ValueError("Directory bundle is missing its regular _internal directory")
        resources = list(runtime_members(internal))
        if not resources:
            raise ValueError("Directory bundle has no runtime files")
        for name, _ in resources:
            if not re.fullmatch(r"_internal/[A-Za-z0-9_.+@/ -]+", name) or any(
                part in {"", ".", ".."} for part in name.split("/")
            ):
                raise ValueError("Unsupported runtime archive path")
        if sum(path.stat().st_size for _, path in resources) > 1_000_000_000:
            raise ValueError("Runtime exceeds release size bound")
    metadata = json.dumps({**identity, "version": version, "target": target,
                           "commit": identity["git_commit"]}, indent=2).encode() + b"\n"
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
        for name, path in resources:
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = path.stat().st_size, 0o755 if os.access(path, os.X_OK) else 0o644, 0
            with path.open("rb") as stream:
                archive.addfile(info, stream)
    with checksum.open("x") as stream:
        stream.write(f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}\n")
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "dist/signalweave/signalweave")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/release")
    parser.add_argument("--version", required=True)
    parser.add_argument("--target", choices=sorted(TARGETS.values()), required=True)
    args = parser.parse_args()
    print(package(args.binary, args.output, args.version, args.target))


if __name__ == "__main__":
    main()
