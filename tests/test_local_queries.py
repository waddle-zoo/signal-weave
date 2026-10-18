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
from signalweave.query_source import MAX_CATALOG_BYTES, QueryCatalog, load_query_catalog
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


def test_adding_another_workflow_keeps_existing_query_references_active(home, artifact, tmp_path):
    first = import_queries(home, "superset", artifact, yes=True).queries[0]
    second_file = tmp_path/"second-workflow.json"
    value = json.loads(artifact.read_text())
    value["queries"][0].update(key="another-check", title="Another reusable fact", sql="SELECT 42 AS another_fact")
    second_file.write_text(json.dumps(value))
    incoming = QueryCatalog.model_validate(value).queries[0]
    import_queries(home, "superset", second_file, yes=True)
    assert {item["resource"] for item in list_queries(home)} == {first.resource, incoming.resource}
    with local_environment(home):
        runtime = build_runtime(mode="agent")
        query = runtime.sources._adapters["superset_sql"]
        assert set(query.queries) == {first.resource, incoming.resource}
        assert query.client.requests_made == 0


@pytest.mark.parametrize("source", ["superset", "preset"])
def test_upsert_reimports_and_updates_keep_other_definitions_and_stable_order(
    home, artifact, tmp_path, capsys, source,
):
    _, config = read_config(home)
    config.update(PRESET_URL="https://workspace.app.preset.io", SUPERSET_PASSWORD_FILE="password")
    _write_new(home/"password", "retained-credential\n")
    (home/"config.toml").write_text(_config_text(config))
    first = import_queries(home, source, artifact, yes=True)
    capsys.readouterr()
    value = json.loads(artifact.read_text())
    value["queries"][0].update(key="another-check", title="Another workflow", sql="SELECT 42 AS fact")
    second = tmp_path/"second.json"
    second.write_text(json.dumps(value))
    merged = import_queries(home, source, second, yes=True)
    output = capsys.readouterr().out
    assert "1 incoming; 2 active after import; 1 unmentioned queries retained" in output
    assert "Another workflow" in output and "Read a fact" not in output
    assert [q.key for q in merged.queries] == ["watch", "another-check"]
    assert merged.queries[0] == first.queries[0]
    saved = {p.name: p.read_bytes() for p in home.iterdir() if p.is_file()}
    for incoming in (artifact, second):
        assert import_queries(home, source, incoming, yes=True) == merged
    # Reordering incoming definitions also must not reorder already active keys.
    second.write_text(json.dumps({"version": 2, "queries": [
        q.model_dump(mode="json", by_alias=True) for q in reversed(merged.queries)
    ]}))
    assert import_queries(home, source, second, yes=True) == merged
    assert {p.name: p.read_bytes() for p in home.iterdir() if p.is_file()} == saved
    capsys.readouterr()
    value["queries"][0]["sql"] = "SELECT 43 AS fact"
    second.write_text(json.dumps(value))
    updated = import_queries(home, source, second, yes=True)
    assert "new source identity; review affected cards" in capsys.readouterr().out
    assert updated.queries[0] == first.queries[0]
    assert updated.queries[1].resource != merged.queries[1].resource
    assert [item["resource"] for item in list_queries(home)] == [q.resource for q in updated.queries]
    for name, content in saved.items():
        if name != "config.toml":
            assert (home/name).read_bytes() == content
    _, current = read_config(home)
    setting = source.upper() + "_QUERY_SOURCES_FILE"
    assert {k: v for k, v in current.items() if k != setting} == config
    assert load_query_catalog(home/current[setting]) == updated


def test_merged_query_count_bound_fails_before_mutating_home(home, artifact, tmp_path):
    value = json.loads(artifact.read_text())
    query = value["queries"][0]
    value["queries"] = [dict(query, key=f"existing-{i}") for i in range(1000)]
    artifact.write_text(json.dumps(value))
    active = import_queries(home, "superset", artifact, yes=True)
    assert len(active.queries) == 1000
    assert import_queries(home, "superset", artifact, yes=True) == active
    before = {p.name: p.read_bytes() for p in home.iterdir() if p.is_file()}
    incoming = tmp_path/"extra.json"
    incoming.write_text(json.dumps({"version": 2, "queries": [dict(query, key="extra")]}))
    with pytest.raises(SetupError, match="at most 1000"):
        import_queries(home, "superset", incoming, yes=True)
    assert {p.name: p.read_bytes() for p in home.iterdir() if p.is_file()} == before


@pytest.mark.parametrize("meaning", ["m" * 1_000_000, "é" * 170_000], ids=["bytes", "canonical-escaping"])
def test_merged_serialized_byte_bound_fails_before_mutating_home(home, artifact, tmp_path, meaning):
    value = json.loads(artifact.read_text())
    value["queries"][0]["meaning"] = {"metric_names": [meaning]}
    artifact.write_text(json.dumps(value, ensure_ascii=False))
    import_queries(home, "superset", artifact, yes=True)
    before = {p.name: p.read_bytes() for p in home.iterdir() if p.is_file()}
    value["queries"][0]["key"] = "another-check"
    incoming = tmp_path/"extra.json"
    incoming.write_text(json.dumps(value, ensure_ascii=False))
    assert incoming.stat().st_size <= MAX_CATALOG_BYTES
    assert load_query_catalog(incoming).queries[0].key == "another-check"
    with pytest.raises(SetupError, match="serialized byte limit"):
        import_queries(home, "superset", incoming, yes=True)
    assert {p.name: p.read_bytes() for p in home.iterdir() if p.is_file()} == before


@pytest.mark.parametrize("semantic_change", [True, False], ids=["changed-definition", "formatting-only"])
def test_existing_catalog_is_rechecked_under_lock_after_consent(
    home, artifact, tmp_path, monkeypatch, semantic_change,
):
    original = import_queries(home, "superset", artifact, yes=True)
    _, config = read_config(home)
    selected = home/config["SUPERSET_QUERY_SOURCES_FILE"]
    incoming = tmp_path/"extra.json"
    value = json.loads(artifact.read_text())
    value["queries"][0]["key"] = "another-check"
    incoming.write_text(json.dumps(value))
    changed_bytes = None

    def concurrent_edit(_):
        nonlocal changed_bytes
        current = json.loads(selected.read_text())
        if semantic_change:
            current["queries"][0]["sql"] = "SELECT 88 AS fact"
        selected.write_text(json.dumps(current, separators=(",", ":")))
        changed_bytes = selected.read_bytes()
        return "yes"

    def check_under_lock(root, current, prefix):
        if (root/".setup.lock").exists():
            assert current == config
        return real_active_catalog(root, current, prefix)

    from signalweave import local_queries

    real_active_catalog = local_queries._active_catalog
    monkeypatch.setattr(local_queries, "_active_catalog", check_under_lock)
    monkeypatch.setattr("builtins.input", concurrent_edit)
    if semantic_change:
        with pytest.raises(SetupError, match="Query catalog changed during review"):
            import_queries(home, "superset", incoming)
        assert read_config(home)[1] == config
        assert len(list(home.glob("queries-*.json"))) == 1
    else:
        merged = import_queries(home, "superset", incoming)
        assert merged.queries[0] == original.queries[0] and len(merged.queries) == 2
    assert selected.read_bytes() == changed_bytes
    assert not (home/".setup.lock").exists()


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
    output = capsys.readouterr().out
    assert "1 reviewed queries active" in output and "Reconnect" in output
    monkeypatch.setattr("sys.argv", ["signalweave", "queries", "list", "--home", str(home)])
    cli.main()
    assert json.loads(capsys.readouterr().out)[0]["source"] == "superset"
