"""Offline harness contracts; doubles are never trial evidence."""

import copy
import json
import ssl
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from typesafe_sdk import SystemOneResponse, Usage

from evaluations import bootstrap_agent_trial as trial
from evaluations.bootstrap_scenarios import build_scenarios, public_scenario
from signalweave.engine import InsightEngine
from signalweave.mcp_server import create_mcp
from signalweave.models import (
    InsightCard,
    InsightResult,
    Observation,
    PrincipalContext,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import JsonInsightCardStore, JsonMetricQueryCardStore


class OfflineJudger:
    name = "offline-harness-contract-double"

    async def compile_plan(self, state, card):
        return {"capabilities": ["freshness_check"], "baseline": "previous_period"}

    async def rank_resources(self, goal, resources):
        return {f"{item.adapter}|{item.resource}": .99 for item in resources}

    async def judge(self, state, card, plan, observations):
        return InsightResult(card_id=card.id, outcome="ignore", summary="Test only",
                             rationale="Not evidence", confidence=.99,
                             evidence=state["evidence"], observations=observations,
                             source_keys=[source.key for source in card.sources], evaluator=self.name)


def test_codex_credentials_require_only_jev(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-jev")
    args = trial.parser().parse_args(["--agent-transport", "codex"])
    assert trial.credentials(args) == ("", "offline-jev")
    monkeypatch.delenv("TYPESAFE_API_KEY")
    with pytest.raises(ValueError, match="TYPESAFE_API_KEY") as error:
        trial.credentials(args)
    assert "OPENAI_API_KEY" not in str(error.value)


def test_push_gated_ignore_preserves_reported_numeric_facts_without_waking_agent():
    system_output = {
        "result": {
            "outcome": "ignore",
            "report": {
                "status": "complete",
                "next_step": "Suppress delivery.",
                "provenance": [{"source_key": "primary", "comparison_key": "net_sales",
                                 "query_refs": ["superset|dashboard:weekly"]}],
                "numeric_claims": [{"metric": "net_sales", "unit": "USD",
                                    "source_key": "primary", "comparison_key": "net_sales",
                                    "baseline": 100.0, "current": 100.0, "delta": 0.0,
                                    "contributions": []}],
            },
        }
    }
    submission = trial.push_gated_ignore_submission(
        system_output, {"net_sales.delta", "net_sales.current"}
    )
    assert submission is not None
    assert submission["outcome"] == "ignore"
    assert submission["evidence_refs"] == ["superset|dashboard:weekly"]
    assert {claim["fact"] for claim in submission["numeric_claims"]} == {
        "net_sales.current", "net_sales.delta"
    }
    assert trial.push_gated_ignore_submission(
        {"result": {"outcome": "notify", "report": {}}}, {"net_sales.delta"}
    ) is None


def test_same_card_monitoring_is_scoped_to_each_company_period_pair():
    rows = [
        {"phase": "monitoring", "scenario_id": "company-a", "period_id": "p1",
         "shared_card_digest": "card-a"},
        {"phase": "monitoring", "scenario_id": "company-a", "period_id": "p1",
         "shared_card_digest": "card-a"},
        {"phase": "monitoring", "scenario_id": "company-b", "period_id": "p1",
         "shared_card_digest": "card-b"},
        {"phase": "monitoring", "scenario_id": "company-b", "period_id": "p1",
         "shared_card_digest": "card-b"},
    ]
    assert trial.same_card_monitoring_observed(rows)
    rows[-1]["shared_card_digest"] = "different-card-b"
    assert not trial.same_card_monitoring_observed(rows)


def test_card_fingerprint_ignores_response_transport_metadata():
    card = {"id": "card-1", "title": "Growth", "what_to_watch": "conversion"}
    compact = {**card, "response_mode": "compact", "details_available": True}
    full = {**card, "response_mode": "full", "details_available": True}
    assert trial.card_fingerprint(card) == trial.card_fingerprint(compact)
    assert trial.card_fingerprint(card) == trial.card_fingerprint(full)


def test_explicit_regression_subset_preserves_whole_companies_fixture_order_and_inputs():
    scenarios = build_scenarios(seed=20261002)
    before = copy.deepcopy(scenarios)
    ids = [scenarios[3]["scenario_id"], scenarios[2]["scenario_id"]]
    selected = trial.select_scenarios(scenarios, ids, 2)
    assert selected == scenarios[2:4]
    assert scenarios == before
    assert all(len(s["public"]["periods"]) == 3 for s in selected)
    assert trial.select_scenarios(scenarios, None, 2) == scenarios[:2]
    for bad, limit in (([], 2), ([ids[0], ids[0]], 2), (["not-a-company"], 2), (ids, 1), (None, 0)):
        with pytest.raises(ValueError):
            trial.select_scenarios(scenarios, bad, limit)


@pytest.fixture
def public():
    return public_scenario(build_scenarios(split="dev")[0])


def make_session(tmp_path, public, treatment=True, onboarding_surface="full"):
    audit = trial.Audit()
    adapter = trial.PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
    adapter.set_period(public["onboarding"], datetime.now(timezone.utc))
    registry = SourceRegistry([adapter])
    runtime = Runtime(card_store=JsonInsightCardStore(tmp_path / "cards.json"), sources=registry,
                      engine=InsightEngine(OfflineJudger(), registry),
                      metric_query_store=JsonMetricQueryCardStore(tmp_path / "metric-cards.json"),
                      principal=PrincipalContext(principal_id="offline", tenant_id=public["scenario_id"]))
    return trial.ToolSession(public, adapter, create_mcp(runtime), treatment,
                             onboarding_surface=onboarding_surface)


async def test_product_tool_parity_includes_guide_sources_preview_and_workflow(tmp_path, public):
    session = make_session(tmp_path, public, onboarding_surface="guided")
    specs = await session.specs()
    names = {item["name"] for item in specs}
    assert {"get_signalweave_guide", "bootstrap_insight_card", "get_insight_card",
            "preview_investigation_report", "approve_insight_card"} <= names
    assert "evaluate_card_workflow" not in names
    common_names = {item["name"] for item in trial.common_tools(public, "onboarding")}
    assert names - common_names - {"request_synthetic_owner_approval"} <= trial.ONBOARDING_PRODUCT_TOOLS


async def test_owner_review_context_bounds_large_catalog_and_keeps_card_anchor(tmp_path, public):
    session = make_session(tmp_path, public, treatment=True)
    session.adapter.catalog.extend(
        ResourceDescriptor(
            adapter="superset",
            resource=f"noise:{index}",
            kind="dashboard",
            title=f"Unrelated asset {index}",
            description="A separate asset outside the selected workflow.",
        )
        for index in range(80)
    )
    anchor = session.adapter.catalog[-1]
    session.latest_card = {
        "sources": [{"adapter": anchor.adapter, "resource": anchor.resource}]
    }

    context = session.owner_source_context()

    catalog_refs = {
        f"{item['adapter']}|{item['resource']}" for item in context["catalog"]
    }
    assert len(context["catalog"]) == 64
    assert f"{anchor.adapter}|{anchor.resource}" in catalog_refs


async def test_catalog_search_is_shared_and_bounded_for_large_catalogs(tmp_path, public):
    baseline = make_session(tmp_path / "baseline", public, treatment=False)
    treatment = make_session(tmp_path / "treatment", public, treatment=True)
    baseline_specs = {item["name"] for item in await baseline.specs()}
    treatment_specs = {item["name"] for item in await treatment.specs()}
    assert "search_catalog" in baseline_specs
    assert "search_catalog" in treatment_specs
    common_names = {item["name"] for item in trial.common_tools(public, "onboarding")}
    assert common_names <= baseline_specs
    assert common_names <= treatment_specs

    result = await baseline.call("search_catalog", {"query": "customer", "limit": 2})

    assert len(result["resources"]) <= 2
    assert result["strategy"] == "local-scan-fallback"
    assert result["total_count"] == len(public["catalog"])


async def test_full_onboarding_surface_retains_advanced_product_tools(tmp_path, public):
    session = make_session(tmp_path, public)
    names = {item["name"] for item in await session.specs()}
    assert {"onboard_insight_card", "draft_insight_card", "evaluate_card_workflow"} <= names
    assert "bootstrap_insight_card" in names


async def test_multi_connector_public_transport_dispatches_through_registered_adapters(tmp_path):
    connector_public = public_scenario(build_scenarios(split="dev", connector_profile=True)[0])
    audit = trial.Audit()
    hub = trial.PublicSourceAdapter(connector_public["catalog"], connector_public["scenario_id"], audit)
    hub.set_period(connector_public["onboarding"], datetime.now(timezone.utc))
    names = sorted({item["adapter"] for item in connector_public["catalog"]})
    registry = SourceRegistry([trial.PublicConnectorAdapter(hub, name) for name in names])
    assert registry.adapter_names() == names
    resources = await registry.list_resources()
    assert {item.adapter for item in resources} == set(names)
    descriptor = resources[0]
    snapshot = await registry.inspect(SourceRef(
        key="anchor", adapter=descriptor.adapter, resource=descriptor.resource, label=descriptor.title,
    ))
    assert snapshot.adapter == descriptor.adapter
    assert snapshot.source_key == "anchor"


async def test_public_numeric_enum_is_identical_for_both_arms(tmp_path, public):
    schemas = []
    for treatment in (False, True):
        session = make_session(tmp_path, public, treatment)
        session.phase = "monitoring"
        specs = await session.specs()
        schema = next(t["parameters"] for t in specs if t["name"] == "submit_analysis")
        schemas.append(schema)
        assert schema["$defs"]["_NumericClaim"]["properties"]["fact"]["enum"] == public["numeric_vocabulary"]
        with pytest.raises(ValueError, match="exact numeric_vocabulary"):
            await session.call("submit_analysis", {"outcome": "ignore", "recipients": [],
                "evidence_refs": [], "claims": [], "summary": "Contract test",
                "numeric_claims": [{"fact": "invented = 100", "value": 100,
                                    "unit": "USD", "evidence_refs": ["company_mcp|example"]}]})
        assert session.submission is None
    assert schemas[0] == schemas[1]


async def test_missing_owner_review_returns_actionable_steps(tmp_path, public):
    session = make_session(tmp_path, public)
    await session.specs()
    source = session.adapter.catalog[0]
    drafted = await session.call("draft_insight_card", {
        "title": "Review flow", "what_to_watch": "Current source", "why_watch": "Test approval",
        "sources": [{"key": "s", "adapter": source.adapter, "resource": source.resource,
                     "label": source.title}], "questions": ["What changed?"],
    })
    result = await session.call("request_synthetic_owner_approval", {"card_id": drafted["card"]["id"]})
    assert not result["approved"]
    assert result["next_tools"] == ["preview_investigation_report",
                                     "request_synthetic_owner_approval"]
    assert result["missing_prerequisites"] == ["preview_investigation_report"]
    assert result["next_actions"] == [
        {"tool": tool, "arguments": {"card_id": drafted["card"]["id"]}}
        for tool in result["missing_prerequisites"]]
    assert "missing" in result["reason"]
    assert session.owner_approvals == {}


@pytest.mark.parametrize("treatment", [False, True])
async def test_submission_citations_validated_without_expected_answer(tmp_path, public, treatment):
    session = make_session(tmp_path, public, treatment)
    session.phase = "monitoring"
    descriptor = session.adapter.catalog[0]
    ref = f"{descriptor.adapter}|{descriptor.resource}"
    submission = {"outcome": "ignore", "recipients": [], "evidence_refs": [ref],
                  "claims": [{"claim_type": "hypothesis", "evidence_refs": [ref],
                              "statement": "Contract validation does not prove this claim."}],
                  "numeric_claims": [], "summary": "Shared mechanical validation only."}
    with pytest.raises(ValueError, match="actually inspected"):
        await session.call("submit_analysis", submission)
    await session.adapter.inspect(SourceRef(key="s", adapter=descriptor.adapter,
                                            resource=descriptor.resource, label=descriptor.title))
    with pytest.raises(ValueError, match="top-level"):
        await session.call("submit_analysis", {**submission, "evidence_refs": []})
    with pytest.raises(ValueError, match="actually inspected"):
        await session.call("submit_analysis", {**submission, "evidence_refs": [ref + "typo"]})
    assert session.submission is None
    assert (await session.call("submit_analysis", submission))["recorded"]
    # A new period cannot reuse evidence seen only during onboarding/another period.
    session.adapter.set_period(public["periods"][0], datetime.now(timezone.utc))
    with pytest.raises(ValueError, match="actually inspected"):
        await session.call("submit_analysis", submission)


def test_real_sdk_response_usage_serializes_and_is_counted():
    response = SystemOneResponse(model="jev-1.13.0", usage=Usage(input_tokens=120, output_tokens=0), answers={})
    audit = trial.Audit()
    audit.emit("api.request", provider="jev", request_id=1)
    audit.emit("api.response", provider="jev", request_id=1, response=response, usage=response.usage)
    assert audit.events[1]["response"]["model"] == "jev-1.13.0"
    usage = trial.usage_summary(audit.events)["jev"]
    assert usage["input_tokens"] == 120
    assert usage["unknown_usage_attempts"] == 0
    assert usage["estimated_known_usage_usd"] == pytest.approx(120 * .042 / 1e6)


async def test_measured_jev_real_sdk_shape_and_error_count(monkeypatch):
    budget, audit = trial.RequestBudget(2), trial.Audit()
    response = SystemOneResponse(model="jev-1.13.0", usage=Usage(input_tokens=12, output_tokens=0), answers={})

    async def success(self, **kwargs):
        return response

    monkeypatch.setattr(trial.JevJudger, "_system_one_with_retry", success)
    judger = trial.MeasuredJev("not-a-real-key", budget, audit)
    assert await judger._system_one_with_retry(state={}, questions={}, stage="test") is response

    async def failure(self, **kwargs):
        raise RuntimeError("secret-text-must-not-enter-audit")

    monkeypatch.setattr(trial.JevJudger, "_system_one_with_retry", failure)
    with pytest.raises(RuntimeError):
        await judger._system_one_with_retry(state={}, questions={}, stage="test")
    with pytest.raises(trial.BudgetExceeded):
        await judger._system_one_with_retry(state={}, questions={}, stage="test")
    assert budget.used == 2
    assert trial.usage_summary(audit.events)["jev"]["unknown_usage_attempts"] == 1
    assert "secret-text" not in trial.canonical(audit.events)


@pytest.mark.parametrize("expression,result", [("(800-100)+(400-100)", 1000),
                                              ("(150/200)-(90/100)", -.15), ("-3*+2", -6)])
def test_shared_arithmetic(expression, result):
    assert trial.calculate(expression) == pytest.approx(result)


@pytest.mark.parametrize("expression", ["__import__('os')", "2**20", "a.b", "True", "[1,2]",
                                        "1/0", "1e999", "1+" * 501 + "1"])
def test_arithmetic_rejects_code_and_nonfinite(expression):
    with pytest.raises((ValueError, SyntaxError, ZeroDivisionError)):
        trial.calculate(expression)


def test_projection_excludes_labels_future_periods_and_owner_answers(public, tmp_path):
    public["private"] = {"outcome": "SENTINEL_PRIVATE"}
    public["periods"][2]["snapshots"] = {"SENTINEL_FUTURE": {}}
    session = make_session(tmp_path, public)
    context = trial.canonical(session.public)
    assert "SENTINEL_PRIVATE" not in context
    assert "SENTINEL_FUTURE" not in trial.canonical(session.adapter.snapshots)
    assert "owner_answers" not in context
    assert "periods" not in vars(session)
    assert "periods" not in vars(session.adapter)
    assert "snapshots" not in session.public
    altered = copy.deepcopy(public)
    altered["private"]["outcome"] = "OTHER_HIDDEN"
    altered["periods"][2]["snapshots"] = {"OTHER_FUTURE": {}}
    assert trial.agent_context(altered) == session.public


async def test_both_arms_have_same_raw_tools_context_and_calculator(tmp_path, public):
    baseline = make_session(tmp_path / "a", public, False)
    treatment = make_session(tmp_path / "b", public, True)
    a = {spec["name"]: spec for spec in await baseline.specs()}
    b = {spec["name"]: spec for spec in await treatment.specs()}
    assert all(a[name] == b[name] for name in a)
    assert baseline.public == treatment.public
    assert await baseline.call("ask_owner", {"topic": "materiality"}) == await treatment.call("ask_owner", {"topic": "materiality"})
    assert await baseline.call("calculate", {"expression": "10/4"}) == await treatment.call("calculate", {"expression": "10/4"})
    schemas = {tool.name: tool.inputSchema for tool in await treatment.server.list_tools()}
    assert b["onboard_insight_card"]["parameters"] == schemas["onboard_insight_card"]
    assert "onboard_insight_card" not in a
    with pytest.raises(ValueError, match="not available"):
        await baseline.call("onboard_insight_card", {})


@pytest.mark.parametrize("name", ["propose_insight_card", "onboard_insight_card", "draft_insight_card"])
async def test_authoring_schemas_expose_required_delivery_fields_and_mode_enums(tmp_path, public, name):
    session = make_session(tmp_path, public)
    schemas = {tool.name: tool.inputSchema for tool in await session.server.list_tools()}
    schema = schemas[name]
    properties, definitions = schema["properties"], schema["$defs"]
    delivery_array = next(item for item in properties["delivery_methods"]["anyOf"]
                          if item.get("type") == "array")
    delivery = definitions[delivery_array["items"]["$ref"].rsplit("/", 1)[1]]
    assert set(delivery["required"]) == {"key", "outcome", "label", "destination"}
    for field in ("key", "label", "destination"):
        assert delivery["properties"][field]["type"] == "string"
        assert delivery["properties"][field]["minLength"] == 1
    outcome = definitions[delivery["properties"]["outcome"]["$ref"].rsplit("/", 1)[1]]
    assert set(outcome["enum"]) == {"ignore", "investigate", "notify", "escalate", "insufficient_data"}
    for field, choices, default in (
        ("retrieval_mode", {"fixed", "expand"}, "fixed"),
        ("investigation_mode", {"none", "bounded"}, "none"),
    ):
        mode = definitions[properties[field]["$ref"].rsplit("/", 1)[1]]
        assert set(mode["enum"]) == choices
        assert properties[field]["default"] == default
    specs = {spec["name"]: spec for spec in await session.specs()}
    assert specs[name]["parameters"] == schema


async def test_draft_schema_exposes_typed_source_refs(tmp_path, public):
    session = make_session(tmp_path, public)
    schema = next(tool.inputSchema for tool in await session.server.list_tools()
                  if tool.name == "draft_insight_card")
    assert "sources" in schema["required"]
    sources = schema["properties"]["sources"]
    assert sources["type"] == "array"
    source = schema["$defs"][sources["items"]["$ref"].rsplit("/", 1)[1]]
    assert set(source["required"]) == {"key", "adapter", "resource", "label"}
    for field in source["required"]:
        assert source["properties"][field]["type"] == "string"
        assert source["properties"][field]["minLength"] == 1
    assert source["properties"]["adapter"]["pattern"] == r"^[a-z][a-z0-9_-]*$"
    assert source["properties"]["parameters"]["type"] == "object"
    assert source["properties"]["required"]["default"] is True


@pytest.mark.parametrize("wall_year", [1990, 2090])
@pytest.mark.parametrize("age_hours,outcome", [(1, "ignore"), (72, "insufficient_data")])
async def test_engine_uses_injected_clock_for_fresh_and_72_hour_sources(monkeypatch, wall_year, age_hours, outcome):
    clock = datetime(2040, 1, 1, tzinfo=timezone.utc)

    class WallClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(wall_year, 1, 1, tzinfo=tz)

    monkeypatch.setattr("signalweave.engine.datetime", WallClock)
    source = SourceRef(key="signal", adapter="company_mcp", resource="metric:signal", label="Signal")
    card = InsightCard(id="clock-regression", title="Clock regression", what_to_watch="Source signal",
                       why_watch="Check source freshness", sources=[source], max_source_age_hours=24)
    snapshot = ResourceSnapshot(
        source_key=source.key, adapter=source.adapter, resource=source.resource, title=source.label,
        captured_at=clock, source_captured_at=clock - timedelta(hours=age_hours),
        observations=[Observation(source_key=source.key, subject_id="signal", subject_label="Signal",
                                  metric="value", current=10, baseline=10, change_pct=0)],
    )
    run = await InsightEngine(OfflineJudger(), clock=lambda: clock).evaluate(card, [snapshot])
    assert run.result.outcome == outcome
    assert run.result.delivery_methods == []
    freshness = [item.statement for item in run.result.evidence if "hours old" in item.statement]
    if age_hours == 72:
        assert len(freshness) == 1
        assert "72.0 hours old; maximum is 24 hours" in freshness[0]
    else:
        assert freshness == []


async def test_clock_preserves_staleness_and_nested_source_keys(tmp_path, public):
    clock = datetime(2026, 9, 30, tzinfo=timezone.utc)
    period = copy.deepcopy(public["onboarding"])
    ref, snapshot = next(iter(period["snapshots"].items()))
    snapshot["source_captured_at"] = (datetime.fromisoformat(period["as_of"]) - timedelta(days=3)).isoformat()
    snapshot["evidence"][0]["values"]["event_at"] = snapshot["source_captured_at"]
    session = make_session(tmp_path, public)
    session.adapter.set_period(period, clock)
    adapter, resource = ref.split("|", 1)
    result = await session.adapter.inspect(SourceRef(key="caller-selected-key", adapter=adapter,
                                                     resource=resource, label="selected"))
    assert clock - result.source_captured_at == timedelta(days=3)
    assert result.captured_at == clock
    assert result.source_key == "caller-selected-key"
    assert result.evidence[0].source_key == "caller-selected-key"
    assert datetime.fromisoformat(result.evidence[0].values["event_at"]) == clock - timedelta(days=3)
    assert ref in session.adapter.inspected
    session.adapter.set_period(public["periods"][0], clock)
    assert not session.adapter.inspected


async def test_real_mcp_draft_preview_approval_roundtrip(tmp_path, public):
    # All selected resources, no probability-dependent fixture discovery shortcuts.
    public["catalog"] = public["catalog"][:1]
    session = make_session(tmp_path, public)
    await session.specs()
    descriptor = session.adapter.catalog[0]
    drafted = await session.call("draft_insight_card", {
        "title": "Offline trial", "what_to_watch": "Changes in this source",
        "why_watch": "Validate the transport contract", "watch_for": ["Source freshness"],
        "sources": [{"key": "selected", "adapter": descriptor.adapter,
                     "resource": descriptor.resource, "label": descriptor.title}],
        "decision_guidance": "Ignore unchanged evidence, otherwise investigate.",
    })
    card_id = drafted["card"]["id"]
    await session.call("get_insight_card", {"card_id": card_id})
    with pytest.raises(ValueError, match="requires"):
        await session.call("approve_insight_card", {"card_id": card_id})
    preview = await session.call("simulate_insight_card", {"card_id": card_id})
    assert preview["delivery_enabled"] is False
    decision = await session.call("request_synthetic_owner_approval", {"card_id": card_id})
    assert decision["approved"] and decision["synthetic"]
    assert decision["policy_correctness_validated"] is False
    approved = await session.call("approve_insight_card", {"card_id": card_id})
    assert approved["status"] == "approved"
    assert any(item["kind"] == "owner.approval" for item in session.adapter.audit.events)
    await session.call("ask_owner", {"topic": "metric_scope"})
    await session.call("save_notes", {"notes": "Remember the context, not old measurements."})
    assert (await session.call("finish_setup", {"card_id": card_id}))["setup_complete"]
    session.phase = "monitoring"
    result = await session.product("evaluate_insight_card", {"card_id": card_id, "idempotency_key": "offline-one"})
    assert result["result"]["evaluator"] == "offline-harness-contract-double"
    assert result["receipt"]["delivery_enabled"] is False


async def test_preview_expansion_uses_stored_fingerprint_and_edits_revoke_approval(tmp_path, public, monkeypatch):
    session = make_session(tmp_path, public)
    await session.specs()
    card = {"id": "one", "what_to_watch": "original", "sources": [{"key": "anchor"}]}

    async def product(name, arguments):
        if name == "get_insight_card":
            return copy.deepcopy(card)
        if name in {"simulate_insight_card", "preview_investigation_report"}:
            return {"status": "preview", "card": {**card, "sources": [{"key": "anchor"}, {"key": "expanded"}]}}
        raise AssertionError("unexpected tool")

    monkeypatch.setattr(session, "product", product)
    await session.call("get_insight_card", {"card_id": "one"})
    await session.call("preview_investigation_report", {"card_id": "one"})
    assert (await session.call("request_synthetic_owner_approval", {"card_id": "one"}))["approved"]
    card["what_to_watch"] = "edited"
    with pytest.raises(ValueError, match="requires"):
        await session.call("approve_insight_card", {"card_id": "one"})


async def test_responses_api_exact_model_instructions_usage_and_failure_no_retry(tmp_path, public):
    session = make_session(tmp_path, public, True)
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"message": "secret-response-not-recorded"}})

    audit, budget = trial.Audit(), trial.RequestBudget(5)
    result = await trial.luna_episode(session, key="dummy", effort="low", budget=budget,
                                     audit=audit, max_turns=5, max_tool_calls=20, max_output_tokens=100,
                                     transport=httpx.MockTransport(handle))
    assert result["status"] == "failed"
    assert len(seen) == budget.used == 1
    assert seen[0]["model"] == "gpt-5.6-luna"
    assert session.server.instructions in seen[0]["instructions"]
    assert "secret-response" not in trial.canonical(audit.events)
    usage = trial.usage_summary(audit.events)["openai"]
    assert usage["failed_attempts"] == usage["unknown_usage_attempts"] == 1


