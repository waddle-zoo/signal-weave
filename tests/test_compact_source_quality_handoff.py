"""Source-quality snapshots survive compact MCP handoff and durable receipts."""

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from signalweave.mcp_server import (
    AGENT_HANDOFF_BYTES,
    RECEIPT_PAGE_BYTES,
    _compact_evaluation_response,
    _receipt_result_page,
)
from signalweave.models import (
    MetricDefinition,
    Observation,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceComparisonContract,
)
from tests.test_onboarding import OnboardingJevDouble, make_server, tool

SOURCE_COVERAGE = ("complete", "partial", "unknown", "partial")
SOURCE_KEYS = tuple(f"quality-source-{index}" for index in range(4))


def source_contract(index: int, coverage: str) -> ResourceContract:
    metric = f"metric_{index}"
    return ResourceContract(
        tenant_id="default",
        domain="operations",
        metric_names=[metric],
        metric_definitions=[MetricDefinition(
            key=metric,
            label=f"Metric {index}",
            description=f"Adapter-owned definition revision {index + 1}.",
            relation=f"measurements_{index}",
            aggregation="sum",
            measure_column="amount",
            time_column="event_day",
            supported_grains=["day"],
            population=f"population-{index}",
            grain="day",
            lineage=[f"definition-revision-{index + 1}"],
        )],
        comparison_contracts=[SourceComparisonContract(
            key=f"{metric}:previous-period",
            metric=metric,
            definition=f"Exact source definition revision {index + 1}.",
            population=f"population-{index}",
            unit="count",
            comparison_window="previous_period",
            coverage=coverage,
            comparable=coverage == "complete",
            detail=f"Source quality state {coverage}.",
            query_refs=[f"approved-query-{index}"],
        )],
        available_comparison_windows=["previous_period"],
        freshness_sla_hours=24,
        lineage=[f"adapter-lineage-{index}"],
        roles=["primary"],
        source_status="healthy",
        authorized=True,
    )


class QualitySnapshotFactory:
    """Offline adapter fixture with distinct catalog and per-run snapshots."""

    name = "superset"

    def __init__(self):
        self.contracts = [
            source_contract(index, coverage)
            for index, coverage in enumerate(SOURCE_COVERAGE)
        ]
        self.resources = [
            ResourceDescriptor(
                adapter=self.name,
                resource=f"dashboard:{7 + index}",
                kind="dashboard",
                title=f"Source {index}",
                source_url=f"https://example.invalid/dashboard/{7 + index}",
                contract=contract.model_copy(
                    update={
                        "comparison_contracts": [
                            contract.comparison_contracts[0].model_copy(update={
                                "coverage": "complete",
                                "comparable": True,
                                "detail": "Stable catalog definition; not this run's coverage.",
                            })
                        ]
                    },
                    deep=True,
                ),
            )
            for index, contract in enumerate(self.contracts)
        ]
        self.snapshots = {}
        self.inspect_calls = []
        epoch = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
        for index, (key, contract) in enumerate(zip(SOURCE_KEYS, self.contracts, strict=True)):
            self.snapshots[key] = ResourceSnapshot(
                source_key=key,
                adapter=self.name,
                resource=f"dashboard:{7 + index}",
                title=f"Source {index}",
                source_url=f"https://example.invalid/result/{index}",
                captured_at=epoch + timedelta(minutes=index),
                source_captured_at=(
                    None if index == 3 else epoch - timedelta(hours=index + 1)
                ),
                observations=[Observation(
                    source_key=key,
                    subject_id=f"subject-{index}",
                    subject_label=f"Metric {index}",
                    metric=f"metric_{index}",
                    unit="count",
                    current=10 + index,
                )],
                contract=contract.model_copy(deep=True),
            )

    async def list_resources(self):
        return [resource.model_copy(deep=True) for resource in self.resources]

    async def inspect(self, source):
        self.inspect_calls.append(source.key)
        return self.snapshots[source.key].model_copy(deep=True)

    def change_catalog_to_today(self):
        for index, resource in enumerate(self.resources):
            today = source_contract(index, "complete").model_copy(
                update={
                    "domain": "today-catalog",
                    "lineage": ["today-catalog-revision"],
                }
            )
            resource.contract = today


