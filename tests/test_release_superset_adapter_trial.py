from __future__ import annotations

import subprocess
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from evaluations.release_superset_adapter_trial import (
    CATALOG_DASHBOARD_ID,
    CERTIFIED_BINARY_SHA256,
    CERTIFIED_MCP_PROTOCOL_VERSION,
    CERTIFIED_SOURCE_SHA256,
    FIXTURE_PASSWORD,
    FIXTURE_TOKEN,
    FIXTURE_USERNAME,
    MAIN_DASHBOARD_ID,
    MAX_REAL_JEV_ATTEMPTS,
    WIDE_CHART_ID,
    JevRequestProxy,
    SupersetHTTPFixture,
    _evaluation_diagnostics,
    _read_evaluation_receipt_pages,
    _read_health_output,
    _read_receipt_list_pages,
    build_chart_cases,
)
from signalweave.models import SourceRef
from signalweave.superset_adapter import SupersetAdapter
from signalweave.superset_client import SupersetClient


@pytest.fixture
def fixture() -> SupersetHTTPFixture:
    return SupersetHTTPFixture()


@pytest.mark.asyncio
async def test_fixture_serves_login_catalog_pagination_and_saved_query_context(fixture):
    transport = httpx.ASGITransport(app=fixture.app)
    async with httpx.AsyncClient(base_url="http://fixture.test", transport=transport) as client:
        health = await client.get("/health")
        login = await client.post(
            "/api/v1/security/login",
            json={
                "username": FIXTURE_USERNAME,
                "password": FIXTURE_PASSWORD,
                "provider": "db",
                "refresh": True,
            },
        )
        headers = {"authorization": f"Bearer {FIXTURE_TOKEN}"}
        first = await client.get(
            "/api/v1/dashboard/", params={"page": 0, "page_size": 1}, headers=headers
        )
        second = await client.get(
            "/api/v1/dashboard/", params={"page": 1, "page_size": 1}, headers=headers
        )
        saved_chart = await client.get("/api/v1/chart/311", headers=headers)

    assert health.json()["status"] == "healthy"
    assert login.json()["access_token"] == FIXTURE_TOKEN
    assert [item["id"] for item in first.json()["result"]] == [int(MAIN_DASHBOARD_ID)]
    assert [item["id"] for item in second.json()["result"]] == [int(CATALOG_DASHBOARD_ID)]
    assert first.json()["count"] == second.json()["count"] == 2
    assert saved_chart.json()["result"]["query_context"]["queries"][0]["row_limit"] == 999999


@pytest.mark.asyncio
async def test_superset_client_and_adapter_extract_all_fixture_chart_shapes(fixture):
    transport = httpx.ASGITransport(app=fixture.app)
    client = SupersetClient(
        "http://fixture.test",
        username=FIXTURE_USERNAME,
        password=FIXTURE_PASSWORD,
        transport=transport,
    )
    adapter = SupersetAdapter(client, tenant_id="release-superset-fixture")

    snapshot = await adapter.inspect(
        SourceRef(
            key="dashboard-matrix",
            adapter="superset",
            resource=f"dashboard:{MAIN_DASHBOARD_ID}",
            label="Release telemetry dashboard",
        )
    )

    charts = {item["id"]: item for item in snapshot.metadata["charts"]}
    assert len(charts) == 12
    assert charts[WIDE_CHART_ID]["result_row_count"] == 400
    assert len(
        [obs for obs in snapshot.observations if obs.subject_id.startswith(f"{WIDE_CHART_ID}:")]
    ) == 400
    assert charts["303"]["cache_status"] == "mixed"
    assert charts["303"]["data_scope"] == "dashboard_scoped"
    assert charts["311"]["data_scope"] == "chart_query_fallback"
    assert charts["307"]["viz_type"] == "custom_unknown_visualization"
    assert charts["307"]["semantic_status"] == "extracted"
    assert charts["308"]["result_row_count"] == 2
    assert charts["309"]["result_row_count"] == 2
    assert charts["310"]["semantic_status"] == "no_data"
    assert charts["311"]["semantic_status"] == "extracted"
    assert charts["306"]["result_row_count"] == 4
    null_chart_values = {
        obs.current
        for obs in snapshot.observations
        if obs.subject_id.startswith("306:")
    }
    assert null_chart_values == {0.0, 77.0}
    assert snapshot.contract.available_comparison_windows == []
    assert snapshot.analytical_comparisons == []
    assert snapshot.contract.comparison_contracts == []
    assert "fixture-cache-key-must-not-cross-adapter" not in snapshot.model_dump_json()

    data_requests = [item for item in fixture.requests if item["path"].endswith("/data/")]
    assert len(data_requests) == 12
    assert all(item["dashboard_id"] == MAIN_DASHBOARD_ID for item in data_requests)
    fallback_posts = [
        item
        for item in fixture.requests
        if item["method"] == "POST" and item["path"] == "/api/v1/chart/data"
    ]
    assert len(fallback_posts) == 1
    assert fallback_posts[0]["chart_id"] == "311"
    assert fallback_posts[0]["result_format"] == "json"
    assert fallback_posts[0]["result_type"] == "full"
    assert fallback_posts[0]["force"] is False
    assert fallback_posts[0]["query_limits"] == [{"row_limit": 10000, "series_limit": 0}]


