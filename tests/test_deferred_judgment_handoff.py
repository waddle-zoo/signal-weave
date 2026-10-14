"""Oversized local judgments become receipt-backed frontier handoffs."""

import asyncio
import json
from datetime import datetime, timezone

import pytest

from signalweave.diagnostics import AnalyticalComparison, PeriodValue, SegmentPair
from signalweave.mcp_server import _deferred_observation_facts
from signalweave.models import (
    ContextFact,
    ContextSnapshot,
    InsightCard,
    InsightCardStatus,
    Observation,
    PrincipalContext,
)
from signalweave.numeric_conditions import NumericCondition
from signalweave.typesafe_adapter import JevJudger, JevPayloadError
from tests.test_onboarding import (
    OnboardingJevDouble,
    SupersetCatalogDouble,
    make_server,
    tool,
)


class NoRequestClient:
    calls = 0

    def __init__(self, **kwargs):
        del kwargs
        type(self).calls += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        del args

    async def system_one(self, **kwargs):
        del kwargs
        raise AssertionError("the oversized local judgment must not reach the SDK")


class SuccessfulRequestClient:
    calls = 0

    def __init__(self, **kwargs):
        del kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        del args

    async def system_one(self, **kwargs):
        del kwargs
        type(self).calls += 1
        return object()


class PayloadCatalog(SupersetCatalogDouble):
    def __init__(self, observation_count):
        super().__init__()
        self.observation_count = observation_count
        self.last_snapshot = None
        self.inspect_count = 0
        descriptor = self.resources[0]
        self.resources[0] = descriptor.model_copy(update={
            "contract": descriptor.contract.model_copy(update={
                "required_comparison_keys": ["growth-total"],
            }),
        })

    async def inspect(self, source):
        self.inspect_count += 1
        snapshot = await super().inspect(source)
        observations = [
            Observation(
                source_key=source.key,
                subject_id=f"row-{index:04d}",
                subject_label=f"Metric row {index}",
                metric=f"metric_{index:04d}",
                current=index + 10,
                baseline=index + 9,
                unit="USD",
                dimensions={"channel": f"channel-{index % 4}"},
                attributes={"record_id": f"record-{index:04d}"},
            )
            for index in range(self.observation_count)
        ]
        comparison = AnalyticalComparison(
            key="growth-total",
            metric="total_growth",
            definition="A complete, source-reported total.",
            population="All fictional growth records.",
            unit="USD",
            dimension="channel",
            kind="additive",
            baseline_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            baseline_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
            current_start=datetime(2026, 2, 1, tzinfo=timezone.utc),
            current_end=datetime(2026, 3, 1, tzinfo=timezone.utc),
            coverage="complete",
            disjoint_segments=True,
            comparable=True,
            required=True,
            query_refs=["query:quarterly-growth"],
            baseline_total=PeriodValue(value=100),
            current_total=PeriodValue(value=125),
            segments=[SegmentPair(
                segment="all", baseline=PeriodValue(value=100), current=PeriodValue(value=125),
            )],
        )
        snapshot = snapshot.model_copy(update={
            "observations": observations,
            "analytical_comparisons": [comparison],
            "metadata": {
                "chart_definitions": [
                    {
                        "chart_id": f"chart-{index}",
                        "query_context": {
                            "sql": f"select * from fictional_growth where chart_id = {index}",
                            "time_range": "previous_period",
                        },
                    }
                    for index in range(3)
                ],
                "opaque_connector_metadata": {"retained": [f"field-{i}" for i in range(30)]},
            },
        })
        self.last_snapshot = snapshot
        return snapshot


def payload_judger():
    NoRequestClient.calls = 0
    judger = JevJudger(
        api_key="test-only-no-network-key",
        max_payload_bytes=4_000_000,
        max_input_tokens=1_024,
        max_retries=0,
    )
    judger._client_type = NoRequestClient
    return judger


