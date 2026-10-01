import json
import os
import socket
import stat
import warnings

import pytest
import tomllib

from signalweave import local_setup as setup


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    for name in (*setup._ENV_NAMES, "SIGNALWEAVE_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setattr(setup.getpass, "getpass", lambda _: "test-local-key")
    return setup.initialize(tmp_path / "local home")


def private_file(path, text):
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


def add_config(home, text):
    config = home / "config.toml"
    config.write_text(config.read_text() + "\n" + text + "\n")


def test_init_creates_private_files_and_onboarding_config(home):
    root, environment = setup.read_config(home)
    assert root == home
    assert environment["TYPESAFE_API_KEY_FILE"] == "typesafe.key"
    assert environment["SIGNALWEAVE_ALLOW_EMPTY_SOURCES"] == "1"
    assert "test-local-key" not in (home / "config.toml").read_text()
    assert not (home / "state" / "signalweave.db").exists()
    if os.name == "posix":
        for path in (home, home / "state"):
            assert stat.S_IMODE(path.stat().st_mode) == 0o700
        for path in (home / "config.toml", home / "typesafe.key"):
            assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_key_file_is_copied_and_survives_original_removal(tmp_path):
    source = private_file(tmp_path / "source-key", "test-file-key\n")
    root = setup.initialize(tmp_path / "local", key_file=source)
    source.unlink()
    with setup.local_environment(root):
        assert setup.validate_key_configuration() == "readable private file"
    assert (root / "typesafe.key").read_text() == "test-file-key\n"


def test_repeated_init_preserves_config_key_and_database(home, monkeypatch):
    add_config(home, 'SUPERSET_URL = "http://localhost:8088"')
    database = private_file(home / "state" / "signalweave.db", "existing-state")
    original = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (
        home / "config.toml", home / "typesafe.key", database,
    )}
    monkeypatch.setattr(setup.getpass, "getpass", lambda _: pytest.fail("unexpected key prompt"))
    assert setup.initialize(home) == home
    assert setup.initialize(home, key_file=home / "typesafe.key") == home
    assert original == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in original}


def test_repeated_init_rejects_key_replacement(home, tmp_path):
    source = private_file(tmp_path / "replacement", "different-key")
    with pytest.raises(setup.SetupError, match="cannot replace"):
        setup.initialize(home, key_file=source)
    assert (home / "typesafe.key").read_text().strip() == "test-local-key"


def test_init_recovers_after_key_was_written_before_config(tmp_path, monkeypatch):
    root = tmp_path / "incomplete"
    root.mkdir(mode=0o700)
    private_file(root / "typesafe.key", "test-existing-key")
    monkeypatch.setattr(setup.getpass, "getpass", lambda _: pytest.fail("unexpected key prompt"))
    setup.initialize(root)
    assert (root / "typesafe.key").read_text() == "test-existing-key"
    assert (root / "config.toml").exists()


@pytest.mark.parametrize("key", ["", "\n", "replace-me", "first\nsecond", "a\x00b"])
def test_init_rejects_bad_keys_without_persisting_them(tmp_path, monkeypatch, key):
    monkeypatch.setattr(setup.getpass, "getpass", lambda _: key)
    root = tmp_path / "bad-key"
    with pytest.raises(setup.SetupError):
        setup.initialize(root)
    assert not (root / "typesafe.key").exists()
    assert not (root / "config.toml").exists()


def test_init_never_falls_back_to_echoing_stdin(tmp_path, monkeypatch):
    def no_terminal(_):
        warnings.warn("echo would be enabled", setup.getpass.GetPassWarning, stacklevel=2)
        pytest.fail("must stop before reading echoed input")

    monkeypatch.setattr(setup.getpass, "getpass", no_terminal)
    with pytest.raises(setup.SetupError, match="secure terminal"):
        setup.initialize(tmp_path / "headless")


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
@pytest.mark.parametrize("target", ["home", "state", "config.toml", "typesafe.key"])
def test_group_or_world_access_is_rejected(home, target):
    path = home if target == "home" else home / target
    path.chmod(0o755 if path.is_dir() else 0o644)
    with pytest.raises(setup.SetupError, match="chmod"):
        with setup.local_environment(home):
            setup.validate_key_configuration()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_insecure_source_key_file_is_not_copied_or_chmodded(tmp_path):
    key = private_file(tmp_path / "input", "test-key")
    key.chmod(0o644)
    with pytest.raises(setup.SetupError, match="0600"):
        setup.initialize(tmp_path / "new", key_file=key)
    assert stat.S_IMODE(key.stat().st_mode) == 0o644
    assert not (tmp_path / "new" / "typesafe.key").exists()


