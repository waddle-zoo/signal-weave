"""Exercise the real shell installer with a fake HTTPS transport and private home."""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import tomllib

from scripts.package_release import ROOT, TARGETS, package

INSTALLER = ROOT / "scripts/install.sh"
VERSION = "v" + tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
BASE = "https://github.com/waddle-zoo/signal-weave/releases"


@pytest.fixture
def install_env(tmp_path):
    home, commands, fixtures = [tmp_path / name for name in ("home", "commands", "fixtures")]
    for folder in (home, commands, fixtures):
        folder.mkdir()
    fake_curl = commands / "curl"
    fake_curl.write_text(f"#!{sys.executable}\n" + '''
import os, pathlib, shutil, sys
args = sys.argv[1:]
assert args[args.index('--proto') + 1] == '=https'
assert args[args.index('--proto-redir') + 1] == '=https'
assert '--fail' in args and '--location' in args
url = args[-1]
assert url.startswith('https://github.com/waddle-zoo/signal-weave/releases/')
with open(os.environ['REQUEST_LOG'], 'a') as log:
    log.write(url + '\\n')
if os.environ.get('FAIL_DOWNLOAD') and url.endswith(os.environ['FAIL_DOWNLOAD']):
    sys.exit(22)
if url.endswith('/latest'):
    print(os.environ['LATEST_URL'], end='')
else:
    source = pathlib.Path(os.environ['FIXTURES']) / url.rsplit('/', 1)[1]
    if not source.exists():
        sys.exit(22)
    shutil.copyfile(source, args[args.index('--output') + 1])
''')
    fake_curl.chmod(0o755)
    uname = commands / "uname"
    uname.write_text('#!/bin/sh\ncase "$1" in -s) echo "$TEST_OS";; -m) echo "$TEST_ARCH";; *) exit 1;; esac\n')
    uname.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if not key.startswith("SIGNALWEAVE_")}
    env.update(HOME=str(home), FIXTURES=str(fixtures), REQUEST_LOG=str(tmp_path / "requests"),
               TEST_OS="Linux", TEST_ARCH="x86_64", LATEST_URL=f"{BASE}/tag/{VERSION}",
               PATH=str(commands) + os.pathsep + os.environ["PATH"])
    return env


