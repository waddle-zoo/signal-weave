"""Process-level coverage for the human install and onboarding path."""
from __future__ import annotations

import fcntl
import json
import os
import platform
import pty
import select
import signal
import subprocess
import sys
import termios
import time
from pathlib import Path

import pytest
from test_install import INSTALLER, ROOT, VERSION, installed, release, run
from test_install import install_env as install_env

from scripts.binary_provenance import build_metadata, verify_binary

PROJECT_PYTHON = ROOT / ".venv/bin/python"
CLI_PYTHON = str(PROJECT_PYTHON if PROJECT_PYTHON.is_file() else Path(sys.executable))


def _piped_install(
    env: dict[str, str],
    *args: str,
    responses: tuple[tuple[str, bytes], ...] = (),
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    """Run the real installer as a shell reading its source through a pipe."""
    master, slave = pty.openpty()
    os.set_blocking(master, False)
    producer = subprocess.Popen(
        ["cat", str(INSTALLER)], cwd=INSTALLER.parents[1], stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert producer.stdout is not None

    def attach_controlling_terminal() -> None:
        fcntl.ioctl(1, termios.TIOCSCTTY, 0)
        os.tcsetpgrp(1, os.getpgrp())

    process = subprocess.Popen(
        ["sh", "-s", "--", *args], cwd=env["HOME"], env=env,
        stdin=producer.stdout, stdout=slave, stderr=slave,
        start_new_session=True, preexec_fn=attach_controlling_terminal,
    )
    producer.stdout.close()
    os.close(slave)
    output = bytearray()
    pending = list(responses)
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise TimeoutError("installer PTY journey did not finish")
            readable, _, _ = select.select([master], [], [], min(remaining, 0.1))
            if readable:
                try:
                    output.extend(os.read(master, 8192))
                except BlockingIOError:
                    continue
                except OSError:
                    break
            transcript = output.decode("utf-8", errors="replace")
            while pending and pending[0][0] in transcript:
                _, answer = pending.pop(0)
                os.write(master, answer)
        returncode = process.wait(timeout=max(0.1, deadline - time.monotonic()))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if producer.poll() is None:
            producer.wait(timeout=5)
        os.close(master)

    if pending:
        missing = pending[0][0]
        raise AssertionError(f"wizard prompt was not reached: {missing!r}\n{output.decode(errors='replace')}")
    text = output.decode("utf-8", errors="replace")
    return subprocess.CompletedProcess(["sh", "-s", "--", *args], returncode, text, text)


def _python_cli_launcher() -> bytes:
    metadata = build_metadata(ROOT)
    return f'''#!{CLI_PYTHON}
import json, sys
if sys.argv[1:] == ["--build-info"]:
    print(json.dumps({metadata!r}, sort_keys=True))
else:
    from signalweave.cli import main
    main()
'''.encode()


def test_piped_installer_runs_current_source_wizard_and_reports_agent_conflict(install_env):
    """A curl-style pipe reaches the real wizard through the controlling terminal."""
    install_dir = Path(install_env["HOME"]) / "custom install bin"
    private_home = Path(install_env["HOME"]) / "private SignalWeave home"
    codex_calls = Path(install_env["HOME"]) / "codex-calls.jsonl"
    codex = Path(install_env["PATH"].split(os.pathsep)[0]) / "codex"
    codex.write_text(f"#!{sys.executable}\n" + '''
import json, os, sys
with open(os.environ["CODEX_CALL_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:] == ["mcp", "list", "--json"]:
    print(json.dumps([{
        "name": "signalweave", "enabled": False,
        "transport": {"type": "stdio", "command": "old-signalweave", "args": []},
    }]))
else:
    sys.exit(9)
''')
    codex.chmod(0o755)
    release(install_env, version="v1.2.3", executable=_python_cli_launcher())
    journey_env = {
        **install_env,
        "PYTHONPATH": str(INSTALLER.parents[1] / "src"),
        "SIGNALWEAVE_HOME": str(private_home),
        "SIGNALWEAVE_INSTALL_DIR": str(install_dir),
        "CODEX_CALL_LOG": str(codex_calls),
    }
    result = _piped_install(
        journey_env,
        "--version", "v1.2.3", "--setup",
        responses=(
            ("Decision provider [1]:", b"2\n"),
            ("OpenAI API key (hidden):", b"test-key-for-local-journey\n"),
            ("Source [skip]:", b"5\n"),
            ("Agent [codex]:", b"1\n"),
            ("Add another source?", b"n\n"),
            ("Connect SignalWeave to Codex now?", b"y\n"),
        ),
    )

    assert result.returncode == 0, result.stdout
    executable = install_dir / "signalweave"
    assert executable.is_file()
    assert f'"{executable}" health --live' in result.stdout
    assert f'export PATH="{install_dir}:$PATH"' in result.stdout
    assert "different, disabled, or credential-bearing" in result.stdout
    assert "Registration was not verified" in result.stdout
    assert "Review existing entries before running this manual command" in result.stdout
    assert "The local setup is saved" in result.stdout
    assert "test-key-for-local-journey" not in result.stdout

    config = (private_home / "config.toml").read_text()
    assert 'SIGNALWEAVE_DECISION_PROVIDER = "openai-decisions"' in config
    assert 'OPENAI_API_KEY_FILE = "openai.key"' in config
    assert "test-key-for-local-journey" not in config
    assert (private_home / "openai.key").read_text() == "test-key-for-local-journey\n"
    assert (private_home / "openai.key").stat().st_mode & 0o777 == 0o600
    calls = [json.loads(line) for line in codex_calls.read_text().splitlines()]
    assert calls == [["mcp", "list", "--json"]]
    assert private_home.exists()


def test_piped_installer_recovers_after_setup_cancellation(install_env):
    metadata = build_metadata(ROOT)
    executable_bytes = f'''#!{sys.executable}
import json, os, sys
if sys.argv[1:] == ["--build-info"]:
    print(json.dumps({metadata!r}, sort_keys=True))
elif sys.argv[1:] == ["--version"]:
    print("SignalWeave 1.2.3")
elif sys.argv[1:] == ["--help"]:
    print("fake SignalWeave for cancellation contract")
elif sys.argv[1:] == ["setup"]:
    print("WIZARD READY", flush=True)
    answer = sys.stdin.readline().strip()
    if answer == "cancel":
        print("WIZARD CANCELED", flush=True)
        sys.exit(130)
    with open(os.environ["JOURNEY_LOG"], "a") as log:
        log.write(answer + "\\n")
    print("WIZARD SAVED", flush=True)
else:
    sys.exit(2)
'''.encode()
    release(install_env, version="v1.2.3", executable=executable_bytes)
    log = Path(install_env["HOME"]) / "journey.log"
    journey_env = {**install_env, "JOURNEY_LOG": str(log)}

    canceled = _piped_install(
        journey_env, "--version", "v1.2.3", "--setup",
        responses=(("WIZARD READY", b"cancel\n"),),
    )
    assert canceled.returncode == 130, canceled.stdout
    assert "WIZARD CANCELED" in canceled.stdout
    assert "Setup was canceled" in canceled.stdout
    assert f'"{installed(install_env)}" setup' in canceled.stdout
    assert installed(install_env).is_file()

    requests_before = Path(install_env["REQUEST_LOG"]).read_text()
    resumed = _piped_install(
        journey_env, "--setup", responses=(("WIZARD READY", b"continue\n"),),
    )
    assert resumed.returncode == 0, resumed.stdout
    assert "keeping it and resuming setup" in resumed.stdout
    assert "WIZARD SAVED" in resumed.stdout
    assert "Setup finished" in resumed.stdout
    assert log.read_text().splitlines() == ["continue"]
    assert Path(install_env["REQUEST_LOG"]).read_text() == requests_before


def test_requested_upgrade_replaces_old_version_before_setup(install_env):
    old_version, new_version = "v1.2.2", "v1.2.3"
    old_setup_log = Path(install_env["HOME"]) / "old-setup.log"
    new_setup_log = Path(install_env["HOME"]) / "new-setup.log"
    private_home = Path(install_env["HOME"]) / "existing local setup"
    private_home.mkdir()
    config = private_home / "config.toml"
    config.write_text("preserve existing setup\n")

    def setup_binary(version: str, label: str, log_env: str) -> bytes:
        return f'''#!/bin/sh
case "$1" in
    --help) exit 0 ;;
    --version) printf 'SignalWeave {version.removeprefix("v")}\\n' ;;
    setup)
        printf '{label} WIZARD READY\\n'
        IFS= read -r response
        printf '%s\\n' "$response" >> "${log_env}"
        printf '{label} WIZARD SAVED\\n'
        ;;
    *) exit 2 ;;
esac
'''.encode()

    journey_env = {
        **install_env,
        "SIGNALWEAVE_HOME": str(private_home),
        "OLD_SETUP_LOG": str(old_setup_log),
        "NEW_SETUP_LOG": str(new_setup_log),
    }
    release(journey_env, version=old_version, executable=setup_binary(old_version, "OLD", "OLD_SETUP_LOG"))
    installed_old = run(journey_env, "--version", old_version)
    assert installed_old.returncode == 0, installed_old.stderr
    original = installed(journey_env).read_bytes()
    requests_before = Path(journey_env["REQUEST_LOG"]).read_text()

    mismatch = run(journey_env, "--version", new_version, "--setup")
    assert mismatch.returncode != 0
    assert "Installed SignalWeave v1.2.2 differs from requested v1.2.3" in mismatch.stderr
    assert "--replace --setup" in mismatch.stderr
    assert installed(journey_env).read_bytes() == original
    assert Path(journey_env["REQUEST_LOG"]).read_text() == requests_before
    assert not old_setup_log.exists() and not new_setup_log.exists()

    release(journey_env, version=new_version, executable=setup_binary(new_version, "NEW", "NEW_SETUP_LOG"))
    upgraded = _piped_install(
        journey_env, "--version", new_version, "--replace", "--setup",
        responses=(("NEW WIZARD READY", b"continue\n"),),
    )
    assert upgraded.returncode == 0, upgraded.stdout
    assert "Installed SignalWeave v1.2.3" in upgraded.stdout
    assert "NEW WIZARD SAVED" in upgraded.stdout
    assert "OLD WIZARD" not in upgraded.stdout
    assert new_setup_log.read_text().splitlines() == ["continue"]
    assert not old_setup_log.exists()
    assert subprocess.run([str(installed(journey_env)), "--version"], capture_output=True, text=True).stdout.strip() == "SignalWeave 1.2.3"
    assert config.read_text() == "preserve existing setup\n"
    assert not list(installed(journey_env).parent.glob(".signalweave-install.*"))


@pytest.mark.skipif(
    not (os.getenv("SIGNALWEAVE_TEST_BINARY") and os.getenv("SIGNALWEAVE_TEST_BINARY_SHA256")
         and os.getenv("SIGNALWEAVE_TEST_BINARY_VERSION")),
    reason="Wait for coordinator-certified latest binary path, SHA-256, and rebuild version",
)
def test_certified_latest_binary_completes_pty_onboarding(install_env):
    """Optional real-binary journey; it cannot start without the supplied fingerprint."""
    binary = Path(os.environ["SIGNALWEAVE_TEST_BINARY"]).resolve()
    identity = verify_binary(binary)
    print("Certified binary identity: " + json.dumps(identity, sort_keys=True), flush=True)
    assert identity["binary_sha256"] == os.environ["SIGNALWEAVE_TEST_BINARY_SHA256"]
    assert identity["version"] == os.environ["SIGNALWEAVE_TEST_BINARY_VERSION"] == VERSION.removeprefix("v")

    system, architecture = platform.system(), platform.machine()
    target = {
        ("Darwin", "arm64"): "darwin-arm64",
        ("Darwin", "x86_64"): "darwin-x86_64",
        ("Linux", "x86_64"): "linux-x86_64",
    }[(system, architecture)]
    release(install_env, version=VERSION, target=target, executable=binary.read_bytes())
    install_env.update(TEST_OS=system, TEST_ARCH=architecture)
    private_home = Path(install_env["HOME"]) / "certified private home"
    onboarding_env = {**install_env, "SIGNALWEAVE_HOME": str(private_home)}
    result = _piped_install(
        onboarding_env, "--version", VERSION, "--setup",
        responses=(
            ("Decision provider [1]:", b"2\n"),
            ("OpenAI API key (hidden):", b"test-key-for-certified-binary\n"),
            ("Source [skip]:", b"5\n"),
            ("Agent [codex]:", b"1\n"),
            ("Add another source?", b"n\n"),
            ("Connect SignalWeave to Codex now?", b"n\n"),
        ),
    )
    assert result.returncode == 0, result.stdout
    assert "Setup finished" in result.stdout
    assert (private_home / "config.toml").is_file()
    assert (private_home / "openai.key").read_text() == "test-key-for-certified-binary\n"
