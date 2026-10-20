import json
import subprocess
import tarfile
from pathlib import Path

import pytest
from test_fresh_install_journey import _piped_install
from test_install import VERSION, installed, release, run
from test_install import install_env as install_env


def curl_calls(env):
    return [json.loads(line) for line in Path(env["CURL_ARGS_LOG"]).read_text().splitlines()]


def logged_env(env, **options):
    return {**env, "CURL_ARGS_LOG": str(Path(env["HOME"]).parent / "curl-args"), **options}


def test_noninteractive_download_has_plain_phase_messages(install_env):
    env = logged_env(install_env)
    release(env)
    result = run(env, "--version", VERSION)
    assert result.returncode == 0
    assert all(f"[{n}/4]" in result.stderr for n in range(1, 5))
    assert "\033" not in result.stderr and "\r" not in result.stderr
    assert "--silent" in curl_calls(env)[-1]
    assert "--progress-bar" not in curl_calls(env)[-1]


@pytest.mark.parametrize("term,no_color,bar,color", [("xterm", "", True, True), ("xterm", "1", True, False), ("dumb", "", False, False)])
def test_terminal_download_progress_and_color_preferences(install_env, term, no_color, bar, color):
    env = logged_env(install_env, TERM=term, NO_COLOR=no_color)
    release(env)
    result = _piped_install(env, "--version", VERSION)
    assert result.returncode == 0, result.stdout
    assert ("--progress-bar" in curl_calls(env)[-1]) is bar
    assert ("\033[" in result.stdout) is color
    assert "[1/4] Downloading" in result.stdout and "[4/4] Ready" in result.stdout


def test_quiet_suppresses_success_but_not_errors(install_env):
    env = logged_env(install_env)
    archive, checksum = release(env)
    result = run(env, "--version", VERSION, "--quiet")
    assert result.returncode == 0 and result.stdout == result.stderr == ""
    original = installed(env).read_bytes()
    checksum.write_text("0" * 64 + "  " + archive.name + "\n")
    failed = run(env, "--version", VERSION, "--replace", "-q")
    assert failed.returncode != 0 and "Checksum mismatch" in failed.stderr
    assert "[1/4]" not in failed.stderr and failed.stdout == ""
    assert installed(env).read_bytes() == original


def bundle(env, *, extra=None, executable=None):
    native = executable or b'''#!/bin/sh
test -f "$(dirname "$0")/_internal/runtime.txt" || exit 17
printf 'SignalWeave bundle fixture\\n'
'''
    return release(env, members=[("signalweave", native, tarfile.REGTYPE),
                                 ("LICENSE", b"License", tarfile.REGTYPE),
                                 ("build-info.json", b"{}", tarfile.REGTYPE),
                                 ("_internal/runtime.txt", b"support", tarfile.REGTYPE), *(extra or [])])


def test_directory_bundle_installs_once_and_upgrades_atomically(install_env):
    bundle(install_env)
    config = Path(install_env["HOME"]) / ".signalweave/config.toml"
    config.parent.mkdir()
    config.write_text("keep this config")
    first = run(install_env, "--version", VERSION)
    assert first.returncode == 0, first.stderr
    command = installed(install_env)
    old_wrapper = command.read_bytes()
    runtimes = command.parent / ".signalweave-runtime"
    old = list(runtimes.glob("*/signalweave"))
    assert len(old) == 1
    assert subprocess.run([str(command), "--help"], capture_output=True).returncode == 0
    assert (old[0].parent / "install-marker").read_text() == "signalweave-managed-runtime-v1\n"
    second = run(install_env, "--version", VERSION, "--replace")
    assert second.returncode == 0, second.stderr
    assert command.read_bytes() != old_wrapper and old[0].exists()
    assert len(list(runtimes.glob("*/signalweave"))) == 2
    assert config.read_text() == "keep this config"
    assert "Configuration and cards kept" in second.stdout
    assert "Next:" not in second.stdout


def test_directory_launcher_handles_shell_metacharacters_without_expansion(install_env):
    env = {**install_env, "SIGNALWEAVE_INSTALL_DIR": str(Path(install_env["HOME"]) / 'tools $value "quotes" `false`')}
    bundle(env)
    result = run(env, "--version", VERSION)
    assert result.returncode == 0, result.stderr
    command = Path(env["SIGNALWEAVE_INSTALL_DIR"]) / "signalweave"
    assert subprocess.run([str(command), "--help"], capture_output=True).returncode == 0


@pytest.mark.parametrize("name,kind", [("_internal/../escape", tarfile.REGTYPE), ("_internal/a/../../escape", tarfile.REGTYPE),
                                       ("_internal/link", tarfile.SYMTYPE), ("_internal/fifo", tarfile.FIFOTYPE)])
def test_runtime_archive_cannot_escape_or_introduce_links(install_env, name, kind):
    bundle(install_env, extra=[(name, b"bad", kind)])
    result = run(install_env, "--version", VERSION)
    assert result.returncode != 0
    assert not installed(install_env).exists()
    assert not (installed(install_env).parent / ".signalweave-runtime").exists()


def test_failed_directory_startup_preserves_existing_command_and_cleans_staging(install_env):
    release(install_env)
    assert run(install_env, "--version", VERSION).returncode == 0
    original = installed(install_env).read_bytes()
    bundle(install_env, executable=b"#!/bin/sh\nexit 19\n")
    result = run(install_env, "--version", VERSION, "--replace")
    assert result.returncode != 0 and installed(install_env).read_bytes() == original
    assert not list(installed(install_env).parent.glob(".signalweave-install.*"))
    assert not list((installed(install_env).parent / ".signalweave-runtime").iterdir())


@pytest.mark.parametrize("offset", [-1, 0])
def test_install_retention_bound_matches_uninstall_capacity(install_env, offset):
    from signalweave.managed_install import MAX_MANAGED_RUNTIMES

    bundle(install_env)
    assert run(install_env, "--version", VERSION).returncode == 0
    binary = installed(install_env)
    original = binary.read_bytes()
    root = binary.parent / ".signalweave-runtime"
    count = MAX_MANAGED_RUNTIMES + offset
    for number in range(count - 1):
        (root / f"v1.0.0.{number:08d}").mkdir()
    result = run(install_env, "--version", VERSION, "--replace")
    if offset == -1:
        assert result.returncode == 0, result.stderr
        assert len(list(root.iterdir())) == MAX_MANAGED_RUNTIMES
    else:
        assert result.returncode != 0 and "retention limit" in result.stderr
        assert f'"{binary}" uninstall' in result.stderr
        assert binary.read_bytes() == original
        assert len(list(root.iterdir())) == MAX_MANAGED_RUNTIMES