@pytest.mark.parametrize("target", ["config.toml", "typesafe.key"])
def test_symlinks_cannot_redirect_local_files(home, tmp_path, target):
    external = private_file(tmp_path / "external", "test-do-not-touch")
    path = home / target
    path.unlink()
    path.symlink_to(external)
    with pytest.raises(setup.SetupError, match="symlinks"):
        with setup.local_environment(home):
            setup.validate_key_configuration()
    assert external.read_text() == "test-do-not-touch"


def test_init_rejects_symlink_home(tmp_path):
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(setup.SetupError, match="symlinks"):
        setup.initialize(link)
    assert list(target.iterdir()) == []


def test_config_paths_are_independent_of_cwd_and_environment_restored(home, tmp_path, monkeypatch):
    add_config(home, 'TRINO_CATALOG_FILE = "catalog.json"\nSIGNALWEAVE_MCP_SOURCES_FILE = "sources.json"')
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    with pytest.raises(RuntimeError, match="test exit"):
        with setup.local_environment(home):
            assert os.environ["TYPESAFE_API_KEY_FILE"] == str(home / "typesafe.key")
            assert os.environ["SIGNALWEAVE_STORE_PATH"] == str(home / "state" / "signalweave.db")
            assert os.environ["TRINO_CATALOG_FILE"] == str(home / "catalog.json")
            assert os.environ["SIGNALWEAVE_MCP_SOURCES_FILE"] == str(home / "sources.json")
            assert os.environ["DECISION_RECEIPT_STORE"] == str(home / "state" / "decision-receipts.json")
            raise RuntimeError("test exit")
    assert "TYPESAFE_API_KEY_FILE" not in os.environ
    assert "SIGNALWEAVE_STORE_PATH" not in os.environ


