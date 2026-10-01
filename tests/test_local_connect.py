"""Offline setup contracts; credentials here are inert unit-test values."""

import json
import os
import shlex
import stat
import subprocess
import sys
import warnings

import httpx
import mcp  # noqa: F401 — load SDK process type annotations before blocking process launches
import pytest

from signalweave import cli
from signalweave import local_setup as setup
from signalweave.runtime import build_runtime


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for name in (*setup._ENV_NAMES, "SIGNALWEAVE_HOME"):
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("the setup wizard must not access the network or launch a source")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


def private(path, value):
    path.write_text(value)
    path.chmod(0o600)
    return path


@pytest.fixture
def options(tmp_path):
    return {
        "home": tmp_path / "local home", "non_interactive": True,
        "key_file": private(tmp_path / "jev", "test-jev-credential"),
        "agent": "codex",
    }


def superset_options(options, tmp_path):
    return {
        **options, "source": "superset", "url": "https://bi.internal", "username": "analyst",
        "secret_file": private(tmp_path / "password", "test-password-credential"),
    }


def manifest_file(tmp_path, tenant="local"):
    return private(tmp_path / "mcp.json", json.dumps({"version": 1, "connections": [{
        "name": "company", "tenant_id": tenant, "read_only": True,
        "transport": {"type": "stdio", "command": ["/never/run/this"]},
        "resources": [{"source_key": "metric", "tool": "read", "descriptor": {
            "adapter": "company", "resource": "metric:1", "kind": "metric", "title": "Metric",
            "contract": {"tenant_id": tenant},
        }}],
    }]}))


def test_bare_interactive_setup_and_single_registration_command(tmp_path, monkeypatch, capsys):
    hidden = iter(["test-jev-credential", "test-password-credential"])
    visible = iter(["", "", "superset", "https://bi.internal", "analyst", "claude"])
    monkeypatch.setenv("SIGNALWEAVE_HOME", str(tmp_path / "wizard"))
    monkeypatch.setattr(setup.getpass, "getpass", lambda _: next(hidden))
    monkeypatch.setattr("builtins.input", lambda _: next(visible))
    monkeypatch.setattr(sys, "argv", ["signalweave", "setup"])
    cli.main()
    output = capsys.readouterr().out
    assert "claude mcp add --transport stdio --scope user signalweave --" in output
    assert "test-password" not in output and "test-jev" not in output
    assert "unverified" in output and "not provider authentication" in output
    _, env = setup.read_config(tmp_path / "wizard")
    assert env["SIGNALWEAVE_TENANT_ID"] == env["SUPERSET_TENANT_ID"] == "local"
    assert env["SIGNALWEAVE_PRINCIPAL_ID"] == "local"


def test_superset_setup_to_actual_runtime(options, tmp_path):
    opts = superset_options(options, tmp_path)
    root, agent = setup.setup_local(**opts)
    opts["key_file"].unlink()
    opts["secret_file"].unlink()
    assert agent == "codex"
    with setup.local_environment(root):
        assert "SUPERSET_PASSWORD_FILE" not in os.environ
        assert os.environ["SUPERSET_PASSWORD"] == "test-password-credential"
        assert setup.doctor()[0]
        runtime = build_runtime()
        assert runtime.principal.tenant_id == "local"
        assert runtime.principal.principal_id == "local"
        assert runtime.sources._get("superset").tenant_id == "local"
    assert "SUPERSET_PASSWORD" not in os.environ
    assert "SUPERSET_PASSWORD_FILE" not in os.environ
    _, env = setup.read_config(root)
    assert env["SUPERSET_PASSWORD_FILE"] == "superset-password.key"
    assert "test-password" not in (root / "config.toml").read_text()
    for path in (root / "config.toml", root / "typesafe.key", root / "superset-password.key"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_preset_api_token_pair_to_actual_runtime(options, tmp_path):
    root, _ = setup.setup_local(
        **options, source="preset", url="https://workspace.app.preset.io", tenant="team",
        principal="owner", token_name_file=private(tmp_path / "token-name", "test-preset-name"),
        secret_file=private(tmp_path / "token-secret", "test-preset-secret"),
    )
    with setup.local_environment(root):
        assert setup.doctor()[0]
        runtime = build_runtime()
        assert runtime.principal.tenant_id == "team"
        assert runtime.principal.principal_id == "owner"
    _, env = setup.read_config(root)
    assert env["PRESET_TENANT_ID"] == "team"
    assert env["PRESET_DATA_MODE"] == "cached_results"
    assert "test-preset" not in (root / "config.toml").read_text()


def test_mcp_manifest_scoped_without_executing_server(options, tmp_path):
    manifest = manifest_file(tmp_path, "team")
    root, _ = setup.setup_local(**options, source="mcp", manifest=manifest, tenant="team")
    with setup.local_environment(root):
        assert setup.doctor()[0]
        runtime = build_runtime()
        assert runtime.principal.tenant_id == "team"
        assert runtime.sources._get("company").tenant_id == "team"


def test_mcp_tenant_mismatch_is_not_an_invented_grant(options, tmp_path):
    manifest = manifest_file(tmp_path, "another-company")
    with pytest.raises(setup.SetupError, match="match the local tenant"):
        setup.setup_local(**options, source="mcp", manifest=manifest)
    assert not (options["home"] / "config.toml").exists()
    assert not (options["home"] / "typesafe.key").exists()
    assert "another-company" in manifest.read_text()


def test_skip_is_explicit_onboarding_only_and_has_identity(options):
    root, _ = setup.setup_local(**options, source="skip")
    with setup.local_environment(root):
        runtime = build_runtime()
        assert runtime.principal.tenant_id == "local"
        assert "onboarding only" in "\n".join(setup.doctor()[1])


def test_init_then_setup_migrates_identity_preserves_state(options, tmp_path):
    root = setup.initialize(options["home"], key_file=options["key_file"])
    state = private(root / "state" / "untouched", "existing cards")
    setup.setup_local(**superset_options(options, tmp_path))
    assert state.read_text() == "existing cards"
    assert setup.read_config(root)[1]["SIGNALWEAVE_PRINCIPAL_ID"] == "local"


def test_repeated_setup_preserves_every_byte_and_mtime(options, tmp_path):
    opts = superset_options(options, tmp_path)
    root, _ = setup.setup_local(**opts)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}
    setup.setup_local(**opts)
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}
    setup.initialize(root, key_file=options["key_file"])
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}