async def test_responses_api_retries_rate_limit_with_bounded_backoff(tmp_path, public, monkeypatch):
    session = make_session(tmp_path, public, False)
    session.phase = "monitoring"
    submission = {"outcome": "ignore", "recipients": [], "evidence_refs": [], "summary": "Test only"}
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        if len(seen) == 1:
            return httpx.Response(
                429,
                headers={"retry-after": "0"},
                json={"error": {"message": "rate limited"}},
            )
        return httpx.Response(200, json={
            "output": [{"type": "function_call", "name": "submit_analysis", "call_id": "call-1",
                        "arguments": json.dumps(submission)}],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        })

    monkeypatch.setattr(trial, "OPENAI_RETRY_BACKOFF_SECONDS", 0)
    audit = trial.Audit()
    result = await trial.luna_episode(
        session, key="dummy", effort="low", budget=trial.RequestBudget(3), audit=audit,
        max_turns=1, max_tool_calls=5, max_output_tokens=100,
        transport=httpx.MockTransport(handle),
    )

    assert result["status"] == "complete"
    assert len(seen) == 2
    assert trial.usage_summary(audit.events)["openai"]["unknown_usage_attempts"] == 1
    assert any(
        event.get("status_code") == 429
        for event in audit.events
        if event["kind"] == "api.error"
    )