class CountingJevDouble(OnboardingJevDouble):
    def __init__(self):
        self.judge_calls = 0

    async def rank_resources(self, goal, resources):
        del goal
        return {f"{item.adapter}|{item.resource}": 0.99 for item in resources}

    async def judge(self, state, card, plan, observations):
        self.judge_calls += 1
        return await super().judge(state, card, plan, observations)


def expected_source_contracts(snapshots: list[ResourceSnapshot]) -> list[dict]:
    result = []
    for snapshot in snapshots:
        result.append({
            "source_key": snapshot.source_key,
            "adapter": snapshot.adapter,
            "resource": snapshot.resource,
            "source_url": snapshot.source_url,
            "captured_at": snapshot.captured_at.isoformat(),
            "source_captured_at": (
                snapshot.source_captured_at.isoformat()
                if snapshot.source_captured_at is not None else None
            ),
            "contract": snapshot.contract.model_dump(mode="json"),
        })
    return result


async def approved_quality_card(tmp_path):
    factory = QualitySnapshotFactory()
    judger = CountingJevDouble()
    server = make_server(tmp_path, judger=judger, catalog=factory, sqlite=True)
    draft = await tool(server, "draft_insight_card")(
        title="Source quality receipt",
        what_to_watch="A bounded quality fixture across four approved sources.",
        why_watch="Verify source definitions and freshness survive the receipt handoff.",
        decision_guidance="Record the fake provider's judgment; do not deliver a notification.",
        comparison_windows=["previous_period"],
        sources=[
            {
                "key": key,
                "adapter": factory.name,
                "resource": f"dashboard:{7 + index}",
                "label": f"Source {index}",
            }
            for index, key in enumerate(SOURCE_KEYS)
        ],
    )
    card_id = draft["card"]["id"]
    await tool(server, "review_insight_card")(card_id)
    approved = await tool(server, "approve_insight_card")(card_id)
    assert approved["status"] == "approved"
    return server, factory, judger, card_id


@pytest.mark.asyncio
async def test_approved_evaluation_receipt_keeps_exact_four_source_quality_snapshots_and_replays(
    tmp_path,
):
    server, factory, judger, card_id = await approved_quality_card(tmp_path)
    inspections_before = list(factory.inspect_calls)
    registry_snapshots = {}
    registry = server._test_runtime.sources
    registry_inspect = registry.inspect

    async def capture_inspection(source, *, authorized_tenants=None):
        snapshot = await registry_inspect(source, authorized_tenants=authorized_tenants)
        registry_snapshots[source.key] = snapshot.model_copy(deep=True)
        return snapshot

    registry.inspect = capture_inspection

    first = await tool(server, "evaluate_insight_card")(
        card_id, idempotency_key="source-quality:daily", response_mode="compact",
    )
    expected = expected_source_contracts([
        registry_snapshots[key] for key in SOURCE_KEYS
    ])
    assert first["result"]["source_contracts"] == expected
    assert [
        item["contract"]["comparison_contracts"][0]["coverage"]
        for item in first["result"]["source_contracts"]
    ] == list(SOURCE_COVERAGE)
    assert factory.inspect_calls[len(inspections_before):] == list(SOURCE_KEYS)

    receipt = server._test_runtime.decision_receipts.get_by_idempotency_key(
        "source-quality:daily"
    )
    assert receipt.result["source_contracts"] == expected

    # A later catalog revision must not replace the exact contract used by this run.
    factory.change_catalog_to_today()
    inspections_after = list(factory.inspect_calls)
    judgments_after = judger.judge_calls
    replay = await tool(server, "evaluate_insight_card")(
        card_id, idempotency_key="source-quality:daily", response_mode="compact",
    )
    assert replay["replayed"] is True
    assert replay["result"]["source_contracts"] == expected
    assert factory.inspect_calls == inspections_after
    assert judger.judge_calls == judgments_after

    page = tool(server, "get_decision_receipt")(
        receipt_id=receipt.receipt_id,
        result_path=["source_contracts"],
        offset=0,
        limit=10,
    )["result_page"]
    assert page["items"] == expected
    assert page["coverage"] == "complete_section"
    assert page["next_offset"] is None
    assert factory.inspect_calls == inspections_after