def release(env, *, target="linux-x86_64", members=None, executable=b"#!/bin/sh\nexit 0\n"):
    asset = f"signalweave-{VERSION}-{target}.tar.gz"
    archive = Path(env["FIXTURES"]) / asset
    if members is None:
        members = [("signalweave", executable, tarfile.REGTYPE),
                   ("LICENSE", b"License", tarfile.REGTYPE),
                   ("build-info.json", b"{}", tarfile.REGTYPE)]
    with tarfile.open(archive, "w:gz", format=tarfile.USTAR_FORMAT) as stream:
        for name, content, kind in members:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.mode = 0o755
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                member.linkname = "../../outside"
            else:
                member.size = len(content)
            stream.addfile(member, io.BytesIO(content))
    checksum = archive.with_name(asset + ".sha256")
    checksum.write_text(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {asset}\n")
    return archive, checksum


def run(env, *args, timeout=15):
    return subprocess.run(["sh", str(INSTALLER), *args], cwd=env["HOME"], env=env,
                          text=True, capture_output=True, timeout=timeout)


def installed(env):
    return Path(env["HOME"]) / ".local/bin/signalweave"


@pytest.mark.parametrize(("system", "arch", "target"), [
    ("Linux", "x86_64", "linux-x86_64"), ("Darwin", "arm64", "darwin-arm64"),
    ("Darwin", "x86_64", "darwin-x86_64"),
])
def test_native_detection_and_latest_install(install_env, system, arch, target):
    env = {**install_env, "TEST_OS": system, "TEST_ARCH": arch}
    release(env, target=target)
    result = run(env)
    assert result.returncode == 0, result.stderr
    assert installed(env).stat().st_mode & 0o777 == 0o755
    assert VERSION in result.stdout
    assert '" setup' in result.stdout
    assert not list(installed(env).parent.glob(".signalweave-install.*"))
    assert not (Path(env["HOME"]) / ".signalweave").exists()
    requests = Path(env["REQUEST_LOG"]).read_text().splitlines()
    assert requests == [f"{BASE}/latest", f"{BASE}/download/{VERSION}/signalweave-{VERSION}-{target}.tar.gz.sha256",
                        f"{BASE}/download/{VERSION}/signalweave-{VERSION}-{target}.tar.gz"]


def test_explicit_version_no_latest_lookup(install_env):
    release(install_env)
    assert run(install_env, "--version", VERSION).returncode == 0
    assert "/latest" not in Path(install_env["REQUEST_LOG"]).read_text()


@pytest.mark.parametrize("version", ["../main", "v1.2.3/../../escape", "v1.2.3\nx", "v01.2.3", "1.2.3", "v1.2.3-rc.1", ""])
def test_version_injection_rejected_before_network(install_env, version):
    assert run(install_env, "--version", version).returncode != 0
    assert not Path(install_env["REQUEST_LOG"]).exists()


@pytest.mark.parametrize("url", ["https://evil.example/tag/v1.2.3", f"{BASE}/tag/v1.2.3/../x", f"{BASE}/tag/v1.2.3-rc.1"])
def test_latest_redirect_must_be_official_stable_tag(install_env, url):
    assert run({**install_env, "LATEST_URL": url}).returncode != 0
    assert not installed(install_env).exists()


@pytest.mark.parametrize("failure", ["checksum", "malformed-checksum", "missing-checksum", "archive-download", "startup"])
def test_failed_install_never_replaces_existing(install_env, failure):
    executable = b"#!/bin/sh\nexit 42\n" if failure == "startup" else b"#!/bin/sh\nexit 0\n"
    archive, checksum = release(install_env, executable=executable)
    destination = installed(install_env)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"keep my installation")
    if failure == "checksum":
        archive.write_bytes(b"corruption")
    elif failure == "malformed-checksum":
        checksum.write_text("not a checksum\n")
    elif failure == "missing-checksum":
        checksum.unlink()
    elif failure == "archive-download":
        install_env["FAIL_DOWNLOAD"] = ".tar.gz"
    result = run(install_env, "--version", VERSION, "--replace")
    assert result.returncode != 0
    assert destination.read_bytes() == b"keep my installation"
    assert not list(destination.parent.glob(".signalweave-install.*"))


@pytest.mark.parametrize(("name", "kind"), [
    ("../../outside", tarfile.REGTYPE), ("/tmp/outside", tarfile.REGTYPE),
    ("signalweave", tarfile.SYMTYPE), ("signalweave", tarfile.LNKTYPE),
    ("signalweave", tarfile.FIFOTYPE), ("./signalweave", tarfile.REGTYPE),
])
def test_archive_paths_links_special_files_rejected(install_env, name, kind):
    release(install_env, members=[(name, b"fake", kind), ("LICENSE", b"x", tarfile.REGTYPE),
                                  ("build-info.json", b"{}", tarfile.REGTYPE)])
    result = run(install_env, "--version", VERSION)
    assert result.returncode != 0, result.stdout
    assert not installed(install_env).exists()
    assert not (Path(install_env["HOME"]) / ".local/outside").exists()


def test_duplicate_member_rejected(install_env):
    release(install_env, members=[("signalweave", b"fake", tarfile.REGTYPE)] * 3)
    assert run(install_env, "--version", VERSION).returncode != 0


def test_existing_requires_explicit_replacement(install_env):
    release(install_env)
    assert run(install_env, "--version", VERSION).returncode == 0
    original = installed(install_env).read_bytes()
    release(install_env, executable=b"#!/bin/sh\n# new version\nexit 0\n")
    assert run(install_env, "--version", VERSION).returncode != 0
    assert installed(install_env).read_bytes() == original
    assert run(install_env, "--version", VERSION, "--replace").returncode == 0
    assert installed(install_env).read_bytes() != original


def test_symlink_destination_is_never_replaced(install_env):
    release(install_env)
    target = Path(install_env["HOME"]) / "keep"
    target.write_text("original")
    installed(install_env).parent.mkdir(parents=True)
    installed(install_env).symlink_to(target)
    assert run(install_env, "--version", VERSION, "--replace").returncode != 0
    assert target.read_text() == "original"