@pytest.mark.parametrize("name,value", [
    ("TYPESAFE_API_KEY", "test-env-key"), ("TYPESAFE_API_KEY_FILE", "override.key"),
    ("TYPESAFE_API_KEY", ""),
])
def test_environment_key_selection_overrides_local_pair(home, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with setup.local_environment(home):
        assert os.environ[name] == (str(home / value) if name.endswith("_FILE") else value)
        other = "TYPESAFE_API_KEY_FILE" if name == "TYPESAFE_API_KEY" else "TYPESAFE_API_KEY"
        assert other not in os.environ
    assert os.environ[name] == value


def test_environment_file_overrides_local_inline_secret(home, monkeypatch):
    add_config(home, 'PRESET_ACCESS_TOKEN = "test-local-token"')
    monkeypatch.setenv("PRESET_ACCESS_TOKEN_FILE", "/external/deployment/token")
    with setup.local_environment(home):
        assert "PRESET_ACCESS_TOKEN" not in os.environ
        assert os.environ["PRESET_ACCESS_TOKEN_FILE"] == "/external/deployment/token"


def test_empty_store_path_cannot_silently_create_temporary_sqlite_database(home, monkeypatch):
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", "")
    with pytest.raises(setup.SetupError, match="durable storage path"):
        with setup.local_environment(home):
            pytest.fail("empty SQLite paths are temporary databases")


def test_home_resolution_precedence(tmp_path, monkeypatch):
    assert setup.resolve_home() == tmp_path / ".signalweave"
    monkeypatch.setenv("SIGNALWEAVE_HOME", str(tmp_path / "from-env"))
    assert setup.resolve_home() == tmp_path / "from-env"
    assert setup.resolve_home(tmp_path / "explicit") == tmp_path / "explicit"


@pytest.mark.parametrize("config", [
    'version = 2\n[environment]\n', 'version = true\n[environment]\n',
    'version = 1\n[environment]\nTYPESAFE_API_KEY = 42\n',
    'version = 1\n[environment]\nPATH = "/bad"\n',
    'version = 1\n[environment]\n"test-secret" = "never-print"\n',
    'version = 1\n[environment]\nTYPESAFE_API_KEY = "never-print',
])
def test_malformed_config_fails_without_echoing_contents(home, config):
    (home / "config.toml").write_text(config)
    with pytest.raises(setup.SetupError) as error:
        setup.read_config(home)
    assert "never-print" not in str(error.value)
    assert "test-secret" not in str(error.value)


def test_offline_doctor_does_not_build_runtime_or_touch_network(home, monkeypatch):
    import signalweave.runtime as runtime

    def forbidden(*args, **kwargs):
        pytest.fail("offline doctor must not contact a provider or construct a runtime")

    monkeypatch.setattr(runtime, "build_runtime", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    before = sorted(home.rglob("*"))
    with setup.local_environment(home):
        healthy, messages = setup.doctor()
    assert healthy
    assert "onboarding only" in "\n".join(messages)
    assert "remain unverified" in "\n".join(messages)
    assert "test-local-key" not in "\n".join(messages)
    assert sorted(home.rglob("*")) == before


def test_doctor_requires_sources_without_explicit_onboarding_setting(home, monkeypatch):
    monkeypatch.setenv("SIGNALWEAVE_ALLOW_EMPTY_SOURCES", "0")
    with setup.local_environment(home):
        healthy, messages = setup.doctor()
    assert not healthy
    assert any("No source configured" in line for line in messages)


@pytest.mark.parametrize("environment, expected", [
    ({"SUPERSET_URL": "https://user:test-secret@superset.example"}, "SUPERSET_URL"),
    ({"SUPERSET_URL": "https://superset.example", "SUPERSET_USERNAME": "alice"}, "together"),
    ({"TRINO_URL": "https://trino.example"}, "TRINO_URL and TRINO_CATALOG_FILE"),
    ({"PRESET_URL": "https://preset.example", "PRESET_ACCESS_TOKEN": "test-secret"}, "Preset configuration invalid"),
    ({"SIGNALWEAVE_TENANT_ID": "test-secret"}, "configured together"),
    ({"TYPESAFE_API_KEY": "test-secret", "TYPESAFE_API_KEY_FILE": "missing"}, "Set only one"),
])
def test_doctor_rejects_partial_configuration_without_secrets(home, monkeypatch, environment, expected):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    with setup.local_environment(home):
        healthy, messages = setup.doctor()
    report = "\n".join(messages)
    assert not healthy
    assert expected in report
    assert "test-secret" not in report


def test_doctor_missing_key_is_failure(home):
    (home / "typesafe.key").unlink()
    with setup.local_environment(home):
        healthy, messages = setup.doctor()
    assert not healthy
    assert "missing or unreadable" in "\n".join(messages)


def test_doctor_reuses_mcp_manifest_validation_offline(home, monkeypatch):
    manifest = {"version": 1, "connections": [{
        "name": "internal", "tenant_id": "acme", "read_only": True,
        "transport": {"type": "stdio", "command": ["/never/execute/this"]},
        "resources": [{"source_key": "revenue", "tool": "read_snapshot", "descriptor": {
            "adapter": "internal", "resource": "revenue", "kind": "metric", "title": "Revenue",
            "contract": {"tenant_id": "acme"},
        }}],
    }]}
    private_file(home / "sources.json", json.dumps(manifest))
    monkeypatch.setenv("SIGNALWEAVE_MCP_SOURCES_FILE", "sources.json")
    with setup.local_environment(home):
        healthy, messages = setup.doctor()
    assert healthy
    assert any("manifest schema valid" in line for line in messages)
    manifest["connections"][0]["read_only"] = False
    (home / "sources.json").write_text(json.dumps(manifest))
    with setup.local_environment(home):
        healthy, messages = setup.doctor()
    assert not healthy
    assert any("valid MCP source manifest" in line for line in messages)


def test_agent_snippets_round_trip_spaces_quotes_and_unicode(tmp_path, monkeypatch):
    root = tmp_path / 'local "雪" home'
    executable = str(tmp_path / 'virtual env "雪"' / "bin" / "python")
    monkeypatch.setattr(setup.sys, "executable", executable)
    codex = tomllib.loads(setup.agent_config(root, "codex"))["mcp_servers"]["signalweave"]
    claude = json.loads(setup.agent_config(root, "claude"))["mcpServers"]["signalweave"]
    for snippet in (codex, claude):
        assert snippet["command"] == executable
        assert snippet["args"] == ["-m", "signalweave.cli", "serve", "--transport", "stdio", "--home", str(root)]
        assert "env" not in snippet
    assert not root.exists()


def test_frozen_agent_snippet_uses_binary_without_python_arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.sys, "frozen", True, raising=False)
    monkeypatch.setattr(setup.sys, "executable", str(tmp_path / "signalweave"))
    entry = json.loads(setup.agent_config(tmp_path / "home", "claude"))["mcpServers"]["signalweave"]
    assert entry["args"] == ["serve", "--transport", "stdio", "--home", str(tmp_path / "home")]