def approved_card():
    return InsightCard(
        id="deferred-card",
        title="Deferred judgment test",
        what_to_watch="Review fictional growth measurements.",
        why_watch="Keep the source facts available for the frontier agent.",
        decision_guidance="Investigate a supported increase; otherwise preserve uncertainty.",
        numeric_conditions=[NumericCondition(
            text="Growth total increased.",
            source_key="growth",
            comparison_key="growth-total",
            measurement="delta",
            unit="USD",
            threshold=0,
            comparator=">",
        )],
        sources=[{
            "key": "growth",
            "adapter": "superset",
            "resource": "dashboard:7",
            "label": "Growth overview",
            "required_comparison_keys": ["growth-total"],
        }],
        delivery_methods=[{
            "key": "owner",
            "outcome": "notify",
            "label": "Owner",
            "destination": "owner://inbox",
        }],
        status=InsightCardStatus.APPROVED,
        principal_id="test-principal",
        principal_tenant="default",
    )


def configured_server(tmp_path, observation_count=117, judger=None):
    catalog = PayloadCatalog(observation_count)
    server = make_server(
        tmp_path,
        judger=judger or payload_judger(),
        catalog=catalog,
        sqlite=True,
    )
    server._test_runtime.card_store.save_card(approved_card())
    return server, catalog


def context_snapshot():
    return ContextSnapshot(
        provider="test-context",
        version="v1",
        trust="trusted",
        facts=[ContextFact(
            fact_id="owner-context",
            subject_ref="superset|dashboard:7",
            relation="measurement_scope",
            statement="The source covers the fictional growth population.",
            provenance=["owner:test"],
        )],
    )


async def read_all_pages(server, receipt_id, path, limit=100):
    values = []
    offset = 0
    total = None
    while True:
        page = tool(server, "get_decision_receipt")(
            receipt_id=receipt_id, result_path=path, offset=offset, limit=limit,
        )["result_page"]
        total = page["total"]
        values.extend(page["items"])
        if not page["has_more"]:
            assert len(values) == total
            return values
        assert page["next_offset"] > offset
        offset = page["next_offset"]


def test_deferred_observation_facts_preserve_field_identity_nulls_and_raw_paths():
    observations = [
        {
            "source_key": "observation_facts",
            "subject_id": "0",
            "metric": "source_by_key",
            "current": None,
            "dimensions": {"metric": "current", "source_by_key": "0"},
            "attributes": {"measurement_month": "2025-04", "opaque": [1, 2]},
            "extra/metadata": {"current": 7},
        },
        {
            "source_key": "0",
            "subject_id": "source_by_key",
            "metric": "observation_facts",
            "baseline": 0,
        },
    ]
    original = json.loads(json.dumps(observations))

    facts = _deferred_observation_facts(observations)

    assert facts["record_count"] == 2
    assert facts["rows_complete"] is True
    assert facts["fields"] == sorted(set().union(*(row.keys() for row in observations)) - {"attributes"})
    first, second = facts["rows"]
    assert first["index"] == 0
    assert first["full_ref"] == ["judgment_state", "observations", "0"]
    first_values = dict(zip(facts["fields"], first["values"], strict=True))
    assert first_values["source_key"] == "observation_facts"
    assert first_values["metric"] == "source_by_key"
    assert first_values["current"] is None
    assert "current" not in first.get("missing_fields", [])
    assert first_values["extra/metadata"] == {"current": 7}
    assert "measurement_month" not in facts["fields"]
    assert facts["attributes_present_indices"] == [0]
    assert facts["attributes_path_suffix"] == ["attributes"]
    assert first["full_ref"] + facts["attributes_path_suffix"] == [
        "judgment_state", "observations", "0", "attributes",
    ]
    second_values = dict(zip(facts["fields"], second["values"], strict=True))
    assert second_values["baseline"] == 0
    assert "current" in second["missing_fields"]
    assert second["full_ref"] == ["judgment_state", "observations", "1"]
    assert observations == original


