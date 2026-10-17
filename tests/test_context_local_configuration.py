"""Human-facing configuration of existing context tools; no inference."""

import os

import pytest

from signalweave import local_setup
from signalweave.local_status import context_status, local_status


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name in local_setup._ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(local_setup.getpass, "getpass", lambda _: "test-private-key")
    root = local_setup.initialize(tmp_path / "private home")
    with (root / "config.toml").open("a") as output:
        output.write('\nSIGNALWEAVE_TENANT_ID = "example"\nSIGNALWEAVE_PRINCIPAL_ID = "analyst"\n')
    return root


def test_context_toggle_persists_without_touching_other_config_credentials_or_state(home):
    _, before = local_setup.read_config(home)
    state = home / "state" / "signalweave.db"
    state.write_bytes(b"opaque existing state")
    key = (home / "typesafe.key").read_bytes()
    assert context_status(home)["status"] == "disabled"
    for enabled in (True, False, True):
        assert local_setup.configure_domain_context(home, enabled=enabled) == home
        _, after = local_setup.read_config(home)
        assert {k: v for k, v in after.items() if k != "SIGNALWEAVE_KNOWLEDGE_ENABLED"} == before
        assert context_status(home)["enabled"] is enabled
        assert local_status(home)["domain_context"]["enabled"] is enabled
        assert state.read_bytes() == b"opaque existing state"
        assert (home / "typesafe.key").read_bytes() == key
    if os.name == "posix":
        assert (home / "config.toml").stat().st_mode & 0o777 == 0o600


def test_repeated_enable_is_a_noop_and_existing_setup_lock_is_not_removed(home):
    local_setup.configure_domain_context(home, enabled=True)
    before = (home / "config.toml").stat().st_mtime_ns
    local_setup.configure_domain_context(home, enabled=True)
    assert (home / "config.toml").stat().st_mtime_ns == before
    lock = home / ".setup.lock"
    lock.touch(mode=0o600)
    with pytest.raises(local_setup.SetupError, match="already running"):
        local_setup.configure_domain_context(home, enabled=False)
    assert lock.exists() and context_status(home)["enabled"]


def test_context_toggle_preserves_normal_config_comments_and_does_not_edit_string_content(home):
    path = home / "config.toml"
    with path.open("a") as output:
        output.write('\n# Operator note: do not remove\nMCP_HOST = """localhost\nSIGNALWEAVE_KNOWLEDGE_ENABLED = "0"\n"""\n')
    original = path.read_text()
    local_setup.configure_domain_context(home, enabled=True)
    assert path.read_text().startswith(original)
    text = path.read_text().replace('SIGNALWEAVE_KNOWLEDGE_ENABLED = "1"', 'SIGNALWEAVE_KNOWLEDGE_ENABLED = "1" # Keep this explanation')
    path.write_text(text)
    local_setup.configure_domain_context(home, enabled=False)
    assert '# Operator note: do not remove' in path.read_text()
    assert 'SIGNALWEAVE_KNOWLEDGE_ENABLED = "0" # Keep this explanation' in path.read_text()
    assert local_setup.read_config(home)[1]["MCP_HOST"] == 'localhost\nSIGNALWEAVE_KNOWLEDGE_ENABLED = "0"\n'


def test_enable_refuses_to_silently_switch_json_storage(home):
    path = home / "config.toml"
    path.write_text(path.read_text().replace('SIGNALWEAVE_STORE_BACKEND = "sqlite"', 'SIGNALWEAVE_STORE_BACKEND = "json"'))
    before = path.read_bytes()
    with pytest.raises(local_setup.SetupError, match="SQLite"):
        local_setup.configure_domain_context(home, enabled=True)
    assert path.read_bytes() == before and not (home / ".setup.lock").exists()
    local_setup.configure_domain_context(home, enabled=False)


@pytest.mark.parametrize("value,enabled", [("true", True), ("off", False), ("1", True), ("0", False)])
def test_status_exposes_environment_precedence_without_persisting_it(home, monkeypatch, value, enabled):
    before = (home / "config.toml").read_bytes()
    monkeypatch.setenv("SIGNALWEAVE_KNOWLEDGE_ENABLED", value)
    status = context_status(home)
    assert status["enabled"] is enabled and status["environment_override"]
    assert status["configured"] is False and (home / "config.toml").read_bytes() == before


@pytest.mark.parametrize("name,value,expected", [
    ("SIGNALWEAVE_KNOWLEDGE_ENABLED", "not-a-boolean-secret", "invalid"),
    ("SIGNALWEAVE_STORE_BACKEND", "json", "blocked"),
    ("SIGNALWEAVE_PRINCIPAL_ID", "", "blocked"),
])
def test_status_marks_runtime_configuration_limits_without_echoing_values(home, monkeypatch, name, value, expected):
    local_setup.configure_domain_context(home, enabled=True)
    monkeypatch.setenv(name, value)
    result = context_status(home)
    assert result["status"] == expected
    assert "not-a-boolean-secret" not in str(result)


def test_invalid_toggle_type_and_missing_home_do_not_create_state(home, tmp_path):
    with pytest.raises(local_setup.SetupError, match="boolean"):
        local_setup.configure_domain_context(home, enabled="false")
    missing = tmp_path / "not configured"
    with pytest.raises((local_setup.SetupError, OSError)):
        local_setup.configure_domain_context(missing, enabled=True)
    assert not missing.exists()


def test_failed_atomic_publish_releases_owned_lock_and_keeps_original_configuration(home, monkeypatch):
    before = (home / "config.toml").read_bytes()
    def failed(*args):
        raise OSError("synthetic storage failure")
    monkeypatch.setattr(local_setup, "_publish_config", failed)
    with pytest.raises(OSError, match="synthetic"):
        local_setup.configure_domain_context(home, enabled=True)
    assert (home / "config.toml").read_bytes() == before
    assert not (home / ".setup.lock").exists()


@pytest.mark.parametrize("setting,value", [("SIGNALWEAVE_KNOWLEDGE_ENABLED", "private-invalid-value"), ("SIGNALWEAVE_STORE_BACKEND", "json")])
def test_doctor_detects_context_runtime_errors_without_inference(home, monkeypatch, setting, value):
    local_setup.configure_domain_context(home, enabled=True)
    monkeypatch.setenv(setting, value)
    with local_setup.local_environment(home):
        healthy, messages = local_setup.doctor(home)
    assert not healthy
    assert "private-invalid-value" not in str(messages)
    assert any("boolean" in item or "SQLite" in item for item in messages)


def test_enabled_doctor_check_does_not_initialize_database(home):
    local_setup.configure_domain_context(home, enabled=True)
    with local_setup.local_environment(home):
        healthy, messages = local_setup.doctor(home)
    assert healthy and any("context: enabled" in item for item in messages)
    assert not (home / "state" / "signalweave.db").exists()