def test_concurrent_creation_not_overwritten(install_env):
    release(install_env, executable=b'#!/bin/sh\nprintf raced > "$HOME/.local/bin/signalweave"\n')
    assert run(install_env, "--version", VERSION).returncode != 0
    assert installed(install_env).read_text() == "raced"


def test_custom_install_directory_with_spaces(install_env):
    folder = Path(install_env["HOME"]) / "custom folder/bin"
    release(install_env)
    assert run({**install_env, "SIGNALWEAVE_INSTALL_DIR": str(folder)}, "--version", VERSION).returncode == 0
    assert (folder / "signalweave").exists()


def test_unsupported_platform_no_download(install_env):
    assert run({**install_env, "TEST_ARCH": "aarch64"}).returncode != 0
    assert not Path(install_env["REQUEST_LOG"]).exists()


def test_package_archive_is_small_explicit_contract(tmp_path):
    binary = tmp_path / "binary"
    binary.write_bytes(b"fake binary")
    target = TARGETS[(platform.system(), platform.machine())]
    artifact = package(binary, tmp_path / "release", VERSION, target)
    with tarfile.open(artifact) as archive:
        assert archive.getnames() == ["signalweave", "LICENSE", "build-info.json"]
        assert all(member.isfile() for member in archive.getmembers())
        assert archive.getmember("signalweave").mode == 0o755
        metadata = json.load(archive.extractfile("build-info.json"))
        assert metadata["version"] == VERSION and metadata["target"] == target
        assert len(metadata["commit"]) == 40
    checksum = artifact.with_name(artifact.name + ".sha256").read_text()
    assert checksum == f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}\n"
    with pytest.raises(FileExistsError):
        package(binary, tmp_path / "release", VERSION, target)


def test_package_rejects_wrong_version_or_platform(tmp_path):
    binary = tmp_path / "binary"
    binary.write_bytes(b"fake binary")
    with pytest.raises(ValueError, match="tag"):
        package(binary, tmp_path, "v99999.0.0", "linux-x86_64")
    with pytest.raises(ValueError, match="platform"):
        package(binary, tmp_path, VERSION, "not-this-platform")


def test_release_workflow_pins_actions_and_has_no_model_secrets():
    import re
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    actions = re.findall(r"uses: ([^\s]+)", workflow)
    assert actions and all(re.fullmatch(r"[\w/-]+@[0-9a-f]{40}", action) for action in actions)
    assert "secrets." not in workflow and "--clobber" not in workflow
    assert "uv sync --locked" in workflow and "scripts/check_binary.py" in workflow
    assert "github.event_name == 'push'" in workflow


@pytest.mark.asyncio
async def test_binary_without_setup_cannot_pass_release_smoke(tmp_path):
    from scripts.check_binary import check

    old_binary = tmp_path / "old-binary"
    old_binary.write_text('#!/bin/sh\ncase "$1" in setup) exit 2;; *) exit 0;; esac\n')
    old_binary.chmod(0o755)
    with pytest.raises(RuntimeError, match="Binary command failed"):
        await check(old_binary, None, live=False)


@pytest.mark.skipif(not os.getenv("SIGNALWEAVE_TEST_BINARY"), reason="Opt-in native binary installer smoke")
def test_real_binary_installs_and_initializes(install_env, tmp_path):
    binary = Path(os.environ["SIGNALWEAVE_TEST_BINARY"]).resolve()
    system, architecture = platform.system(), platform.machine()
    env = {**install_env, "TEST_OS": system, "TEST_ARCH": architecture}
    package(binary, Path(env["FIXTURES"]), VERSION, TARGETS[(system, architecture)])
    result = run(env, "--version", VERSION, timeout=90)
    assert result.returncode == 0, result.stderr
    # Use the installed path, not dist/. The checker creates another private home
    # outside the checkout and requires setup, source secrets, persisted identity,
    # doctor, agent config, and an actual MCP initialize/list-tools handshake.
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_binary.py"), "--binary", str(installed(env))],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, "Installed wizard/MCP smoke failed; diagnostic output withheld"
    report = json.loads(result.stdout)
    assert report["private_setup"] and report["persisted_source_config"]
    assert report["offline_doctor"] and report["agent_config"] and report["stdio_tools"] > 0
    assert report["different_cwd"] and not report["live"]