async def test_responses_api_retries_transient_transport_and_keeps_unknown_cost(tmp_path, public, monkeypatch):
    session = make_session(tmp_path, public, False)
    session.phase = "monitoring"
    submission = {"outcome": "ignore", "recipients": [], "evidence_refs": [], "summary": "Test only"}
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        if len(seen) == 1:
            raise ssl.SSLError("transient TLS failure")
        return httpx.Response(200, json={
            "output": [{"type": "function_call", "name": "submit_analysis", "call_id": "call-1",
                        "arguments": json.dumps(submission)}],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        })

    monkeypatch.setattr(trial, "OPENAI_RETRY_BACKOFF_SECONDS", 0)
    audit = trial.Audit()
    result = await trial.luna_episode(
        session, key="dummy", effort="low", budget=trial.RequestBudget(3), audit=audit,
        max_turns=1, max_tool_calls=5, max_output_tokens=100,
        transport=httpx.MockTransport(handle),
    )

    assert result["status"] == "complete", result
    assert len(seen) == 2
    assert trial.usage_summary(audit.events)["openai"]["attempts"] == 2
    assert trial.usage_summary(audit.events)["openai"]["unknown_usage_attempts"] == 1
    assert audit.events[1]["retry_index"] == 0


async def test_successful_transport_retry_does_not_poison_followup_tool_turn(tmp_path, public, monkeypatch):
    session = make_session(tmp_path, public, False)
    seen = []

    def response_for(*calls):
        return httpx.Response(200, json={
            "output": [{"type": "function_call", "name": name, "call_id": call_id,
                        "arguments": json.dumps(arguments)} for name, call_id, arguments in calls],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        })

    def handle(request):
        seen.append(json.loads(request.content))
        if len(seen) == 1:
            raise ssl.SSLError("transient TLS failure")
        if len(seen) == 2:
            descriptor = public["catalog"][0]
            return response_for(
                ("inspect_source", "call-inspect", {"ref": f"{descriptor['adapter']}|{descriptor['resource']}"}),
                ("ask_owner", "call-owner", {"topic": "metric_scope"}),
            )
        if len(seen) == 3:
            return response_for(("save_notes", "call-notes", {"notes": "Reusable policy context."}))
        return response_for(("finish_setup", "call-finish", {"card_id": None}))

    monkeypatch.setattr(trial, "OPENAI_RETRY_BACKOFF_SECONDS", 0)
    audit = trial.Audit()
    result = await trial.luna_episode(
        session, key="dummy", effort="low", budget=trial.RequestBudget(5), audit=audit,
        max_turns=4, max_tool_calls=8, max_output_tokens=100,
        transport=httpx.MockTransport(handle),
    )

    assert result["status"] == "complete", result
    assert session.setup_complete
    assert len(seen) == 4  # failed attempt, successful retry, then three follow-up turns
    assert trial.usage_summary(audit.events)["openai"]["unknown_usage_attempts"] == 1


