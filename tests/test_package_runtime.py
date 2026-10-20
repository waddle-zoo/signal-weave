import platform
import tarfile

import pytest
from test_install import VERSION

from scripts import package_release as module


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    root = tmp_path / "build"
    root.mkdir()
    binary = root / "signalweave"
    binary.write_bytes(b"native fixture")
    binary.chmod(0o755)
    runtime = root / "_internal"
    runtime.mkdir()
    monkeypatch.setattr(module, "verify_binary", lambda _: {"bundle_layout": "directory-v1", "git_commit": "a" * 40})
    target = module.TARGETS[(platform.system(), platform.machine())]
    return binary, runtime, tmp_path / "release", target


def test_directory_package_contains_regular_runtime_files(candidate):
    binary, runtime, output, target = candidate
    (runtime / "libpython.so").write_bytes(b"dependency")
    (runtime / "alias.so").symlink_to("libpython.so")
    archive = module.package(binary, output, VERSION, target)
    with tarfile.open(archive) as reader:
        files = reader.getmembers()
        assert all(item.isfile() for item in files)
        assert {item.name for item in files} == {"signalweave", "LICENSE", "build-info.json", "_internal/libpython.so", "_internal/alias.so"}
        assert reader.extractfile("_internal/alias.so").read() == b"dependency"


@pytest.mark.parametrize("kind", ["outside", "cycle", "bad-name", "empty"])
def test_unsafe_or_empty_runtime_fails_before_creating_release(candidate, tmp_path, kind):
    binary, runtime, output, target = candidate
    if kind == "outside":
        outside = tmp_path / "unrelated"
        outside.write_text("do not package")
        (runtime / "escape").symlink_to(outside)
    elif kind == "cycle":
        (runtime / "loop").symlink_to(runtime, target_is_directory=True)
    elif kind == "bad-name":
        (runtime / "bad\nname").write_text("bad")
    with pytest.raises(ValueError):
        module.package(binary, output, VERSION, target)
    assert not output.exists()