@pytest.mark.asyncio
async def test_chart_scope_uses_saved_chart_definition_without_invented_comparisons(fixture):
    transport = httpx.ASGITransport(app=fixture.app)
    client = SupersetClient(
        "http://fixture.test",
        username=FIXTURE_USERNAME,
        password=FIXTURE_PASSWORD,
        transport=transport,
    )
    adapter = SupersetAdapter(client, tenant_id="release-superset-fixture")

    snapshot = await adapter.inspect(
        SourceRef(
            key="wide-chart",
            adapter="superset",
            resource=f"chart:{WIDE_CHART_ID}",
            label="Wide cohort events table",
        )
    )

    assert len(snapshot.observations) == 400
    assert snapshot.metadata["result_row_count"] == 400
    assert snapshot.metadata["semantic_status"] == "extracted"
    assert snapshot.contract.available_comparison_windows == []
    assert snapshot.analytical_comparisons == []
    query_posts = [
        item
        for item in fixture.requests
        if item["method"] == "POST" and item["path"] == "/api/v1/chart/data"
    ]
    assert len(query_posts) == 1
    assert query_posts[0]["chart_id"] == WIDE_CHART_ID
    assert query_posts[0]["query_limits"] == [{"row_limit": 500, "series_limit": 0}]


def test_fixture_matrix_contains_twelve_named_chart_and_data_variants():
    cases = build_chart_cases()

    assert len(cases) == 12
    assert len({item["viz_type"] for item in cases}) >= 9
    assert len(next(item for item in cases if item["id"] == WIDE_CHART_ID)["data"]) == 400
    assert next(item for item in cases if item["id"] == "303")["cached"] == [True, False]
    assert next(item for item in cases if item["id"] == "311")["query_context"]["force"] is True
    assert next(item for item in cases if item["id"] == "308")["data"].keys() == {"records"}
    assert next(item for item in cases if item["id"] == "309")["data"].keys() == {"columns", "data"}


def test_trial_pins_the_current_certified_candidate_not_the_superseded_binary():
    assert CERTIFIED_BINARY_SHA256 == (
        "6abe5f0e292a688a30c139f917e98cd6635bb4b6bb974597f23e3edfcda9d7b5"
    )
    assert CERTIFIED_SOURCE_SHA256 == (
        "9460d2e8e08a3e06de7309cf6c8d554b17043074d8fa9fe7fbdcee972c1298e2"
    )
    assert CERTIFIED_MCP_PROTOCOL_VERSION == "2025-11-25"
    assert MAX_REAL_JEV_ATTEMPTS == 1


def test_evaluation_diagnostics_use_typed_telemetry_and_preserve_source_scope():
    diagnostics = _evaluation_diagnostics(
        {
            "response_mode": "compact",
            "details_available": True,
            "result": {
                "outcome": "investigate",
                "confidence": 0.7,
                "probabilities": {"ignore": 0.2, "investigate": 0.7},
                "summary": "Synthetic result",
                "rationale": "Synthetic rationale",
                "telemetry": {"source_count": 1, "observation_count": 400},
                "source_keys": ["superset|dashboard:41"],
                "observations": [{"current": 10}],
                "evidence": [],
                "evidence_findings": [],
                "analyses": [],
                "retrieval": {
                    "candidate_count": 1,
                    "selected_sources": [
                        {"adapter": "superset", "resource": "dashboard:41"}
                    ],
                },
                "question_results": [],
                "watch_results": [],
            },
        }
    )

    assert diagnostics["response_mode"] == "compact"
    assert diagnostics["source_count"] == 1
    assert diagnostics["source_keys_count"] == 1
    assert diagnostics["observation_count"] == 1
    assert diagnostics["selected_sources"] == [
        {"adapter": "superset", "resource": "dashboard:41"}
    ]


def test_evaluation_diagnostics_keep_separated_optional_judgments():
    watch = {"key": "watch_0", "status": "unknown", "probability": .5,
             "probabilities": {"present": .4, "absent": .1, "unknown": .5}}
    question = {"key": "question_0", "status": "unknown", "probability": .3}
    response = {"result": {"outcome": "ignore"}, "optional_policy_diagnostics": {
        "values": {"watch_results": [watch], "question_results": [question]},
    }}
    diagnostics = _evaluation_diagnostics(response)
    assert diagnostics["watch_results"] == [watch]
    assert diagnostics["question_results"] == [question]
    assert diagnostics["outcome"] == "ignore"