async def test_onboarding_continues_after_model_returns_prose_before_setup(tmp_path, public):
    session = make_session(tmp_path, public, False)
    seen = []
    descriptor = public["catalog"][0]
    ref = f"{descriptor['adapter']}|{descriptor['resource']}"

    def response_for(*calls, prose=False):
        output = []
        if prose:
            output.append({
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "I will continue onboarding."}],
            })
        output.extend(
            {"type": "function_call", "name": name, "call_id": call_id,
             "arguments": json.dumps(arguments)}
            for name, call_id, arguments in calls
        )
        return httpx.Response(200, json={
            "output": output,
            "usage": {"input_tokens": 100, "output_tokens": 20},
        })

    def handle(request):
        seen.append(json.loads(request.content))
        if len(seen) == 1:
            return response_for(prose=True)
        if len(seen) == 2:
            return response_for(
                ("inspect_source", "call-inspect", {"ref": ref}),
                ("ask_owner", "call-owner", {"topic": "metric_scope"}),
            )
        if len(seen) == 3:
            return response_for(("save_notes", "call-notes", {"notes": "Reusable policy context."}))
        return response_for(("finish_setup", "call-finish", {"card_id": None}))

    audit = trial.Audit()
    result = await trial.luna_episode(
        session, key="dummy", effort="low", budget=trial.RequestBudget(8), audit=audit,
        max_turns=2, max_tool_calls=8, max_output_tokens=100,
        transport=httpx.MockTransport(handle),
    )

    assert result["status"] == "complete"
    assert session.setup_complete
    assert len(seen) == 4
    assert [event["continuation_turn"] for event in audit.events if event["kind"] == "agent.continuation"] == [1]