@pytest.mark.parametrize("observation_count", [117, 1_000])
async def test_overbudget_judgment_persists_complete_state_and_never_calls_sdk(
    tmp_path, observation_count,
):
    server, catalog = configured_server(tmp_path, observation_count)
    context = context_snapshot()
    response = await tool(server, "evaluate_insight_card")(
        "deferred-card",
        idempotency_key=f"deferred-{observation_count}",
        context=context,
        response_mode="full",
    )

    assert NoRequestClient.calls == 0
    assert server._test_runtime.engine.judger.metrics.request_attempts == 0
    assert response["receipt"]["status"] == "decision_deferred"
    assert response["receipt"]["outcome"] is None
    assert response["receipt"]["delivery_enabled"] is False
    assert response["receipt"]["delivery_method_keys"] == []
    assert response["card"]["id"] == "deferred-card"
    result = response["result"]
    assert result["outcome"] is None
    assert result["delivery_enabled"] is False
    assert result["delivery_methods"] == []
    assert result["judgment"]["status"] == "deferred"
    assert result["judgment"]["input_budget"]["stage"] == "judgment"
    assert result["judgment"]["input_budget"]["observed_tokens"] > 1_024
    assert result["judgment"]["provider_call_attempts"] == 0
    assert result["judgment"]["attempt_scope"] == "current_judgment"
    assert result["judgment"]["provider_call_attempted"] is False

    state = result["judgment_state"]
    assert len(state["observations"]) == observation_count
    assert len(state["evidence"]) >= observation_count
    assert state["observations"][-1]["subject_id"] == f"row-{observation_count - 1:04d}"
    assert state["analyses"][0]["comparison_key"] == "growth-total"
    assert state["numeric_conditions"][0]["status"] == "true"
    assert state["context"]["facts"][0]["fact_id"] == "owner-context"
    assert result["source_by_key"]["growth"]["metadata"]["chart_definitions"] == (
        catalog.last_snapshot.metadata["chart_definitions"]
    )
    assert result["source_by_key"]["growth"]["metadata"]["opaque_connector_metadata"] == (
        catalog.last_snapshot.metadata["opaque_connector_metadata"]
    )
    assert result["source_by_key"]["growth"]["analytical_comparisons"][0]["query_refs"] == [
        "query:quarterly-growth"
    ]
    assert result["source_contracts"][0]["contract"] == (
        result["source_by_key"]["growth"]["contract"]
    )

    durable = tool(server, "get_decision_receipt")(
        idempotency_key=f"deferred-{observation_count}"
    )
    assert durable["receipt"]["status"] == "decision_deferred"
    assert durable["result"] == result


