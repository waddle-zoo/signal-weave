"""Tool-boundary integration; these are not frontier-agent business benchmarks."""

from datetime import datetime, timedelta, timezone

import pytest

from signalweave.knowledge import KnowledgeService
from signalweave.knowledge_mcp import KNOWLEDGE_TOOLS
from signalweave.knowledge_store import SQLiteKnowledgeStore
from signalweave.mcp_server import AGENT_PROFILE_TOOLS, create_mcp
from signalweave.models import PrincipalContext, ResourceContract, ResourceDescriptor
from signalweave.runtime import build_runtime
from signalweave.sources import SourceRegistry
from tests.test_local_investigation import make_runtime


class DomainAssets:
    name = "company"

    def __init__(self):
        self.revoked = False
        self.authorizations = []

    async def authorize(self, source, *, authorized_tenants=None):
        self.authorizations.append((source.resource, tuple(authorized_tenants or [])))
        tenant = source.resource.split(":")[0]
        if self.revoked or tenant not in authorized_tenants:
            return None
        return ResourceDescriptor(
            adapter=self.name, resource=source.resource, title="Shared Sales",
            kind="chart", contract=ResourceContract(tenant_id=tenant, authorized=True),
        )

    async def inspect(self, source):
        raise AssertionError("context retrieval must not execute an analytical query")


def content(tenant="a"):
    return {
        "domain": "commercial", "title": "Net sales", "kind": "definition",
        "body": "Net sales excludes refunds and includes online and store sales.",
        "sources": [{"key": "sales", "adapter": "company", "resource": f"{tenant}:sales", "label": "Sales"}],
        "provenance": ["owner-reviewed definition, finance handbook section 3"],
        "review_after": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
    }


def setup(tmp_path, *, request_scoped=False):
    runtime, _, judger = make_runtime(tmp_path)
    assets = DomainAssets()
    registry = SourceRegistry([assets])
    runtime.sources = registry
    runtime.knowledge = KnowledgeService(SQLiteKnowledgeStore(tmp_path / "context.db"), registry)
    identity = [PrincipalContext(
        principal_id="analyst", tenant_id="a",
        scopes=["knowledge:write", "knowledge:review", "knowledge:share"],
    )]
    runtime.principal = None if request_scoped else identity[0]
    server = create_mcp(
        runtime, principal_resolver=(lambda ctx: identity[0]) if request_scoped else None,
        require_principal=request_scoped,
    )
    return server, runtime, assets, identity, judger


@pytest.mark.parametrize("request_scoped", [False, True])
async def test_context_onboarding_reuse_history_and_changed_meaning(tmp_path, request_scoped):
    server, runtime, assets, _, judger = setup(tmp_path, request_scoped=request_scoped)
    assert {x.name for x in await server.list_tools()} == AGENT_PROFILE_TOOLS | KNOWLEDGE_TOOLS
    _, guide = await server.call_tool("get_signalweave_guide", {})
    assert set(guide["domain_context"]["tools"]) == KNOWLEDGE_TOOLS
    _, draft = await server.call_tool("save_domain_context", {"content": content()})
    _, before = await server.call_tool("retrieve_domain_context", {"query": "net sales"})
    assert before["entries"] == []
    _, reviewed = await server.call_tool("review_domain_context", {
        "entry_id": draft["id"], "expected_revision": 1,
        "action": "approve", "reason": "Finance owner confirmed source and refund treatment.",
    })
    assert reviewed["revision"] == 2
    for task in ("sales brief", "refund investigation"):
        _, packet = await server.call_tool("retrieve_domain_context", {
            "query": task, "source_refs": ["company|a:sales"],
        })
        assert [x["id"] for x in packet["entries"]] == [draft["id"]]
        assert packet["freshness"] == {draft["id"]: "current"}
    changed = content()
    changed["body"] = "Net sales now excludes marketplace sales; validate comparability."
    _, edited = await server.call_tool("save_domain_context", {
        "content": changed, "entry_id": draft["id"], "expected_revision": 2,
    })
    assert edited["status"] == "draft" and edited["revision"] == 3
    _, current = await server.call_tool("retrieve_domain_context", {"query": "net sales"})
    assert current["entries"] == []  # no silent fallback to superseded reviewed meaning
    _, history = await server.call_tool("get_context_history", {"entry_id": draft["id"]})
    assert {x["revision"] for x in history["revisions"]} == {1, 2, 3}
    assert judger.states == []
    assert assets.authorizations
    assert runtime.card_store.get_card("repeat").status == "approved"  # no card mutation


