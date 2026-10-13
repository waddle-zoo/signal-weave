import json
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import signalweave.cli as cli
from signalweave import local_setup as setup


def test_version_reports_installed_distribution_without_initializing(monkeypatch, capsys):
    from importlib.metadata import version

    monkeypatch.setattr(sys, "argv", ["signalweave", "--version"])
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 0
    assert capsys.readouterr().out.strip() == f"SignalWeave {version('signal-weave')}"


@pytest.fixture(autouse=True)
def isolated_local_setup(monkeypatch, tmp_path):
    for name in (*setup._ENV_NAMES, "SIGNALWEAVE_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def local_home(monkeypatch, tmp_path):
    monkeypatch.setattr(setup.getpass, "getpass", lambda _: "test-cli-key")
    return setup.initialize(tmp_path / "local home")


def test_token_preset_server_fails_closed_without_static_principal(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-cli-key")
    monkeypatch.setenv("PRESET_URL", "https://workspace.app.preset.io")
    monkeypatch.setenv("SIGNALWEAVE_AUTH_MODE", "token")
    monkeypatch.delenv("SIGNALWEAVE_TENANT_ID", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_PRINCIPAL_ID", raising=False)
    monkeypatch.setattr(cli, "build_runtime", lambda **_kwargs: SimpleNamespace(principal=None))
    monkeypatch.setattr(sys, "argv", ["signalweave", "serve", "--transport", "streamable-http"])

    with pytest.raises(RuntimeError, match="streamable HTTP requires"):
        cli.main()


def test_token_http_fails_closed_without_any_static_principal(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-cli-key")
    monkeypatch.delenv("PRESET_URL", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_AUTH_MODE", "token")
    monkeypatch.setattr(cli, "build_runtime", lambda **_kwargs: SimpleNamespace(principal=None))
    monkeypatch.setattr(sys, "argv", ["signalweave", "serve", "--transport", "streamable-http"])

    with pytest.raises(RuntimeError, match="streamable HTTP requires"):
        cli.main()


def test_http_api_token_uses_deployment_secret_loader(monkeypatch):
    monkeypatch.setattr(cli, "load_deployment_secret", lambda name: "mounted-token")

    assert cli._http_api_token() == "mounted-token"


def test_init_cli_and_repeated_init_do_not_print_key(monkeypatch, tmp_path, capsys):
    key_file = tmp_path / "input-key"
    key_file.write_text("test-cli-secret")
    key_file.chmod(0o600)
    home = tmp_path / "new home"
    monkeypatch.setattr(sys, "argv", ["signalweave", "init", "--home", str(home), "--key-file", str(key_file)])
    cli.main()
    cli.main()
    captured = capsys.readouterr()
    assert "test-cli-secret" not in captured.out + captured.err
    assert str(home / "config.toml") in captured.out


def test_guided_agent_setup_saves_private_jev_key(monkeypatch, tmp_path, capsys):
    home = tmp_path / "agent-only"
    key_file = tmp_path / "typesafe-key"
    key_file.write_text("test-agent-jev-key")
    key_file.chmod(0o600)
    monkeypatch.setattr(sys, "argv", [
        "signalweave", "setup", "--home", str(home), "--non-interactive",
        "--key-file", str(key_file), "--source", "skip", "--no-register-agent",
    ])

    cli.main()

    environment = setup.read_config(home)[1]
    assert environment["SIGNALWEAVE_MCP_PROFILE"] == "agent"
    assert environment["SIGNALWEAVE_DECISION_PROVIDER"] == "jev"
    assert (home / "typesafe.key").read_text() == "test-agent-jev-key\n"
    assert (home / "typesafe.key").stat().st_mode & 0o777 == 0o600
    assert "Local configuration saved" in capsys.readouterr().out


def test_bare_command_starts_keyless_chatgpt_plan_setup(monkeypatch, tmp_path, capsys):
    from signalweave import chatgpt_auth

    monkeypatch.setattr(sys, "argv", ["signalweave"])
    answers = iter(["3", "5", "1", "n", "n"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(
        chatgpt_auth, "auth_status",
        lambda _home: {"status": "connected", "account": None, "plan_usage": "enabled"},
    )

    cli.main()

    home = Path.home() / ".signalweave"
    environment = setup.read_config(home)[1]
    assert environment["SIGNALWEAVE_DECISION_PROVIDER"] == "chatgpt-plan"
    assert "TYPESAFE_API_KEY_FILE" not in environment
    assert "OPENAI_API_KEY_FILE" not in environment
    output = capsys.readouterr().out
    assert "Choose how SignalWeave should make recurring card decisions" in output
    assert "Local configuration saved" in output


def test_bare_command_uses_configured_private_home_without_restarting_setup(local_home, monkeypatch, capsys):
    monkeypatch.setenv("SIGNALWEAVE_HOME", str(local_home))
    monkeypatch.setattr(sys, "argv", ["signalweave"])

    def unexpected_prompt(_prompt):
        raise AssertionError("A configured home must show status rather than starting setup")

    monkeypatch.setattr("builtins.input", unexpected_prompt)
    cli.main()
    assert "SignalWeave:" in capsys.readouterr().out
    assert sys.argv == ["signalweave", "status"]


def test_noninteractive_chatgpt_setup_does_not_open_browser(monkeypatch, tmp_path, capsys):
    home = tmp_path / "keyless-home"
    monkeypatch.setattr(sys, "argv", [
        "signalweave", "setup", "--home", str(home), "--non-interactive",
        "--decision-provider", "chatgpt-plan", "--source", "skip", "--no-register-agent",
    ])

    cli.main()

    environment = setup.read_config(home)[1]
    assert environment["SIGNALWEAVE_DECISION_PROVIDER"] == "chatgpt-plan"
    output = capsys.readouterr().out
    assert "signalweave auth login" in output
    assert "Opening OpenAI sign-in" not in output


@pytest.mark.parametrize("home_mode", ["explicit", "environment", "default"])
def test_stdio_loads_local_config_before_runtime_without_stdout(
    local_home, monkeypatch, tmp_path, capsys, home_mode,
):
    import signalweave.mcp_server as mcp_server

    monkeypatch.chdir(tmp_path)
    expected_home = local_home
    if home_mode == "default":
        expected_home = setup.resolve_home()
        local_home.rename(expected_home)
    calls = []
    runtime = object()

    def build(**kwargs):
        assert kwargs == {"mode": "jev"}
        assert os.environ["TYPESAFE_API_KEY_FILE"] == str(expected_home / "typesafe.key")
        assert os.environ["SIGNALWEAVE_STORE_PATH"] == str(expected_home / "state" / "signalweave.db")
        assert os.environ["SIGNALWEAVE_ALLOW_EMPTY_SOURCES"] == "1"
        calls.append("build")
        return runtime

    def create(value, **kwargs):
        assert value is runtime
        assert kwargs == {"profile": "agent"}
        return SimpleNamespace(run=lambda **kwargs: calls.append(kwargs))

    monkeypatch.setattr(cli, "build_runtime", build)
    monkeypatch.setattr(mcp_server, "create_mcp", create)
    monkeypatch.setattr(cli, "_run_stdio", lambda server: server.run(transport="stdio"))
    argv = ["signalweave", "serve"]
    monkeypatch.setenv("SIGNALWEAVE_MCP_PROFILE", "agent")
    if home_mode == "environment":
        monkeypatch.setenv("SIGNALWEAVE_HOME", str(local_home))
    elif home_mode == "explicit":
        argv.extend(["--home", str(local_home)])
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()
    assert calls == ["build", {"transport": "stdio"}]
    assert capsys.readouterr().out == ""
    assert "SIGNALWEAVE_STORE_PATH" not in os.environ


def test_serve_remains_environment_driven_without_a_local_profile(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-deployment-key")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", "existing/deployment.db")

    def serve(args):
        assert os.environ["TYPESAFE_API_KEY"] == "test-deployment-key"
        assert "TYPESAFE_API_KEY_FILE" not in os.environ
        assert "SIGNALWEAVE_ALLOW_EMPTY_SOURCES" not in os.environ
        assert os.environ["SIGNALWEAVE_STORE_PATH"] == "existing/deployment.db"

    monkeypatch.setattr(cli, "_serve", serve)
    monkeypatch.setattr(sys, "argv", ["signalweave", "serve"])
    cli.main()


def test_serve_without_jev_key_fails_before_startup(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(cli, "_serve", lambda _args: calls.append(_args.profile))
    monkeypatch.setattr(sys, "argv", ["signalweave", "serve"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert calls == []
    assert "TypeSafe key" in capsys.readouterr().err


def test_local_agent_serve_missing_jev_key_fails_cleanly(local_home, monkeypatch, capsys):
    (local_home / "typesafe.key").unlink()
    monkeypatch.setenv("SIGNALWEAVE_MCP_PROFILE", "agent")
    calls = []
    monkeypatch.setattr(cli, "_serve", lambda _args: calls.append("served"))
    monkeypatch.setattr(sys, "argv", ["signalweave", "serve", "--home", str(local_home)])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert calls == []
    assert "TypeSafe key" in capsys.readouterr().err


def test_explicit_missing_home_does_not_fall_back_to_environment(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-env-key")
    monkeypatch.setattr(cli, "build_runtime", lambda: pytest.fail("must not build"))
    monkeypatch.setattr(sys, "argv", ["signalweave", "serve", "--home", str(tmp_path / "missing")])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("override", [[], ["--host", "localhost", "--port", "9001"]])
def test_local_http_host_and_port_defaults_loaded_after_config(local_home, monkeypatch, override):
    config = local_home / "config.toml"
    config.write_text(config.read_text() + '\nMCP_HOST = "127.0.0.2"\nMCP_PORT = "9000"\n')
    values = []
    monkeypatch.setattr(cli, "_serve", lambda args: values.append((args.host, args.port)))
    monkeypatch.setattr(sys, "argv", ["signalweave", "serve", "--home", str(local_home), *override])
    cli.main()
    assert values == ([("localhost", 9001)] if override else [("127.0.0.2", 9000)])


def test_doctor_exit_status_and_offline_claim(local_home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "build_runtime", lambda: pytest.fail("offline command must not build"))
    monkeypatch.setattr(sys, "argv", ["signalweave", "doctor", "--home", str(local_home)])
    cli.main()
    assert "onboarding only" in capsys.readouterr().out
    (local_home / "typesafe.key").unlink()
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    report = capsys.readouterr().out
    assert "Offline configuration check only" in report
    assert "Offline checks passed" not in report


def test_agent_config_cli_prints_parseable_json_without_writes(local_home, monkeypatch, capsys):
    before = sorted(local_home.rglob("*"))
    monkeypatch.setattr(sys, "argv", ["signalweave", "agent-config", "--agent", "claude", "--home", str(local_home)])
    cli.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["mcpServers"]["signalweave"]["args"][-1] == str(local_home)
    assert before == sorted(local_home.rglob("*"))


def test_init_not_broken_by_http_port_environment(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MCP_PORT", "not-a-port")
    monkeypatch.setattr(setup.getpass, "getpass", lambda _: "test-key")
    monkeypatch.setattr(sys, "argv", ["signalweave", "init", "--home", str(tmp_path / "new")])
    cli.main()
    assert "Local configuration" in capsys.readouterr().out


@pytest.mark.parametrize("with_output", [True, False])
def test_run_cli_loads_local_environment_and_prints_json(local_home, monkeypatch, tmp_path, capsys, with_output):
    calls = []

    async def run_card(card_id, run_key, output_dir=None):
        assert os.environ["SIGNALWEAVE_STORE_PATH"] == str(local_home / "state" / "signalweave.db")
        assert os.environ["TYPESAFE_API_KEY_FILE"] == str(local_home / "typesafe.key")
        calls.append((card_id, run_key, output_dir))
        return {"card_id": card_id, "outcome": "investigate", "replayed": True}

    monkeypatch.setitem(sys.modules, "signalweave.local_run", SimpleNamespace(run_card=run_card))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "signalweave", "run", "card-123", "--run-key", "daily:123", "--home", str(local_home),
        *(["--output", "reports"] if with_output else []),
    ])
    cli.main()
    assert calls == [("card-123", "daily:123", tmp_path / "reports" if with_output else None)]
    assert json.loads(capsys.readouterr().out) == {
        "card_id": "card-123", "outcome": "investigate", "replayed": True,
    }
    assert "SIGNALWEAVE_STORE_PATH" not in os.environ


def test_run_requires_explicit_run_key(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["signalweave", "run", "card-123"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


def test_run_is_available_in_the_default_agent_profile(monkeypatch, tmp_path, capsys):
    key_file = tmp_path / "typesafe-key"
    key_file.write_text("test-run-jev-key")
    key_file.chmod(0o600)
    home = setup.initialize(tmp_path / "signalweave-home", key_file=key_file)
    calls = []

    async def run_card(card_id, run_key, output_dir=None):
        calls.append((card_id, run_key, output_dir))
        return {"card_id": card_id, "outcome": "investigate"}

    monkeypatch.setitem(sys.modules, "signalweave.local_run", SimpleNamespace(run_card=run_card))
    monkeypatch.setenv("SIGNALWEAVE_MCP_PROFILE", "agent")
    monkeypatch.setattr(sys, "argv", [
        "signalweave", "run", "card-123", "--run-key", "daily:123", "--home", str(home),
    ])
    cli.main()
    assert calls == [("card-123", "daily:123", None)]
    assert '"outcome": "investigate"' in capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize("with_source", [True, False])
@pytest.mark.parametrize("check_shutdown_flush", [True, False])
async def test_installed_stdio_protocol_from_unrelated_directory(
    local_home, tmp_path, monkeypatch, with_source, check_shutdown_flush,
):
    # MCP startup/tool discovery is offline: the key is wired but no judgment
    # endpoint is contacted until the agent runs an approved card.
    config = local_home / "config.toml"
    if with_source:
        config.write_text(config.read_text() + '\nSUPERSET_URL = "http://127.0.0.1:9"\n')
    elsewhere = tmp_path / "agent-project"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    entrypoint = Path(sys.prefix) / "bin" / "signalweave"
    parameters = StdioServerParameters(
        command=str(entrypoint) if entrypoint.exists() else sys.executable,
        args=([] if entrypoint.exists() else ["-m", "signalweave.cli"]) + [
            "serve", "--home", str(local_home),
        ],
    env={**os.environ, "SIGNALWEAVE_MCP_PROFILE": "agent"},
    )
    if check_shutdown_flush:
        parameters.command = sys.executable
        parameters.args = ["-I", "-c", (
            "import gc, sys; from signalweave.cli import main; main(); gc.collect(); "
            "assert not sys.stdin.closed and not sys.stdout.closed; "
            "sys.stdout.flush(); sys.__stdout__.flush(); "
            "print('stdio-ownership-ok', file=sys.stderr)"
        ), "serve", "--home", str(local_home)]
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr:
        with anyio.fail_after(20):
            async with stdio_client(parameters, errlog=stderr) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    assert initialized.serverInfo.name
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    assert "evaluate_insight_card" in names
                    assert "get_decision_receipt" in names
                    assert "prepare_insight_run" not in names
        stderr.seek(0)
        diagnostic = stderr.read()
    assert "Traceback" not in diagnostic
    if check_shutdown_flush:
        assert "stdio-ownership-ok" in diagnostic
    assert (local_home / "state" / "signalweave.db").exists()
    assert not (elsewhere / "data").exists()


@pytest.mark.parametrize("failure", [None, RuntimeError, KeyboardInterrupt])
def test_stdio_restores_original_streams_and_closes_duplicates(tmp_path, monkeypatch, failure):
    duplicate_fds = []
    output = tmp_path / "stdout"
    with (tmp_path / "stdin").open("w+") as stdin, output.open("w", encoding="ascii") as stdout:
        monkeypatch.setattr(sys, "stdin", stdin)
        monkeypatch.setattr(sys, "stdout", stdout)

        def run(*, transport):
            assert transport == "stdio"
            assert sys.stdin is not stdin and sys.stdout is not stdout
            duplicate_fds.extend([sys.stdin.fileno(), sys.stdout.fileno()])
            assert duplicate_fds != [stdin.fileno(), stdout.fileno()]
            sys.stdout.write("雪\n")
            sys.stdout.flush()
            # Reproduce the SDK's ownership behavior before normal/error teardown.
            sys.stdin.buffer.close()
            sys.stdout.buffer.close()
            if failure:
                raise failure("test shutdown")

        if failure:
            with pytest.raises(failure, match="test shutdown"):
                cli._run_stdio(SimpleNamespace(run=run))
        else:
            cli._run_stdio(SimpleNamespace(run=run))
        assert sys.stdin is stdin and sys.stdout is stdout
        assert not stdin.closed and not stdout.closed
        stdout.flush()
        for descriptor in duplicate_fds:
            with pytest.raises(OSError):
                os.fstat(descriptor)
    assert output.read_text(encoding="utf-8") == "雪\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown_traceback", [True, False])
async def test_binary_checker_checks_stderr_after_shutdown_without_echo(
    tmp_path, monkeypatch, capsys, shutdown_traceback,
):
    from scripts import check_binary

    monkeypatch.setattr(check_binary, "verify_binary", lambda _: {"fixture": True})

    binary = tmp_path / "binary"
    key = tmp_path / "key"
    key.write_text("test-only-key")
    def checked_command(argv, **kwargs):
        if argv[1] == "setup":
            from signalweave.local_setup import setup_local

            def option(name):
                return argv[argv.index(name) + 1]

            provider = option("--decision-provider") if "--decision-provider" in argv else "jev"
            if provider == "openai-decisions":
                setup_local(
                    option("--home"), decision_provider=provider,
                    openai_key_file=option("--openai-key-file"), source=option("--source"),
                    non_interactive=True,
                )
            elif provider == "chatgpt-plan":
                setup_local(
                    option("--home"), decision_provider=provider,
                    source=option("--source"), non_interactive=True,
                )
            else:
                setup_local(
                    option("--home"), key_file=option("--key-file"),
                    source=option("--source"), url=option("--url"),
                    username=option("--username"), secret_file=option("--secret-file"),
                    tenant=option("--tenant"), principal=option("--principal"),
                    agent=option("--agent"), non_interactive=True,
                )
        if argv[1] == "auth":
            return SimpleNamespace(returncode=0, stderr="", stdout="ChatGPT plan: not_connected")
        if argv[1] == "status":
            return SimpleNamespace(returncode=0, stderr="", stdout="OPENAI_API_KEY: configured")
        return SimpleNamespace(returncode=0, stderr="", stdout=(
            f"SignalWeave {cli.__version__}" if argv[1] == "--version" else
            json.dumps({"binary": str(binary)}) if argv[1] == "agent-config"
            else "Offline configuration check"
        ))

    monkeypatch.setattr(check_binary.subprocess, "run", checked_command)

    @asynccontextmanager
    async def transport(parameters, *, errlog):
        yield None, None
        # Must be tested after context exit, not merely after list_tools.
        if shutdown_traceback:
            errlog.write(
                'Traceback (most recent call last):\n'
                '  File "/private/secret-path-sentinel", line 1\n'
                'ValueError: secret-message-sentinel\n'
            )
        else:
            errlog.write('ordinary shutdown log\n')
        errlog.flush()

    class Session:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            pass

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name=name) for name in (
                "onboard_insight_card", "evaluate_insight_card", "get_signalweave_guide",
            )])

        async def call_tool(self, name, arguments):
            assert name == "get_signalweave_guide"
            return SimpleNamespace(isError=False, structuredContent={"task": arguments["task"]})

    monkeypatch.setattr(check_binary, "stdio_client", transport)
    monkeypatch.setattr(check_binary, "ClientSession", Session)
    if shutdown_traceback:
        with pytest.raises(RuntimeError, match="diagnostic contents withheld") as error:
            await check_binary.check(binary, key, live=False)
        assert "ValueError" in str(error.value)
        assert "secret-path-sentinel" not in str(error.value)
        assert "secret-message-sentinel" not in str(error.value)
    else:
        await check_binary.check(binary, key, live=False)
    captured = capsys.readouterr()
    assert "secret-path-sentinel" not in captured.out + captured.err
    assert "secret-message-sentinel" not in captured.out + captured.err


def test_binary_smoke_drops_host_python_loader_and_provider_environment(tmp_path, monkeypatch):
    from scripts.check_binary import _smoke_environment

    inherited = {
        "Python_ROOT_DIR": "/runner/python/x64",
        "pythonLocation": "/runner/python/x64",
        "DYLD_LIBRARY_PATH": "/runner/python/lib",
        "LD_LIBRARY_PATH": "/runner/python/lib",
        "OPENAI_API_KEY": "must-not-reach-smoke",
        "SIGNALWEAVE_HOME": "/host/signalweave",
        "VIRTUAL_ENV": "/host/venv",
    }
    for name, value in inherited.items():
        monkeypatch.setenv(name, value)

    user_home = tmp_path / "isolated-user"
    environment = _smoke_environment(user_home)

    assert all(name not in environment for name in inherited)
    assert environment["HOME"] == str(user_home)
    assert environment["PATH"] == os.environ["PATH"]


@pytest.mark.asyncio
@pytest.mark.parametrize("returncode,stderr", [
    (0, 'Traceback (most recent call last):\n'
        '  File "/private/secret-path-sentinel", line 1\n'
        'ValueError: secret-message-sentinel\n'),
    (1, "secret-sentinel"),
])
async def test_binary_checker_command_failures_do_not_echo_stderr(tmp_path, monkeypatch, capsys, returncode, stderr):
    from scripts import check_binary

    monkeypatch.setattr(check_binary, "verify_binary", lambda _: {"fixture": True})

    key = tmp_path / "key"
    key.write_text("test-only-key")
    monkeypatch.setattr(check_binary.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=returncode, stderr=stderr, stdout="",
    ))
    with pytest.raises(RuntimeError, match="diagnostic contents withheld") as error:
        await check_binary.check(tmp_path / "binary", key, live=False)
    captured = capsys.readouterr()
    diagnostic = str(error.value) + captured.out + captured.err
    assert "secret-sentinel" not in diagnostic
    assert "secret-path-sentinel" not in diagnostic
    assert "secret-message-sentinel" not in diagnostic
    if returncode == 0:
        assert "ValueError" in str(error.value)


def test_binary_checker_withholds_nonstandard_exception_class():
    from scripts.check_binary import _check_stderr

    with pytest.raises(RuntimeError, match="diagnostic contents withheld") as error:
        _check_stderr(
            'Traceback (most recent call last):\n'
            '  File "/private/secret-path-sentinel", line 1\n'
            'PrivateError: secret-message-sentinel\n'
        )

    assert "PrivateError" not in str(error.value)
    assert "secret-path-sentinel" not in str(error.value)
    assert "secret-message-sentinel" not in str(error.value)