async def test_compact_deferred_handoff_pages_exact_state_and_source_snapshots(tmp_path):
    server, catalog = configured_server(tmp_path, 117)
    response = await tool(server, "evaluate_insight_card")(
        "deferred-card", idempotency_key="deferred-pages", response_mode="compact",
    )
    assert response["result"]["judgment"]["status"] == "deferred"
    assert len(json.dumps(response, ensure_ascii=False).encode("utf-8")) < 64 * 1024
    assert "judgment_state" not in response["result"]
    assert "source_by_key" not in response["result"]
    paths = {tuple(section["path"]) for section in response["evidence_access"]["available_sections"]}
    assert ("judgment_state",) in paths
    assert ("source_by_key",) in paths
    assert response["evidence_access"]["complete"] is False
    assert response["evidence_access"]["observation_coverage"] == {
        "result_path": ["judgment_state", "observations"],
        "total": 117,
        "included": 0,
        "coverage": "partial_section",
        "next_offset": 0,
    }
    facts = response["result"]["observation_facts"]
    assert facts["record_count"] == 117
    assert facts["rows_complete"] is True
    assert len(facts["rows"]) == 117
    assert response["evidence_access"]["observation_facts"] == {
        "location": "inline_projection",
        "inline_result_path": ["observation_facts"],
        "result_path": ["judgment_state", "observations"],
        "total": 117,
        "included": 117,
        "coverage": "complete_normalized_observation_rows",
        "attributes_included": False,
        "attributes_path_suffix": ["attributes"],
        "source_coverage_asserted": False,
    }
    assert response["evidence_access"]["source_directory"] == [{
        "source_key": "growth",
        "snapshot_path": ["source_by_key", "growth"],
        "source_id": "superset|dashboard:7",
        "metadata_path": ["source_by_key", "growth", "metadata"],
        "contract_path": ["source_by_key", "growth", "contract"],
        "analytical_comparisons_path": ["source_by_key", "growth", "analytical_comparisons"],
        "observations_path": ["source_by_key", "growth", "observations"],
        "evidence_path": ["source_by_key", "growth", "evidence"],
    }]
    assert response["evidence_access"]["source_contract_coverage"]["coverage"] == "complete_section"
    assert "does not assert complete source coverage" in response["evidence_access"]["instruction"]
    assert catalog.inspect_count == 1
    assert NoRequestClient.calls == 0
    assert server._test_runtime.engine.judger.metrics.request_attempts == 0
    evidence_coverage = response["evidence_access"]["evidence_coverage"]
    assert evidence_coverage["result_path"] == ["judgment_state", "evidence"]
    assert evidence_coverage["total"] >= 117
    assert evidence_coverage["included"] == 0
    assert evidence_coverage["next_offset"] == 0

    receipt_id = response["receipt"]["receipt_id"]
    source_page = tool(server, "get_decision_receipt")(
        receipt_id=receipt_id, result_path=["source_by_key"], limit=10,
    )["result_page"]
    assert source_page["oversized_item"]["path"] == ["source_by_key", "growth"]
    full = tool(server, "get_decision_receipt")(receipt_id=receipt_id)
    stored_source = full["result"]["source_by_key"]["growth"]
    metadata_items = tool(server, "get_decision_receipt")(
        receipt_id=receipt_id,
        result_path=["source_by_key", "growth", "metadata"],
    )["result_page"]["items"]
    assert {item["key"]: item["value"] for item in metadata_items} == stored_source["metadata"]
    source_observations = await read_all_pages(
        server, receipt_id, ["source_by_key", "growth", "observations"], limit=25,
    )
    assert source_observations == stored_source["observations"]

    observations = await read_all_pages(
        server, receipt_id,
        response["evidence_access"]["observation_facts"]["result_path"], limit=25,
    )
    assert len(observations) == 117
    assert observations == full["result"]["judgment_state"]["observations"]
    fields = facts["fields"]
    assert fields == sorted(set().union(*(observation.keys() for observation in observations)) - {"attributes"})
    for index, (fact_row, raw_observation) in enumerate(zip(facts["rows"], observations, strict=True)):
        assert fact_row["index"] == index
        assert fact_row["full_ref"] == ["judgment_state", "observations", str(index)]
        assert dict(zip(fields, fact_row["values"], strict=True)) == {
            key: value for key, value in raw_observation.items() if key != "attributes"
        }
        assert index in facts["attributes_present_indices"]
        assert fact_row["full_ref"] + facts["attributes_path_suffix"] == [
            "judgment_state", "observations", str(index), "attributes",
        ]
    assert observations[-1]["subject_id"] == tool(server, "get_decision_receipt")(
        receipt_id=receipt_id,
        result_path=["judgment_state", "observations", "116", "subject_id"],
    )["result_page"]["items"][0]
    contracts = await read_all_pages(server, receipt_id, ["source_contracts"], limit=10)
    assert contracts == full["result"]["source_contracts"]
    assert contracts[0]["contract"] == full["result"]["source_by_key"]["growth"]["contract"]
    assert catalog.inspect_count == 1


async def test_compact_deferred_omits_whole_overview_when_it_cannot_fit_and_keeps_receipt_pages(tmp_path):
    server, catalog = configured_server(tmp_path, 1_000)
    response = await tool(server, "evaluate_insight_card")(
        "deferred-card", idempotency_key="deferred-large-overview", response_mode="compact",
    )

    assert len(json.dumps(response, ensure_ascii=False).encode("utf-8")) < 64 * 1024
    assert "observation_facts" not in response["result"]
    assert response["evidence_access"]["observation_facts"] == {
        "location": "receipt_only",
        "result_path": ["judgment_state", "observations"],
        "total": 1_000,
        "included": 0,
        "coverage": "not_included_within_handoff_byte_bound",
        "next_offset": 0,
    }
    assert response["card"]["decision_guidance"] == approved_card().decision_guidance
    receipt_id = response["receipt"]["receipt_id"]
    observations = await read_all_pages(
        server, receipt_id,
        response["evidence_access"]["observation_facts"]["result_path"], limit=25,
    )
    assert len(observations) == 1_000
    assert observations[-1]["subject_id"] == "row-0999"
    assert catalog.inspect_count == 1
    assert NoRequestClient.calls == 0
    assert server._test_runtime.engine.judger.metrics.request_attempts == 0


