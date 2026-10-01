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
    monkeypatch.setenv("PRESET_URL", "https://workspace.app.preset.io")
    monkeypatch.setenv("SIGNALWEAVE_AUTH_MODE", "token")
    monkeypatch.delenv("SIGNALWEAVE_TENANT_ID", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_PRINCIPAL_ID", raising=False)
    monkeypatch.setattr(cli, "build_runtime", lambda: SimpleNamespace(principal=None))
    monkeypatch.setattr(sys, "argv", ["signalweave", "serve", "--transport", "streamable-http"])

    with pytest.raises(RuntimeError, match="streamable HTTP requires"):
        cli.main()


def test_token_http_fails_closed_without_any_static_principal(monkeypatch):
    monkeypatch.delenv("PRESET_URL", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_AUTH_MODE", "token")
    monkeypatch.setattr(cli, "build_runtime", lambda: SimpleNamespace(principal=None))
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


@pytest.mark.parametrize("through_env", [False, True])
def test_stdio_loads_local_config_before_runtime_without_stdout(local_home, monkeypatch, tmp_path, capsys, through_env):
    import signalweave.mcp_server as mcp_server

    monkeypatch.chdir(tmp_path)
    calls = []
    runtime = object()

    def build():
        assert os.environ["TYPESAFE_API_KEY_FILE"] == str(local_home / "typesafe.key")
        assert os.environ["SIGNALWEAVE_STORE_PATH"] == str(local_home / "state" / "signalweave.db")
        assert os.environ["SIGNALWEAVE_ALLOW_EMPTY_SOURCES"] == "1"
        calls.append("build")
        return runtime

    def create(value):
        assert value is runtime
        return SimpleNamespace(run=lambda **kwargs: calls.append(kwargs))

    monkeypatch.setattr(cli, "build_runtime", build)
    monkeypatch.setattr(mcp_server, "create_mcp", create)
    monkeypatch.setattr(cli, "_run_stdio", lambda server: server.run(transport="stdio"))
    argv = ["signalweave", "serve"]
    if through_env:
        monkeypatch.setenv("SIGNALWEAVE_HOME", str(local_home))
    else:
        argv.extend(["--home", str(local_home)])
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()
    assert calls == ["build", {"transport": "stdio"}]
    assert capsys.readouterr().out == ""
    assert "SIGNALWEAVE_STORE_PATH" not in os.environ


def test_legacy_serve_does_not_implicitly_load_default_home(local_home, monkeypatch):
    default = setup.resolve_home()
    local_home.rename(default)
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


def test_local_serve_error_is_only_on_stderr(local_home, monkeypatch, capsys):
    (local_home / "typesafe.key").unlink()
    monkeypatch.setattr(cli, "build_runtime", lambda: pytest.fail("runtime built before setup validation"))
    monkeypatch.setattr(sys, "argv", ["signalweave", "serve", "--home", str(local_home)])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "missing or unreadable" in captured.err


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


@pytest.mark.asyncio
@pytest.mark.parametrize("with_source", [True, False])
@pytest.mark.parametrize("check_shutdown_flush", [True, False])
async def test_installed_stdio_protocol_from_unrelated_directory(
    local_home, tmp_path, monkeypatch, with_source, check_shutdown_flush,
):
    # Startup/tool discovery is offline: no tool that fetches data is invoked.
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
        env=dict(os.environ),
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
                    assert "evaluate_insight_card" in {tool.name for tool in tools.tools}
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

    binary = tmp_path / "binary"
    key = tmp_path / "key"
    key.write_text("test-only-key")
    def checked_command(argv, **kwargs):
        if argv[1] == "setup":
            from signalweave.local_setup import setup_local

            def option(name):
                return argv[argv.index(name) + 1]

            setup_local(
                option("--home"), key_file=option("--key-file"),
                source=option("--source"), url=option("--url"),
                username=option("--username"), secret_file=option("--secret-file"),
                tenant=option("--tenant"), principal=option("--principal"),
                agent=option("--agent"), non_interactive=True,
            )
        return SimpleNamespace(returncode=0, stderr="", stdout=(
            json.dumps({"binary": str(binary)}) if argv[1] == "agent-config"
            else "Offline configuration check"
        ))

    monkeypatch.setattr(check_binary.subprocess, "run", checked_command)

    @asynccontextmanager
    async def transport(parameters, *, errlog):
        yield None, None
        # Must be tested after context exit, not merely after list_tools.
        if shutdown_traceback:
            errlog.write('Traceback (most recent call last):\nsecret-sentinel\n')
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
                "onboard_insight_card", "evaluate_insight_card",
            )])

    monkeypatch.setattr(check_binary, "stdio_client", transport)
    monkeypatch.setattr(check_binary, "ClientSession", Session)
    if shutdown_traceback:
        with pytest.raises(RuntimeError, match="diagnostic contents withheld") as error:
            await check_binary.check(binary, key, live=False)
        assert "secret-sentinel" not in str(error.value)
    else:
        await check_binary.check(binary, key, live=False)
    captured = capsys.readouterr()
    assert "secret-sentinel" not in captured.out + captured.err


@pytest.mark.asyncio
@pytest.mark.parametrize("returncode,stderr", [
    (0, "Traceback (most recent call last): secret-sentinel"), (1, "secret-sentinel"),
])
async def test_binary_checker_command_failures_do_not_echo_stderr(tmp_path, monkeypatch, capsys, returncode, stderr):
    from scripts import check_binary

    key = tmp_path / "key"
    key.write_text("test-only-key")
    monkeypatch.setattr(check_binary.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=returncode, stderr=stderr, stdout="",
    ))
    with pytest.raises(RuntimeError, match="diagnostic contents withheld") as error:
        await check_binary.check(tmp_path / "binary", key, live=False)
    captured = capsys.readouterr()
    assert "secret-sentinel" not in str(error.value) + captured.out + captured.err