async def test_responses_tool_loop_keeps_reasoning_and_notes(tmp_path, public):
    session = make_session(tmp_path, public, False)
    session.phase = "monitoring"
    submission = {"outcome": "ignore", "recipients": [], "evidence_refs": [], "summary": "Test only"}
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        if len(seen) == 1:
            output = [{"type": "reasoning", "id": "rs_1", "summary": []},
                      {"type": "function_call", "name": "save_notes", "call_id": "call_1",
                       "arguments": json.dumps({"notes": "durable context"})}]
        else:
            output = [{"type": "function_call", "name": "submit_analysis", "call_id": "call_2",
                       "arguments": json.dumps(submission)}]
        return httpx.Response(200, json={"output": output,
                                        "usage": {"input_tokens": 100, "output_tokens": 20,
                                                  "input_tokens_details": {"cached_tokens": 50}}})

    audit = trial.Audit()
    result = await trial.luna_episode(session, key="dummy", effort="low", budget=trial.RequestBudget(3),
                                     audit=audit, max_turns=3, max_tool_calls=5, max_output_tokens=100,
                                     transport=httpx.MockTransport(handle))
    assert result["status"] == "complete"
    assert session.notes == "durable context"
    assert any(item.get("type") == "reasoning" for item in seen[1]["input"])
    assert any(item.get("type") == "function_call_output" for item in seen[1]["input"])
    assert trial.usage_summary(audit.events)["openai"]["cached_input_tokens"] == 100