async def test_deferred_receipt_replays_without_reads_and_keeps_card_scope_and_version_guards(tmp_path):
    server, _ = configured_server(tmp_path, 117)
    registry = server._test_runtime.sources
    original_resolve = registry.resolve
    resolve_calls = 0

    async def count_resolve(*args, **kwargs):
        nonlocal resolve_calls
        resolve_calls += 1
        return await original_resolve(*args, **kwargs)

    registry.resolve = count_resolve
    first = await tool(server, "evaluate_insight_card")(
        "deferred-card", idempotency_key="deferred-replay",
    )
    after_first = resolve_calls
    replay = await tool(server, "evaluate_insight_card")(
        "deferred-card", idempotency_key="deferred-replay",
    )
    assert replay["replayed"] is True
    assert replay["result"] == first["result"]
    assert resolve_calls == after_first
    assert NoRequestClient.calls == 0
    with pytest.raises(ValueError, match="decision is not complete"):
        tool(server, "record_decision_feedback")(
            idempotency_key="deferred-replay", kind="incomplete",
        )

    card = server._test_runtime.card_store.get_card("deferred-card")
    server._test_runtime.card_store.save_card(card.model_copy(update={"version": 2}))
    with pytest.raises(ValueError, match="different card, actor, version, or context"):
        await tool(server, "evaluate_insight_card")(
            "deferred-card", idempotency_key="deferred-replay",
        )

    server._test_runtime.card_store.save_card(
        server._test_runtime.card_store.get_card("deferred-card").model_copy(
            update={"principal_tenant": "other-tenant"}
        )
    )
    with pytest.raises(ValueError, match="outside the authenticated principal tenant"):
        tool(server, "get_decision_receipt")(
            receipt_id=first["receipt"]["receipt_id"],
            result_path=["source_by_key", "growth", "metadata", "chart_definitions"],
        )


async def test_draft_and_nonpayload_errors_do_not_become_deferred(tmp_path):
    server, _ = configured_server(tmp_path, 1_000, judger=OnboardingJevDouble())
    card = server._test_runtime.card_store.get_card("deferred-card")
    server._test_runtime.card_store.save_card(card.model_copy(update={"status": InsightCardStatus.DRAFT}))
    with pytest.raises(ValueError, match="draft"):
        await tool(server, "evaluate_insight_card")(
            "deferred-card", idempotency_key="draft-does-not-read",
        )
    assert server._test_runtime.decision_receipts.get_by_idempotency_key("draft-does-not-read") is None

    class BrokenJudger(OnboardingJevDouble):
        async def judge(self, state, card, plan, observations):
            del state, card, plan, observations
            raise RuntimeError("unexpected judgment failure")

    server._test_runtime.card_store.save_card(
        server._test_runtime.card_store.get_card("deferred-card").model_copy(
            update={"status": InsightCardStatus.APPROVED}
        )
    )
    server._test_runtime.engine.judger = BrokenJudger()
    with pytest.raises(RuntimeError, match="unexpected judgment failure"):
        await tool(server, "evaluate_insight_card")(
            "deferred-card", idempotency_key="nonpayload-failure",
        )
    failed = tool(server, "get_decision_receipt")(idempotency_key="nonpayload-failure")
    assert failed["receipt"]["status"] == "failed"
    assert failed["result"]["error"] == "RuntimeError: unexpected judgment failure"


async def test_ordinary_engine_call_still_raises_budget_error_with_prepared_handoff(tmp_path):
    server, _ = configured_server(tmp_path, 117)
    runtime = server._test_runtime
    card = runtime.card_store.get_card("deferred-card")
    resources = await runtime.sources.resolve(
        card.sources, authorized_tenants=["default"]
    )
    with pytest.raises(JevPayloadError) as raised:
        await runtime.engine.evaluate(
            card,
            resources=resources,
            principal=PrincipalContext(principal_id="test-principal", tenant_id="default"),
        )
    assert raised.value.provider_call_attempts == 0
    assert raised.value.prepared_handoff["materials"].state["observations"]
    assert raised.value.prepared_handoff["resources"][0].metadata


