"""Human import/consent and native runtime wiring without any provider requests."""
import json
import stat

import pytest

from signalweave.local_queries import import_queries, list_queries
from signalweave.local_setup import (
    SetupError,
    _config_text,
    _write_new,
    local_environment,
    read_config,
)
from signalweave.query_source import QueryCatalog
from signalweave.runtime import build_runtime


@pytest.fixture
def home(tmp_path):
    root = tmp_path/"private-home"
    root.mkdir(mode=0o700)
    (root/"state").mkdir(mode=0o700)
    _write_new(root/"config.toml", _config_text({"SUPERSET_URL": "http://127.0.0.1:8088",
        "SIGNALWEAVE_TENANT_ID": "local", "SIGNALWEAVE_PRINCIPAL_ID": "local",
        "SIGNALWEAVE_STORE_BACKEND": "sqlite"}))
    return root


@pytest.fixture
def artifact(tmp_path):
    path = tmp_path/"agent-query.json"
    path.write_text(json.dumps({"version": 2, "queries": [{"key": "watch", "title": "Read a fact",
        "definition": "Expert's agreed measurement", "sql": "SELECT 12.34 AS arbitrary_name",
        "database_id": 1, "dialect": "postgres", "read_only": True}]}))
    return path


def test_import_is_private_immutable_idempotent_and_does_not_change_credentials(home, artifact):
    original = artifact.read_bytes()
    catalog = import_queries(home, "superset", artifact, yes=True)
    root, config = read_config(home)
    stored = root/config["SUPERSET_QUERY_SOURCES_FILE"]
    assert stored != artifact and stored.read_bytes() != b""
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    assert artifact.read_bytes() == original
    assert not any("PASSWORD" in k or "TOKEN" in k for k in config)
    saved = stored.read_bytes()
    assert import_queries(home, "superset", artifact, yes=True) == catalog
    assert stored.read_bytes() == saved
    assert len(list(root.glob("queries-superset-*.json"))) == 1
    assert list_queries(home) == [{"source": "superset", "title": "Read a fact", "resource": catalog.queries[0].resource}]
    replacement = json.loads(artifact.read_text())
    replacement["queries"][0]["sql"] = "SELECT 99 AS arbitrary_name"
    artifact.write_text(json.dumps(replacement))
    updated = import_queries(home, "superset", artifact, yes=True)
    assert updated.queries[0].resource != catalog.queries[0].resource
    assert stored.read_bytes() == saved
    assert len(list(root.glob("queries-superset-*.json"))) == 2


def test_declined_consent_and_invalid_artifacts_do_not_mutate_home(home, artifact, monkeypatch):
    before = (home/"config.toml").read_bytes()
    monkeypatch.setattr("builtins.input", lambda _: "n")
    with pytest.raises(SetupError, match="cancelled"):
        import_queries(home, "superset", artifact)
    assert (home/"config.toml").read_bytes() == before
    assert not list(home.glob("queries-*.json"))
    artifact.write_text('{"version":2,"queries": [{"sql":"DELETE FROM sensitive"}]}')
    with pytest.raises(SetupError, match="Invalid query catalog"):
        import_queries(home, "superset", artifact, yes=True)
    assert (home/"config.toml").read_bytes() == before


def test_lock_unconfigured_source_and_tenant_mismatch_fail_without_changes(home, artifact):
    before = (home/"config.toml").read_bytes()
    with pytest.raises(SetupError, match="Connect preset first"):
        import_queries(home, "preset", artifact, yes=True)
    (home/".setup.lock").touch()
    with pytest.raises(SetupError, match="already running"):
        import_queries(home, "superset", artifact, yes=True)
    assert (home/"config.toml").read_bytes() == before
    (home/".setup.lock").unlink()
    data = json.loads(artifact.read_text())
    data["queries"][0]["meaning"] = {"tenant_id": "another-tenant"}
    artifact.write_text(json.dumps(data))
    with pytest.raises(SetupError, match="Invalid query catalog fields"):
        import_queries(home, "superset", artifact, yes=True)
    assert (home/"config.toml").read_bytes() == before


def test_legacy_artifact_is_rejected_with_field_paths_not_its_sql(home, artifact):
    value = json.loads(artifact.read_text())
    value["version"] = 1
    value["queries"][0]["contract"] = {"source_status": "unknown"}
    value["queries"][0]["max_bytes"] = 50000
    artifact.write_text(json.dumps(value))
    with pytest.raises(SetupError) as caught:
        import_queries(home, "superset", artifact, yes=True)
    assert "Invalid query catalog fields" in str(caught.value)
    assert "version" in str(caught.value) and "contract" in str(caught.value) and "max_bytes" in str(caught.value)
    assert "SELECT" not in str(caught.value) and not list(home.glob("queries-*.json"))


def test_connection_scope_change_during_consent_is_not_silently_accepted(home, artifact, monkeypatch):
    def change_scope(_):
        _, changed = read_config(home)
        changed["SIGNALWEAVE_TENANT_ID"] = "another-tenant"
        (home/"config.toml").write_text(_config_text(changed))
        return "yes"

    monkeypatch.setattr("builtins.input", change_scope)
    with pytest.raises(SetupError, match="changed during review"):
        import_queries(home, "superset", artifact)
    assert not list(home.glob("queries-*.json"))
    assert read_config(home)[1]["SIGNALWEAVE_TENANT_ID"] == "another-tenant"


def test_runtime_reuses_same_connection_and_query_file_from_another_cwd(home, artifact, monkeypatch, tmp_path):
    import_queries(home, "superset", artifact, yes=True)
    monkeypatch.chdir(tmp_path)
    with local_environment(home):
        runtime = build_runtime(mode="agent")
        assert runtime.sources.adapter_names() == ["superset", "superset_sql"]
        base, query = runtime.sources._adapters["superset"], runtime.sources._adapters["superset_sql"]
        assert query.client is base.client
        assert query.client.requests_made == 0


def test_preset_live_permission_requires_explicit_additional_consent(home, artifact):
    _, config = read_config(home)
    config.update(PRESET_URL="https://workspace.app.preset.io", PRESET_DATA_MODE="cached_results",
                  PRESET_ALLOW_LIVE_QUERIES="0", PRESET_ALLOW_REFRESH="0")
    (home/"config.toml").write_text(_config_text(config))
    import_queries(home, "preset", artifact, yes=True)
    _, saved = read_config(home)
    assert saved["PRESET_DATA_MODE"] == "cached_results" and saved["PRESET_ALLOW_LIVE_QUERIES"] == "0"
    import_queries(home, "preset", artifact, yes=True, allow_live_queries=True)
    _, saved = read_config(home)
    assert saved["PRESET_DATA_MODE"] == "live_query"
    assert saved["PRESET_ALLOW_LIVE_QUERIES"] == saved["PRESET_ALLOW_REFRESH"] == "1"


def test_cli_help_schema_import_list_without_launching_provider(home, artifact, monkeypatch, capsys):
    from signalweave import cli

    monkeypatch.setattr("sys.argv", ["signalweave", "queries", "schema"])
    cli.main()
    schema = json.loads(capsys.readouterr().out)
    assert schema["title"] == "QueryCatalog" and schema == QueryCatalog.model_json_schema()
    monkeypatch.setattr("sys.argv", ["signalweave", "queries", "import", "--source", "superset", "--file", str(artifact), "--home", str(home), "--yes"])
    cli.main()
    assert "Reconnect" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["signalweave", "queries", "list", "--home", str(home)])
    cli.main()
    assert json.loads(capsys.readouterr().out)[0]["source"] == "superset"