@pytest.mark.parametrize("change", ["url", "username", "tenant", "principal", "credential"])
def test_existing_settings_and_credentials_never_replaced(options, tmp_path, change):
    opts = superset_options(options, tmp_path)
    root, _ = setup.setup_local(**opts)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    if change == "credential":
        opts["secret_file"] = private(tmp_path / "other", "different-credential")
    else:
        opts[change] = "https://other.internal" if change == "url" else "other"
    with pytest.raises(setup.SetupError, match="not replace"):
        setup.setup_local(**opts)
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("url", [
    "https://user:secret-value@bi.internal", "https://bi.internal?q=secret-value",
    "https://bi.internal#secret-value", "http://remote.internal", "https://bi.internal:bad",
])
def test_invalid_source_does_not_write_any_credentials(options, tmp_path, url):
    opts = superset_options(options, tmp_path)
    opts["url"] = url
    with pytest.raises(setup.SetupError) as error:
        setup.setup_local(**opts)
    assert "secret-value" not in str(error.value)
    assert not list(options["home"].glob("*.key"))
    assert not (options["home"] / "config.toml").exists()


def test_local_superset_http_is_supported(options, tmp_path):
    opts = superset_options(options, tmp_path)
    opts["url"] = "http://127.0.0.1:8088"
    root, _ = setup.setup_local(**opts)
    assert setup.read_config(root)[1]["SUPERSET_URL"] == opts["url"]


@pytest.mark.parametrize("source,url", [
    ("superset", "http://127.0.0.1:0"),
    ("superset", "https://bi.internal:0"),
    ("preset", "https://workspace.app.preset.io:0"),
])
def test_zero_port_rejected_before_publishing_config_or_credentials(options, source, url):
    with pytest.raises(setup.SetupError, match="credential-free HTTPS source URL"):
        setup.setup_local(**options, source=source, url=url)
    assert not (options["home"] / "config.toml").exists()
    assert not list(options["home"].glob("*.key"))


@pytest.mark.parametrize("target", ["root", "ancestor", "key", "manifest"])
def test_symlink_paths_rejected(options, tmp_path, target):
    if target in {"root", "ancestor"}:
        real = tmp_path / "real"
        real.mkdir(mode=0o700)
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)
        options["home"] = link if target == "root" else link / "nested"
    elif target == "key":
        link = tmp_path / "linked-key"
        link.symlink_to(options["key_file"])
        options["key_file"] = link
    else:
        real = manifest_file(tmp_path)
        link = tmp_path / "linked-manifest"
        link.symlink_to(real)
        options.update(source="mcp", manifest=link)
    with pytest.raises(setup.SetupError, match="symlinks"):
        setup.setup_local(**options)


def test_config_publish_failure_rolls_back_new_credentials(options, tmp_path, monkeypatch):
    root = setup.initialize(options["home"], key_file=options["key_file"])
    before = (root / "config.toml").read_bytes()
    monkeypatch.setattr(setup, "_publish_config", lambda *a: (_ for _ in ()).throw(OSError("fail")))
    with pytest.raises(OSError):
        setup.setup_local(**superset_options(options, tmp_path))
    assert (root / "config.toml").read_bytes() == before
    assert not (root / "superset-password.key").exists()
    assert not (root / ".setup.lock").exists()
    assert (root / "typesafe.key").exists()


def test_lock_prevents_concurrent_setup(options):
    root, _ = setup.setup_local(**options)
    private(root / ".setup.lock", "")
    with pytest.raises(setup.SetupError, match="already running"):
        setup.setup_local(**options)
    assert (root / ".setup.lock").exists()