def test_audit_redacts_escaped_secrets_and_nested_values(tmp_path):
    secret = 'abc"secret'
    audit = trial.Audit(tmp_path / "trace.jsonl", (secret,))
    audit.emit("test", value={"nested": [secret, "prefix " + secret]})
    assert "secret" not in (tmp_path / "trace.jsonl").read_text()
    assert audit.events[0]["value"]["nested"][0] == "[REDACTED]"


def test_dotenv_parses_quotes_and_preflight_missing_key_no_file_search(monkeypatch, tmp_path, capsys):
    for key in ("OPENAI_API_KEY", "TYPESAFE_API_KEY", "TYPESAFE_API_KEY_FILE"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / "explicit.env"
    env.write_text('OPENAI_API_KEY="quoted-test-key"\n')
    key = tmp_path / "jev.key"
    key.write_text("test-jev-key")
    args = trial.parser().parse_args(["--openai-env", str(env), "--jev-key-file", str(key)])
    assert trial.credentials(args) == ("quoted-test-key", "test-jev-key")
    monkeypatch.setattr("sys.argv", ["runner", "--preflight", "--output", str(tmp_path / "out")])
    with pytest.raises(SystemExit) as caught:
        trial.main()
    assert caught.value.code == 2
    assert "Missing credential" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


async def test_exhausted_budget_keeps_every_planned_period_in_denominator(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-jev")

    async def fail(*args, **kwargs):
        kwargs["budget"].claim()
        return {"status": "failed", "error": "offline_test", "seconds": 0, "tool_calls": 0}

    monkeypatch.setattr(trial, "luna_episode", fail)
    args = trial.parser().parse_args(["--limit", "1", "--max-api-requests", "1",
                                     "--output", str(tmp_path / "new")])
    report = await trial.run_trial(args)
    assert report["status"] == "partial_or_failed"
    assert report["comparative_eligible"] is False
    assert report["budget_censored"] is True
    assert "evaluations/codex_trial_transport.py" in report["config"]["source_fingerprint"]["sha256"]
    assert "src/signalweave/engine.py" in report["config"]["source_fingerprint"]["sha256"]
    assert len(report["rows"]) == 8
    assert all(row["monitoring_denominator"] == 3 for row in report["summary"].values())
    assert all(row["exact_count"] == 0 for row in report["summary"].values())
    with pytest.raises(FileExistsError):
        await trial.run_trial(args)
    assert (args.output / "report.json").exists()


async def test_run_trial_accepts_explicit_versioned_scenarios_and_records_digest(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-jev")
    scenario = build_scenarios(split="dev")[0]

    async def fail(*args, **kwargs):
        kwargs["budget"].claim()
        return {"status": "failed", "error": "offline_test", "seconds": 0, "tool_calls": 0}

    monkeypatch.setattr(trial, "luna_episode", fail)
    args = trial.parser().parse_args(["--limit", "1", "--max-api-requests", "1",
                                      "--output", str(tmp_path / "explicit")])
    report = await trial.run_trial(args, scenarios_override=[scenario])
    assert report["config"]["fixtures"] == "explicit_versioned_scenarios"
    assert report["config"]["dataset_digest"] == trial.dataset_digest([scenario])
    assert report["config"]["selected_scenario_ids"] == [scenario["scenario_id"]]


def test_cost_counts_cold_warm_and_unknown_attempts_separately():
    events = [{"kind": "api.request", "provider": "openai", "request_id": 1},
              {"kind": "api.response", "provider": "openai", "request_id": 1,
               "usage": {"input_tokens": 1000, "output_tokens": 100,
                         "input_tokens_details": {"cached_tokens": 500}}},
              {"kind": "api.request", "provider": "jev", "request_id": 2},
              {"kind": "api.error", "provider": "jev", "request_id": 2}]
    usage = trial.usage_summary(events)
    assert usage["openai"]["estimated_known_usage_usd"] == pytest.approx(.00023)
    row = {"arm": trial.ARMS[0], "status": "failed", "seconds": 3, "usage": usage}
    report = trial.aggregate([{**row, "phase": "onboarding"}, {**row, "phase": "monitoring"}])
    assert report[trial.ARMS[0]]["cost_complete"] is False
    assert report[trial.ARMS[0]]["observed_cold_plus_warm_known_usage_usd"] == pytest.approx(.00046)


@pytest.mark.parametrize("responding_provider", ["openai", "jev"])
def test_usage_request_id_collision_does_not_hide_other_provider_unknown_cost(responding_provider):
    missing_provider = "jev" if responding_provider == "openai" else "openai"
    events = [
        {"kind": "api.request", "provider": "openai", "request_id": 1},
        {"kind": "api.request", "provider": "jev", "request_id": 1},
        {"kind": "api.response", "provider": responding_provider, "request_id": 1,
         "usage": {"input_tokens": 100, "output_tokens": 0}},
        {"kind": "api.error", "provider": missing_provider, "request_id": 1},
    ]
    usage = trial.usage_summary(events)
    known, unknown = usage[responding_provider], usage[missing_provider]
    assert known["attempts"] == unknown["attempts"] == 1
    assert known["unknown_usage_attempts"] == known["failed_attempts"] == 0
    assert known["input_tokens"] == 100
    assert known["estimated_known_usage_usd"] > 0
    assert unknown["unknown_usage_attempts"] == unknown["failed_attempts"] == 1
    assert unknown["input_tokens"] == unknown["output_tokens"] == 0
    row = {"arm": trial.ARMS[0], "phase": "monitoring", "status": "failed", "seconds": 0, "usage": usage}
    assert trial.aggregate([row])[trial.ARMS[0]]["cost_complete"] is False


@pytest.mark.parametrize("usage", [{"input_tokens": None, "output_tokens": None},
                                   {"input_tokens": -1, "output_tokens": 0},
                                   {"input_tokens": True, "output_tokens": 0},
                                   {"input_tokens": "10", "output_tokens": 0}])
def test_missing_or_invalid_token_usage_is_unknown_not_free(usage):
    audit = trial.Audit()
    audit.emit("api.request", provider="jev", request_id=1)
    audit.emit("api.response", provider="jev", request_id=1, usage=usage)
    row = trial.usage_summary(audit.events)["jev"]
    assert row["unknown_usage_attempts"] == 1
    assert row["input_tokens"] == 0


def test_common_instructions_require_both_arms_finish_and_submit():
    assert "finish_setup" in trial.COMMON_SYSTEM
    assert "submit_analysis" in trial.COMMON_SYSTEM
    assert "relevant corroborating fact is numeric" in trial.COMMON_SYSTEM


def test_signalweave_handoff_requires_human_facing_evidence_digest_without_invented_slas():
    instructions = trial.SIGNALWEAVE_BUNDLE_INSTRUCTIONS

    assert "compact evidence digest" in instructions
    assert "current and comparison values" in instructions
    assert "applicable population/coverage" in instructions
    assert "concrete next step" in instructions
    assert "never invent a freshness SLA" in instructions
    assert "A complete push-gated ignore may remain a short silent-run receipt" in instructions


async def test_final_mcp_wrapped_budget_exhaustion_disables_comparative_claims(monkeypatch, tmp_path):
    from mcp.server.fastmcp import FastMCP

    monkeypatch.setenv("OPENAI_API_KEY", "offline-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-jev")
    episodes = 0

    async def episode(session, **kwargs):
        nonlocal episodes
        episodes += 1
        session.setup_complete = True
        if episodes == 8:  # No later episode exists to notice the depleted budget.
            server = FastMCP("offline-budget-wrapper")
            budget = kwargs["budget"]

            @server.tool()
            async def bounded_request() -> dict:
                budget.claim()
                assert budget.exhausted is False  # Spending exactly the cap is permitted.
                budget.claim()  # FastMCP wraps this BudgetExceeded in ToolError.
                return {}

            await server.call_tool("bounded_request", {})
        return {"status": "complete", "seconds": 0, "tool_calls": 0}

    async def evaluation(self, name, arguments):
        assert name == "evaluate_insight_card"
        return {}  # Offline-only: skip semantic execution to isolate final-call accounting.

    monkeypatch.setattr(trial, "luna_episode", episode)
    monkeypatch.setattr(trial.ToolSession, "product", evaluation)
    args = trial.parser().parse_args(["--limit", "1", "--max-api-requests", "1",
                                     "--output", str(tmp_path / "final-call")])
    report = await trial.run_trial(args)
    assert episodes == 8
    assert all(row["status"] == "complete" for row in report["rows"][:-1])
    assert report["rows"][-1]["error"] == "ToolError"
    assert report["api_attempts"] == 1
    assert report["budget_censored"] is True
    assert report["comparative_eligible"] is False