def test_health_json_reads_the_cli_healthy_field_and_mode():
    report = _read_health_output(
        subprocess.CompletedProcess(
            args=["signalweave", "health"],
            returncode=0,
            stdout='{"healthy":true,"mode":"offline_and_live_source","messages":[]}',
            stderr="",
        )
    )

    assert report["healthy"] is True
    assert report["mode"] == "offline_and_live_source"
    assert report["exit_code"] == 0


@pytest.mark.asyncio
async def test_jev_proxy_rejects_attempt_after_the_one_call_budget():
    proxy = JevRequestProxy()
    proxy.requests.append({"attempt": 1})
    app = Starlette(routes=[Route("/jev", proxy.handle, methods=["POST"])])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(base_url="http://proxy.test", transport=transport) as client:
        response = await client.post("/jev", json={"state": {"synthetic": True}})

    assert response.status_code == 429
    assert response.json() == {"error": "trial_request_budget_exhausted"}
    assert proxy.rejected_for_budget == 1
    assert proxy.max_attempts == 1
    assert len(proxy.requests) == 1


class _ReceiptPagesStub:
    """Offline MCP-shaped receipt fixture; it does not invoke the native binary."""

    def __init__(self, sections, *, byte_budget=48_000):
        self.sections = sections
        self.byte_budget = byte_budget
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        assert name == "get_decision_receipt"
        path = arguments["result_path"]
        values = self.sections[path[0]]
        offset = arguments["offset"]
        limit = arguments["limit"]
        items = values[offset : offset + limit]
        next_offset = offset + len(items)
        page = {
            "path": path,
            "kind": "list",
            "offset": offset,
            "total": len(values),
            "items": items,
            "has_more": next_offset < len(values),
            "next_offset": next_offset if next_offset < len(values) else None,
            "oversized_item": None,
            "byte_budget": self.byte_budget,
        }
        return SimpleNamespace(
            isError=False,
            structuredContent={"status": "found", "result_page": page},
            content=[],
        )


@pytest.mark.asyncio
async def test_receipt_pager_consumes_complete_list_and_retains_exact_tail_only():
    items = [{"index": index, "value": index * 3} for index in range(205)]
    session = _ReceiptPagesStub({"evidence": items})

    summary = await _read_receipt_list_pages(
        session,
        receipt_id="fixture-receipt",
        result_path=["evidence"],
        expected_count=205,
    )

    assert [call[1]["offset"] for call in session.calls] == [0, 100, 200]
    assert all(call[1]["limit"] == 100 for call in session.calls)
    assert summary["complete"] is True
    assert summary["consumed_item_count"] == summary["reported_total"] == 205
    assert summary["page_count"] == 3
    assert summary["total_page_json_bytes"] > 0
    assert summary["total_response_json_bytes"] >= summary["total_page_json_bytes"]
    assert summary["exact_tail_item"] == items[-1]
    assert len(summary["ordered_items_sha256"]) == 64


@pytest.mark.asyncio
async def test_receipt_page_summary_reads_full_400_observations_and_evidence():
    observations = [
        {"subject_id": f"312:segment-{index:03d}:events", "current": 100 + index % 37}
        for index in range(400)
    ]
    evidence = [{"evidence_id": f"fixture-{index:03d}", "value": index} for index in range(402)]
    session = _ReceiptPagesStub({"observations": observations, "evidence": evidence})
    evaluation = {
        "receipt": {"receipt_id": "fixture-receipt"},
        "evidence_access": {
            "coverage": "not_included_in_handoff",
            "complete": False,
            "tool": "get_decision_receipt",
            "available_sections": [
                {"path": ["observations"], "count": 400},
                {"path": ["evidence"], "count": 402},
            ],
        },
    }

    summary = await _read_evaluation_receipt_pages(
        session, evaluation, expected_observations=400
    )

    assert summary["status"] == "complete"
    assert summary["evidence_access_advertised"] is True
    assert summary["source_or_model_calls_from_paging"] == 0
    assert summary["raw_pages_retained"] is False
    assert summary["sections"]["observations"]["consumed_item_count"] == 400
    assert summary["sections"]["observations"]["page_count"] == 4
    assert summary["sections"]["observations"]["exact_tail_item"] == observations[-1]
    assert summary["sections"]["evidence"]["consumed_item_count"] == 402
    assert summary["sections"]["evidence"]["page_count"] == 5
    assert summary["sections"]["evidence"]["exact_tail_item"] == evidence[-1]
    assert len(session.calls) == 9


@pytest.mark.asyncio
async def test_receipt_pager_rejects_a_page_that_exceeds_its_byte_budget():
    session = _ReceiptPagesStub({"evidence": [{"value": "synthetic"}]}, byte_budget=1)

    with pytest.raises(ValueError, match="declared byte budget"):
        await _read_receipt_list_pages(
            session,
            receipt_id="fixture-receipt",
            result_path=["evidence"],
        )
