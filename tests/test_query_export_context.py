"""Real manifest/adapter pin checks, not source execution or business approval."""

from datetime import datetime, timedelta, timezone

import pytest

from evaluations.harbor_onboarding import export_resource
from signalweave.knowledge import KnowledgeService
from signalweave.knowledge_dependencies import ContextDependencies
from signalweave.knowledge_models import KnowledgeContent, KnowledgeEntry
from signalweave.knowledge_store import SQLiteKnowledgeStore
from signalweave.mcp_source import MCPConnection, MCPSourceAdapter
from signalweave.models import PrincipalContext, SourceRef
from signalweave.sources import SourceRegistry

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)
PRINCIPAL = PrincipalContext(principal_id="owner", tenant_id="local")


def definition(sql="SELECT SUM(amount) AS amount FROM transactions"):
    return {"key": "primary", "resource": "metric:primary", "title": "Source-defined amount", "sql": sql}


def adapter(resources):
    def no_transport(*args, **kwargs):
        raise AssertionError("Pin checks must not execute SQL, contact MCP, or load secrets")

    return MCPSourceAdapter(MCPConnection.model_validate({
        "name": "company_sql", "tenant_id": "local", "context_namespace": "warehouse-one",
        "read_only": True, "transport": {"type": "stdio", "command": ["never-started"]},
        "resources": resources,
    }), transport_factory=no_transport)


async def pinned(tmp_path, resource, *, other_resources=()):
    knowledge = KnowledgeService(SQLiteKnowledgeStore(tmp_path / "context.sqlite3"), SourceRegistry([adapter([resource, *other_resources])]))
    knowledge.store.append(KnowledgeEntry(id="definition", tenant_id="local", revision=1, actor="owner",
        owner_id="owner", status="reviewed", created_at=NOW, content=KnowledgeContent(
            domain="operations", title="Selected source meaning", body="The reviewed meaning belongs to this selected source query.",
            kind="definition", sources=[SourceRef(key="primary", adapter="company_sql", resource="metric:primary", label="Primary source")],
            provenance=["Synthetic owner review"], review_after=NOW + timedelta(days=30))), expected_revision=0)
    dependencies = ContextDependencies(knowledge)
    binding = await dependencies.pin("definition", 1, PRINCIPAL, required_for_action=True, now=NOW)
    return knowledge, dependencies, binding


async def test_changed_saved_sql_is_not_current_under_an_old_context_pin(tmp_path):
    original = export_resource(definition())
    knowledge, dependencies, binding = await pinned(tmp_path, original)
    changed = export_resource(definition("SELECT SUM(amount) AS amount FROM transactions WHERE is_refund = 0"))
    knowledge.sources = SourceRegistry([adapter([changed])])
    result = await dependencies.inspect([binding], PRINCIPAL, now=NOW)
    assert result["entries"][0]["status"] == "source_changed"
    assert result["required_current"] is False


@pytest.mark.parametrize("metadata", [
    {"captured_at": "2026-10-15T12:00:00Z"},
    {"health": "degraded"},
    {"latest_amount": 12345},
])
async def test_measurement_or_health_metadata_does_not_change_source_meaning(tmp_path, metadata):
    original = export_resource(definition())
    knowledge, dependencies, binding = await pinned(tmp_path, original)
    refreshed = export_resource(definition())
    refreshed["descriptor"]["metadata"].update(metadata)
    knowledge.sources = SourceRegistry([adapter([refreshed])])
    result = await dependencies.inspect([binding], PRINCIPAL, now=NOW)
    assert result["entries"][0]["status"] == "current"
    assert result["required_current"] is True


async def test_other_resource_query_revision_does_not_invalidate_selected_source(tmp_path):
    original = export_resource(definition())
    other = export_resource({**definition("SELECT COUNT(*) AS tickets FROM tickets"),
        "key": "other", "resource": "metric:other", "title": "Another source"})
    knowledge, dependencies, binding = await pinned(tmp_path, original, other_resources=[other])
    changed_other = export_resource({**definition("SELECT COUNT(*) AS tickets FROM tickets WHERE closed = 1"),
        "key": "other", "resource": "metric:other", "title": "Another source"})
    knowledge.sources = SourceRegistry([adapter([original, changed_other])])
    result = await dependencies.inspect([binding], PRINCIPAL, now=NOW)
    assert result["entries"][0]["status"] == "current"
    assert result["required_current"] is True


async def test_declared_upstream_revision_change_invalidates_selected_source(tmp_path):
    original = export_resource(definition())
    original["descriptor"]["contract"]["lineage"].append("transactions-view:revision-1")
    knowledge, dependencies, binding = await pinned(tmp_path, original)
    changed = export_resource(definition())
    changed["descriptor"]["contract"]["lineage"].append("transactions-view:revision-2")
    knowledge.sources = SourceRegistry([adapter([changed])])
    result = await dependencies.inspect([binding], PRINCIPAL, now=NOW)
    assert result["entries"][0]["status"] == "source_changed"
    assert result["required_current"] is False


def test_query_digest_is_an_exact_text_revision_not_semantic_equivalence():
    original = export_resource(definition())
    reformatted = export_resource(definition(definition()["sql"] + "\n"))
    assert original["descriptor"]["contract"]["lineage"] != reformatted["descriptor"]["contract"]["lineage"]