async def test_hosted_identity_not_tool_input_controls_tenant(tmp_path):
    server, _, _, identity, _ = setup(tmp_path, request_scoped=True)
    _, draft = await server.call_tool("save_domain_context", {"content": content()})
    identity[0] = PrincipalContext(principal_id="analyst", tenant_id="b")
    _, packet = await server.call_tool("retrieve_domain_context", {"query": "sales", "include_drafts": True})
    assert packet["entries"] == []
    with pytest.raises(Exception, match="not found"):
        await server.call_tool("get_context_history", {"entry_id": draft["id"]})
    spec = next(x for x in await server.list_tools() if x.name == "save_domain_context")
    assert not {"tenant_id", "principal_id", "actor"} & spec.inputSchema["properties"].keys()


async def test_revoked_link_excludes_body_from_packet_and_history(tmp_path):
    server, _, assets, _, _ = setup(tmp_path)
    _, saved = await server.call_tool("save_domain_context", {"content": content()})
    assets.revoked = True
    _, packet = await server.call_tool("retrieve_domain_context", {"include_drafts": True})
    _, history = await server.call_tool("get_context_history", {"entry_id": saved["id"]})
    assert packet["entries"] == history["revisions"] == []
    assert "Net sales" not in str(packet) + str(history)


async def test_missing_identity_cannot_write_or_read_context(tmp_path):
    server, runtime, _, _, _ = setup(tmp_path)
    runtime.principal = None
    for name, args in (
        ("retrieve_domain_context", {}), ("save_domain_context", {"content": content()}),
    ):
        with pytest.raises(Exception, match="tenant/principal"):
            await server.call_tool(name, args)


async def test_extension_is_absent_without_explicit_runtime_configuration(tmp_path):
    runtime, _, _ = make_runtime(tmp_path)
    server = create_mcp(runtime)
    assert {x.name for x in await server.list_tools()} == AGENT_PROFILE_TOOLS
    _, guide = await server.call_tool("get_signalweave_guide", {})
    assert "domain_context" not in guide


@pytest.mark.parametrize("permission", ["knowledge:write", "knowledge:review"])
async def test_shared_gateway_enforces_curation_scopes(tmp_path, permission):
    server, _, _, identity, _ = setup(tmp_path, request_scoped=True)
    _, saved = await server.call_tool("save_domain_context", {"content": content()})
    identity[0].scopes.remove(permission)
    name, args = (
        ("save_domain_context", {"content": content()}) if permission == "knowledge:write"
        else ("review_domain_context", {
            "entry_id": saved["id"], "expected_revision": 1, "action": "approve", "reason": "Owner confirmation",
        })
    )
    with pytest.raises(Exception, match="permission denied"):
        await server.call_tool(name, args)


async def test_shared_gateway_writer_cannot_publish_without_share_scope(tmp_path):
    server, _, _, identity, _ = setup(tmp_path, request_scoped=True)
    identity[0].scopes = ["knowledge:write"]
    with pytest.raises(Exception, match="knowledge:share"):
        await server.call_tool("save_domain_context", {"content": content()})
    private = content()
    private["reader_principal_ids"] = [identity[0].principal_id]
    _, saved = await server.call_tool("save_domain_context", {"content": private})
    assert saved["status"] == "draft"


@pytest.mark.parametrize("enabled", ["0", "1"])
def test_runtime_wires_only_explicitly_enabled_sqlite_context(monkeypatch, tmp_path, enabled):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "runtime.db"))
    monkeypatch.setenv("SIGNALWEAVE_KNOWLEDGE_ENABLED", enabled)
    runtime = build_runtime(adapters=[DomainAssets()])
    assert (runtime.knowledge is not None) == (enabled == "1")


def test_context_rejects_json_backend_instead_of_silent_ephemeral_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "json")
    monkeypatch.setenv("SIGNALWEAVE_KNOWLEDGE_ENABLED", "1")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="requires SIGNALWEAVE_STORE_BACKEND=sqlite"):
        build_runtime(adapters=[DomainAssets()])