def test_hidden_prompt_never_falls_back_to_echo(tmp_path, monkeypatch):
    def insecure(_):
        warnings.warn("echo", setup.getpass.GetPassWarning, stacklevel=2)
        pytest.fail("should not reach echoed input")

    monkeypatch.setattr(setup.getpass, "getpass", insecure)
    with pytest.raises(setup.SetupError, match="secure terminal"):
        setup.setup_local(tmp_path / "home")
    assert not (tmp_path / "home" / "typesafe.key").exists()


def test_noninteractive_never_prompts(tmp_path, monkeypatch):
    def prompt(_):
        pytest.fail("unattended setup must not prompt")

    monkeypatch.setattr(setup.getpass, "getpass", prompt)
    monkeypatch.setattr("builtins.input", prompt)
    with pytest.raises(setup.SetupError, match="Missing credential"):
        setup.setup_local(tmp_path / "home", non_interactive=True)


@pytest.mark.parametrize("agent", ["codex", "claude"])
def test_registration_quotes_paths_and_never_contains_secrets(options, monkeypatch, agent):
    root, _ = setup.setup_local(**options)
    executable = str(root / 'bin "special"' / "signalweave")
    monkeypatch.setattr(setup.sys, "executable", executable)
    monkeypatch.setattr(setup.sys, "frozen", True, raising=False)
    command = shlex.split(setup.agent_registration(root, agent))
    assert command[command.index("--") + 1:] == [
        executable, "serve", "--transport", "stdio", "--home", str(root),
    ]
    assert "test-jev" not in " ".join(command)


def test_source_password_environment_override_and_restore(options, tmp_path, monkeypatch):
    root, _ = setup.setup_local(**superset_options(options, tmp_path))
    external = private(tmp_path / "override", "override-password")
    monkeypatch.setenv("SUPERSET_PASSWORD_FILE", str(external))
    with setup.local_environment(root):
        assert os.environ["SUPERSET_PASSWORD"] == "override-password"
        assert "SUPERSET_PASSWORD_FILE" not in os.environ
    assert os.environ["SUPERSET_PASSWORD_FILE"] == str(external)
    assert "SUPERSET_PASSWORD" not in os.environ
    monkeypatch.delenv("SUPERSET_PASSWORD_FILE")
    monkeypatch.setenv("SUPERSET_PASSWORD", "inline-override")
    with setup.local_environment(root):
        assert os.environ["SUPERSET_PASSWORD"] == "inline-override"
    assert os.environ["SUPERSET_PASSWORD"] == "inline-override"


def test_existing_comments_preserved_when_extending_init_config(options):
    root = setup.initialize(options["home"], key_file=options["key_file"])
    config = root / "config.toml"
    original = config.read_text() + "\n# local owner notes\n"
    config.write_text(original)
    setup.setup_local(**options)
    assert config.read_text().startswith(original)


def test_source_secrets_require_private_files(options, tmp_path):
    opts = superset_options(options, tmp_path)
    opts["secret_file"].chmod(0o644)
    with pytest.raises(setup.SetupError, match="0600"):
        setup.setup_local(**opts)
    assert not (options["home"] / "config.toml").exists()


def test_existing_source_tenant_conflict_rejected_even_when_skipping_source(options):
    root = setup.initialize(options["home"], key_file=options["key_file"])
    config = root / "config.toml"
    with config.open("a") as stream:
        stream.write('\nSUPERSET_URL = "https://bi.internal"\nSUPERSET_TENANT_ID = "another-tenant"\n')
    before = config.read_bytes()
    with pytest.raises(setup.SetupError, match="not replace"):
        setup.setup_local(**options, source="skip")
    assert config.read_bytes() == before


def test_setup_cli_noninteractive_redacts_failure(options, tmp_path, monkeypatch, capsys):
    password = private(tmp_path / "password", "do-not-print-password")
    monkeypatch.setattr(sys, "argv", [
        "signalweave", "setup", "--non-interactive", "--home", str(options["home"]),
        "--key-file", str(options["key_file"]), "--source", "superset",
        "--url", "https://user:do-not-print-password@bi.internal", "--username", "analyst",
        "--secret-file", str(password),
    ])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    output = capsys.readouterr()
    assert "do-not-print-password" not in output.out + output.err
    assert "test-jev" not in output.out + output.err
    assert not (options["home"] / "config.toml").exists()


def test_invalid_agent_is_validated_before_publishing_credentials(options):
    options["agent"] = "unknown"
    with pytest.raises(setup.SetupError, match="codex or claude"):
        setup.setup_local(**options)
    assert not list(options["home"].glob("*.key"))


def test_conflicting_source_flags_cannot_be_ignored(options, tmp_path):
    with pytest.raises(setup.SetupError, match="do not match"):
        setup.setup_local(**options, source="skip", secret_file=private(tmp_path / "secret", "test-value"))
    assert not (options["home"] / "config.toml").exists()


def test_superset_password_keeps_significant_spaces(options, tmp_path):
    opts = superset_options(options, tmp_path)
    opts["secret_file"].write_text(" significant spaces \n")
    root, _ = setup.setup_local(**opts)
    with setup.local_environment(root):
        assert os.environ["SUPERSET_PASSWORD"] == " significant spaces "
    setup.setup_local(**opts)