async def test_deferred_handoff_reports_prior_judgment_requests_without_claiming_a_result(tmp_path):
    class AttemptThenBudgetJevJudger(JevJudger):
        def __init__(self):
            super().__init__(
                api_key="test-only-no-network-key",
                max_retries=0,
                max_input_tokens=1_024,
            )
            self._client_type = SuccessfulRequestClient

        async def judge(self, state, card, plan, observations):
            del state, card, plan, observations
            await asyncio.create_task(
                self._system_one_with_retry(
                    state={"prior_role_check": "already-attempted"},
                    questions={"evidence-role": {
                        "type": "noul",
                        "instructions": "Classify this already prepared evidence role.",
                    }},
                    stage="judgment",
                )
            )
            raise JevPayloadError(
                stage="judgment",
                observed_bytes=50_000,
                budget_bytes=4_000_000,
                observed_tokens=13_000,
                budget_tokens=12_000,
            )

    SuccessfulRequestClient.calls = 0
    judger = AttemptThenBudgetJevJudger()
    server, _ = configured_server(tmp_path, 1, judger=judger)
    response = await tool(server, "evaluate_insight_card")(
        "deferred-card", idempotency_key="attempted-before-deferral",
    )

    judgment = response["result"]["judgment"]
    assert SuccessfulRequestClient.calls == 1
    assert judgment["provider_call_attempts"] == 1
    assert judgment["attempt_scope"] == "current_judgment"
    assert judgment["provider_call_attempted"] is True
    assert response["result"]["outcome"] is None
    assert response["receipt"]["outcome"] is None
    assert "probabilities" not in response["result"]
    assert judgment["status"] == "deferred"


async def test_concurrent_engine_judgments_attribute_attempts_to_their_own_context(tmp_path):
    class SignalingRequestClient:
        attempt_started = None

        def __init__(self, **kwargs):
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            del args

        async def system_one(self, **kwargs):
            del kwargs
            type(self).attempt_started.set()
            await asyncio.sleep(0)
            return object()

    class ConcurrentBudgetJevJudger(JevJudger):
        def __init__(self):
            super().__init__(
                api_key="test-only-no-network-key",
                max_retries=0,
                max_input_tokens=1_024,
            )
            self._client_type = SignalingRequestClient
            self.attempt_started = asyncio.Event()
            SignalingRequestClient.attempt_started = self.attempt_started

        async def judge(self, state, card, plan, observations):
            del card, plan, observations
            fact_id = state["context"]["facts"][0]["fact_id"]
            if fact_id == "with-request":
                await asyncio.create_task(
                    self._system_one_with_retry(
                        state={"diagnostic": "prior evidence role"},
                        questions={"evidence-role": {
                            "type": "noul",
                            "instructions": "Classify this evidence role.",
                        }},
                        stage="judgment",
                    )
                )
            else:
                await self.attempt_started.wait()
            raise JevPayloadError(
                stage="judgment",
                observed_bytes=50_000,
                budget_bytes=4_000_000,
                observed_tokens=13_000,
                budget_tokens=12_000,
            )

    def context_with_id(fact_id):
        return ContextSnapshot(
            provider="test-context",
            version="v1",
            trust="trusted",
            facts=[ContextFact(
                fact_id=fact_id,
                subject_ref="superset|dashboard:7",
                relation="measurement_scope",
                statement="The source covers the fictional growth population.",
                provenance=["owner:test"],
            )],
        )

    judger = ConcurrentBudgetJevJudger()
    server, _ = configured_server(tmp_path, 1, judger=judger)
    runtime = server._test_runtime
    card = runtime.card_store.get_card("deferred-card")
    resources = await runtime.sources.resolve(
        card.sources, authorized_tenants=["default"]
    )

    async def evaluate_with(fact_id):
        with pytest.raises(JevPayloadError) as raised:
            await runtime.engine.evaluate(
                card,
                resources=resources,
                context_override=context_with_id(fact_id),
                principal=PrincipalContext(
                    principal_id="test-principal", tenant_id="default"
                ),
            )
        assert judger._active_request_attempts.get() is None
        return raised.value.provider_call_attempts

    with_request, without_request = await asyncio.gather(
        evaluate_with("with-request"), evaluate_with("without-request")
    )
    assert with_request == 1
    assert without_request == 0
    assert judger.metrics.request_attempts == 1


async def test_bounded_card_keeps_existing_decision_path(tmp_path):
    class CountingJudger(OnboardingJevDouble):
        def __init__(self):
            self.calls = 0

        async def judge(self, state, card, plan, observations):
            self.calls += 1
            return await super().judge(state, card, plan, observations)

    judger = CountingJudger()
    server, _ = configured_server(tmp_path, 1, judger=judger)
    result = await tool(server, "evaluate_insight_card")(
        "deferred-card", idempotency_key="bounded-card",
    )
    assert result["receipt"]["status"] == "delivery_disabled"
    assert result["result"]["outcome"] == "notify"
    assert "judgment" not in result["result"]
    assert judger.calls == 1
