"""HTTP liveness/readiness contract for local and deployed runtimes."""

from __future__ import annotations

import httpx
import pytest

from signalweave.auth import BearerTokenMiddleware
from signalweave.engine import InsightEngine
from signalweave.mcp_server import create_mcp
from signalweave.models import PrincipalContext, ResourceDescriptor, ResourceSnapshot, SourceRef
from signalweave.readiness import deployment_readiness
from signalweave.runtime import AgentOwnedJudger, Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import (
    InMemoryDecisionFeedbackStore,
    InMemoryDecisionReceiptStore,
    JsonInsightCardStore,
)


class JevDouble:
    name = "jev-readiness-test"

    async def compile_plan(self, state, card):  # pragma: no cover - readiness never calls Jev
        del state, card
        return {}

    async def judge(self, state, card, plan, observations):  # pragma: no cover
        del state, card, plan, observations
        raise AssertionError("readiness must never call Jev")


class SourceDouble:
    name = "looker"

    async def list_resources(self):
        return [
            ResourceDescriptor(
                adapter=self.name,
                resource="explore:orders",
                kind="explore",
                title="Orders",
            )
        ]

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        return ResourceSnapshot(
            source_key=source.key,
            adapter=source.adapter,
            resource=source.resource,
            title=source.label,
        )


def _runtime(tmp_path, *, principal: PrincipalContext | None = None, sources=()):
    return Runtime(
        card_store=JsonInsightCardStore(tmp_path / "cards.json"),
        sources=SourceRegistry(sources),
        engine=InsightEngine(JevDouble()),
        decision_receipts=InMemoryDecisionReceiptStore(),
        decision_feedback=InMemoryDecisionFeedbackStore(),
        principal=principal,
    )


def test_readiness_report_is_safe_and_has_no_network_or_jev_work(tmp_path):
    report = deployment_readiness(
        _runtime(
            tmp_path,
            principal=PrincipalContext(tenant_id="acme", principal_id="agent"),
            sources=[SourceDouble()],
        ),
        profile="agent",
    )

    assert report["status"] == "ready"
    assert report["startup_ready"] is True
    assert report["source_adapters"] == ["looker"]
    assert report["principal_mode"] == "static"
    assert report["network_checks"] == 0
    assert report["jev_requests"] == 0
    assert report["checks"]["decision_provider_wired"] is True
    assert all(field not in report for field in ("api_key", "access_token", "secret", "password"))


@pytest.mark.parametrize("provider_name", ["openai-decisions", "chatgpt-plan-responses"])
def test_readiness_accepts_non_jev_provider_wiring_without_auth_probe(tmp_path, provider_name):
    runtime = _runtime(
        tmp_path,
        principal=PrincipalContext(tenant_id="acme", principal_id="agent"),
        sources=[SourceDouble()],
    )
    runtime.engine.judger = JevDouble()
    runtime.engine.judger.name = provider_name

    report = deployment_readiness(runtime, profile="agent")

    assert report["status"] == "ready"
    assert report["checks"]["decision_provider_wired"] is True
    assert report["decision_path"] == provider_name
    assert report["network_checks"] == 0
    assert report["jev_requests"] == 0


def test_readiness_rejects_unconfigured_agent_owned_guard(tmp_path):
    runtime = _runtime(
        tmp_path,
        principal=PrincipalContext(tenant_id="acme", principal_id="agent"),
        sources=[SourceDouble()],
    )
    runtime.engine.judger = AgentOwnedJudger()

    report = deployment_readiness(runtime, profile="agent")

    assert report["status"] == "not_ready"
    assert report["checks"]["decision_provider_wired"] is False


def test_readiness_fails_closed_without_source_or_identity(tmp_path):
    report = deployment_readiness(_runtime(tmp_path))

    assert report["status"] == "not_ready"
    assert report["startup_ready"] is False
    assert report["checks"]["source_adapter"] is False
    assert report["checks"]["identity_boundary"] is False


@pytest.mark.parametrize(
    "provider_name",
    ["jev-readiness-test", "openai-decisions", "chatgpt-plan-responses"],
)
@pytest.mark.asyncio
async def test_readyz_is_public_but_mcp_remains_bearer_protected(tmp_path, provider_name):
    runtime = _runtime(
        tmp_path,
        principal=PrincipalContext(tenant_id="acme", principal_id="agent"),
        sources=[SourceDouble()],
    )
    runtime.engine.judger.name = provider_name
    server = create_mcp(runtime, profile="full", require_principal=True)
    server_app = server.streamable_http_app()
    app = BearerTokenMiddleware(server_app, token="deployment-token")

    # create_mcp's route is tested directly; the token middleware is exercised
    # by the deployed CLI smoke and has a separate unit contract.
    async with server_app.router.lifespan_context(server_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            ready = await client.get("/readyz")
            assert ready.status_code == 200
            assert ready.json()["startup_ready"] is True
            assert ready.json()["decision_path"] == provider_name
            assert ready.json()["checks"]["decision_provider_wired"] is True

            health = await client.get("/healthz")
            assert health.status_code == 200
            assert health.json()["source_adapters"] == ["looker"]

            unauthorized = await client.post("/mcp")
            assert unauthorized.status_code == 401