@pytest.mark.asyncio
async def test_legacy_receipt_without_source_quality_does_not_invent_today_catalog(
    tmp_path,
):
    server, factory, judger, card_id = await approved_quality_card(tmp_path)
    await tool(server, "evaluate_insight_card")(
        card_id, idempotency_key="legacy-quality", response_mode="full",
    )
    receipt = server._test_runtime.decision_receipts.get_by_idempotency_key("legacy-quality")
    legacy_result = deepcopy(receipt.result)
    legacy_result.pop("source_contracts", None)
    server._test_runtime.decision_receipts.save(
        receipt.model_copy(update={"result": legacy_result})
    )
    factory.change_catalog_to_today()
    inspections_after = list(factory.inspect_calls)
    judgments_after = judger.judge_calls

    replay = await tool(server, "evaluate_insight_card")(
        card_id, idempotency_key="legacy-quality", response_mode="compact",
    )
    assert replay["replayed"] is True
    compact_legacy_result = deepcopy(legacy_result)
    had_markdown = isinstance(compact_legacy_result.pop("report_markdown", None), str)
    assert replay["result"] == compact_legacy_result
    assert replay["report_markdown_available"] is had_markdown
    assert "source_contracts" not in replay["result"]
    full_receipt = tool(server, "get_decision_receipt")(
        receipt_id=receipt.receipt_id
    )
    assert full_receipt["result"] == legacy_result
    with pytest.raises(ValueError, match="does not exist"):
        tool(server, "get_decision_receipt")(
            receipt_id=receipt.receipt_id,
            result_path=["source_contracts"],
        )
    assert factory.inspect_calls == inspections_after
    assert judger.judge_calls == judgments_after


def test_large_source_contracts_get_first_bounded_prefix_and_lossless_32k_pages():
    source_contracts = [
        {
            "source_key": f"large-source-{index}",
            "adapter": "fixture",
            "resource": f"resource:{index}",
            "captured_at": f"2026-10-13T12:0{index}:00+00:00",
            "source_captured_at": None,
            "contract": {
                "domain": f"domain-{index}",
                "comparison_contracts": [{
                    "key": f"comparison-{index}",
                    "coverage": "partial" if index % 2 else "unknown",
                    "definition": "source-defined semantics " + "d" * 24_000,
                }],
            },
        }
        for index in range(4)
    ]
    result = {
        "card_id": "large-quality-card",
        "outcome": "investigate",
        "summary": "Keep the source contract prefix ahead of observations.",
        "source_contracts": source_contracts,
        "observations": [
            {"source_key": f"s-{index}", "metric": "events", "attributes": {"detail": "o" * 900}}
            for index in range(160)
        ],
        "evidence": [{"statement": "e" * 400} for _ in range(160)],
    }
    compact = _compact_evaluation_response({
        "result": result,
        "receipt": {"receipt_id": "large-quality-receipt", "delivery_enabled": False},
    })
    encoded = json.dumps(compact, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(encoded) <= AGENT_HANDOFF_BYTES
    assert compact["evidence_access"]["receipt_id"] == "large-quality-receipt"
    contract_coverage = compact["evidence_access"]["source_contract_coverage"]
    assert contract_coverage == {
        "result_path": ["source_contracts"],
        "total": 4,
        "included": len(compact["result"]["source_contracts"]),
        "coverage": "partial_section",
        "next_offset": len(compact["result"]["source_contracts"]),
    }
    assert 0 < contract_coverage["included"] < len(source_contracts)
    assert compact["result"]["source_contracts"] == source_contracts[:contract_coverage["included"]]
    observation_coverage = compact["evidence_access"]["observation_coverage"]
    assert observation_coverage["total"] == len(result["observations"])
    assert observation_coverage["coverage"] == "partial_section"
    assert observation_coverage["next_offset"] == observation_coverage["included"]
    result_keys = list(compact["result"])
    assert result_keys.index("source_contracts") < result_keys.index("observations")

    recovered = []
    offset = 0
    while True:
        page = _receipt_result_page(result, ["source_contracts"], offset, 100)
        page_bytes = json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        assert len(page_bytes) <= RECEIPT_PAGE_BYTES
        assert page["items"]
        assert page["oversized_item"] is None
        recovered.extend(page["items"])
        if not page["has_more"]:
            assert offset + len(page["items"]) == len(source_contracts)
            break
        assert page["coverage"] == "partial_section"
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert recovered == source_contracts
