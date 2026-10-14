from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from evaluations.native_superset_card_journey import (
    BUSINESS_QUESTIONS,
    COMMON_INSTRUCTIONS,
    DATA_READ_TOOLS,
    DISCOVERY_TOOLS,
    MAX_DATA_READS,
    MAX_EPISODE_TOOL_CALLS,
    MAX_EPISODE_TURNS,
    MAX_PAIRED_REPORT_WORDS,
    MAX_PAIRED_SNAPSHOT_BYTES,
    MAX_RECEIPT_PAGE_CALLS,
    MAX_RECEIPT_PATH_DEPTH,
    MONITOR_INSTRUCTIONS,
    MONITOR_TOOLS,
    PAIRED_POLICY_MODES,
    PAIRED_REPETITIONS,
    SETUP_TOOLS,
    SHARED_SOURCE_TOOLS,
    CardJourneySession,
    PairedSourceSnapshot,
    _owner_approval,
    _run_episode,
    _source_budget_summary,
    build_actor_prompt,
    build_paired_prompt,
    capture_paired_source_snapshot,
    card_panel,
    compare_paired_source_snapshots,
    helper_source_snapshots_by_key,
    helper_source_snapshots_from_audit,
    instructions_for,
    load_installed_skill,
    native_source_snapshots_for_comparison,
    run,
    skill_path,
    source_tool_snapshot_parity_from_events,
)
from signalweave.models import SourceRef
from signalweave.superset_adapter import SupersetAdapter
from signalweave.superset_client import SupersetClient


class NativeTools:
    def __init__(self, names):
        self.names = names

    async def list_tools(self):
        return [
            SimpleNamespace(name=name, description=name, inputSchema={"type": "object"})
            for name in self.names
        ]


@pytest.mark.asyncio
async def test_baseline_and_treatment_share_identical_superset_tool_contracts():
    names = set(SETUP_TOOLS) | set(MONITOR_TOOLS) | {"approve_insight_card", "simulate_insight_card"}
    baseline = CardJourneySession(None, stage="baseline")
    setup = CardJourneySession(None, NativeTools(names), stage="setup")
    baseline_specs, setup_specs = await baseline.specs(), await setup.specs()
    common_baseline = {s["name"]: s for s in baseline_specs if s["name"] in SHARED_SOURCE_TOOLS}
    common_setup = {s["name"]: s for s in setup_specs if s["name"] in SHARED_SOURCE_TOOLS}
    assert common_setup == common_baseline
    assert set(common_baseline) == SHARED_SOURCE_TOOLS
    assert "approve_insight_card" not in {s["name"] for s in setup_specs}
    assert "simulate_insight_card" not in {s["name"] for s in setup_specs}


@pytest.mark.asyncio
async def test_onboarding_and_monitor_tool_surfaces_are_separate_and_default_profile_bounded():
    native = NativeTools(set(SETUP_TOOLS) | set(MONITOR_TOOLS) | {
        "approve_insight_card", "simulate_insight_card", "preview_investigation_report",
    })
    setup_names = {spec["name"] for spec in await CardJourneySession(None, native, stage="setup").specs()}
    monitor_names = {spec["name"] for spec in await CardJourneySession(None, native, stage="monitor").specs()}
    assert SETUP_TOOLS <= setup_names
    assert "approve_insight_card" not in setup_names
    assert "evaluate_insight_card" not in setup_names
    assert MONITOR_TOOLS <= monitor_names
    assert "approve_insight_card" not in monitor_names
    assert "simulate_insight_card" not in setup_names | monitor_names
    assert "preview_investigation_report" not in setup_names | monitor_names


@pytest.mark.asyncio
async def test_discovery_calls_do_not_consume_the_data_read_budget(monkeypatch):
    async def fake_parent_call(self, name, arguments):
        return {"tool": name}

    monkeypatch.setattr(
        "evaluations.native_superset_card_journey.ReportSession.call", fake_parent_call
    )
    session = CardJourneySession(None, stage="setup", max_data_reads=3)
    for _ in range(12):
        await session.call("find_dashboards", {"query": ""})
    for _ in range(12):
        await session.call("search_catalog", {"query": "online"})

    for name in ("read_dashboard", "read_chart_rows", "inspect_resource"):
        await session.call(name, {})

    assert DISCOVERY_TOOLS == {"find_dashboards", "search_catalog"}
    assert DATA_READ_TOOLS == {"read_dashboard", "read_chart_rows", "inspect_resource"}
    assert session.discovery_calls == 24
    assert session.discovery_calls_by_tool == {"find_dashboards": 12, "search_catalog": 12}
    assert session.data_reads == 3
    assert session.data_reads_by_tool == {
        "read_dashboard": 1,
        "read_chart_rows": 1,
        "inspect_resource": 1,
    }
    summary = _source_budget_summary(session)
    assert summary["discovery_calls"] == 24
    assert summary["data_read_calls"] == 3
    assert summary["data_read_cap"] == 3
    with pytest.raises(ValueError, match="data_read_budget_exhausted"):
        await session.call("read_dashboard", {})


@pytest.mark.asyncio
async def test_all_arms_keep_the_same_sixty_data_read_cap_and_episode_limits(monkeypatch):
    assert MAX_DATA_READS == 60
    assert MAX_EPISODE_TURNS == 20
    assert MAX_EPISODE_TOOL_CALLS == 60
    native = NativeTools(SETUP_TOOLS | MONITOR_TOOLS)
    sessions = [
        CardJourneySession(None, stage="baseline"),
        CardJourneySession(None, native, stage="setup"),
        CardJourneySession(None, native, stage="monitor"),
    ]
    assert {session.max_data_reads for session in sessions} == {MAX_DATA_READS}
    assert all(_source_budget_summary(session)["data_read_cap"] == MAX_DATA_READS for session in sessions)

    observed_limits = []

    async def fake_codex_episode(session, **kwargs):
        observed_limits.append((kwargs["max_turns"], kwargs["max_tool_calls"]))
        return {"status": "complete"}

    monkeypatch.setattr("evaluations.native_superset_card_journey.codex_episode", fake_codex_episode)
    for session in sessions:
        await _run_episode(
            session,
            audit=SimpleNamespace(episode=None),
            stage=session.stage,
            prompt={},
            skill="---\nname: signalweave\n---\n",
        )
    assert observed_limits == [(20, 60)] * 3


def test_three_questions_are_live_evidence_prompts_without_expected_classes_or_thresholds():
    assert len(BUSINESS_QUESTIONS) == 3
    actor_prompt = build_actor_prompt("Owner definitions and policy supplied for this trial.")
    text = str(actor_prompt)
    assert all(question in text for question in BUSINESS_QUESTIONS)
    assert "expected_outcome" not in text
    assert "ground_truth" not in text
    assert "case_label" not in text
    assert "10%" not in text


def test_baseline_can_browse_the_catalog_with_an_empty_dashboard_query():
    instructions = instructions_for(
        "baseline", "---\nname: signalweave\ndescription: test\n---\n"
    )
    assert "find_dashboards with an empty query" in instructions
    assert "instead of repeating title synonyms" in instructions


@pytest.mark.asyncio
async def test_paired_arms_have_identical_shared_tools_and_replay_one_snapshot(monkeypatch):
    snapshot = PairedSourceSnapshot(
        dashboards={"7": {"title": "Revenue", "metadata": {"charts": []}}},
        charts={"9": {"chart_id": "9", "title": "Revenue by month", "rows": [
            {"month": "2026-08", "revenue": 20},
            {"month": "2026-09", "revenue": 12},
        ]}},
        resources=[{"resource": "dashboard:7", "title": "Revenue"}],
        manifest={"snapshot_sha256": "a" * 64, "captured_at_started": "t0", "captured_at_finished": "t1"},
    )
    async def unexpected_live_call(self, name, arguments):
        raise AssertionError(f"snapshot replay must not call live adapter for {name}")

    monkeypatch.setattr("evaluations.native_superset_card_journey.ReportSession.call", unexpected_live_call)
    baseline = CardJourneySession(None, stage="paired-baseline", source_snapshot=snapshot)
    treatment = CardJourneySession(
        None, NativeTools(MONITOR_TOOLS), stage="paired-treatment", source_snapshot=snapshot
    )
    baseline_specs = {item["name"]: item for item in await baseline.specs()}
    treatment_specs = {item["name"]: item for item in await treatment.specs()}
    assert {name: baseline_specs[name] for name in SHARED_SOURCE_TOOLS} == {
        name: treatment_specs[name] for name in SHARED_SOURCE_TOOLS
    }

    first = await baseline.call("read_chart_rows", {"id": "chart:9", "offset": 0, "limit": 1})
    second = await treatment.call("read_chart_rows", {"id": "9", "offset": 0, "limit": 1})
    assert first == second
    assert first["rows"] == [{"month": "2026-08", "revenue": 20}]
    assert first["next_offset"] == 1
    second["rows"][0]["revenue"] = -1
    assert (await baseline.call("read_dashboard", {"id": "7"}))["title"] == "Revenue"
    assert snapshot.call("read_chart_rows", {"id": "9", "limit": 2})["rows"][0]["revenue"] == 20
    assert baseline.data_reads == 2
    assert treatment.data_reads == 1


def test_paired_prompt_gives_both_arms_the_same_card_notes_questions_and_snapshot():
    card = {"id": "card-1", "numeric_conditions": [], "sources": [{"key": "primary"}]}
    review = {"readiness_status": "ready_for_approval"}
    snapshot = {
        "snapshot_sha256": "b" * 64,
        "captured_at_started": "request-start",
        "captured_at_finished": "request-finish",
    }
    baseline = build_paired_prompt(
        owner_context="Owner-defined reporting context.", card=card, review=review,
        owner_notes="Owner selected these source meanings.", snapshot=snapshot, repeat=1,
    )
    treatment = build_paired_prompt(
        owner_context="Owner-defined reporting context.", card=card, review=review,
        owner_notes="Owner selected these source meanings.", snapshot=snapshot, repeat=1,
        policy_mode="skill_guided_deferred", idempotency_key="run-1",
    )
    repeat_two = build_paired_prompt(
        owner_context="Owner-defined reporting context.", card=card, review=review,
        owner_notes="Owner selected these source meanings.", snapshot=snapshot, repeat=2,
    )
    for field in ("owner_context", "reviewed_card", "source_review", "owner_notes", "source_snapshot"):
        assert baseline[field] == treatment[field]
    assert all(question in baseline["request"] for question in BUSINESS_QUESTIONS)
    assert treatment["paired_policy_mode"] == "skill_guided_deferred"
    assert treatment["new_idempotency_key"] == "run-1"
    assert "paired_policy_mode" not in baseline
    assert baseline["source_snapshot"] == repeat_two["source_snapshot"]
    assert all(question in repeat_two["request"] for question in BUSINESS_QUESTIONS)
    assert "expected_outcome" not in str(baseline)
    assert baseline["source_snapshot"]["timestamps_are_query_capture_times_not_warehouse_as_of"] is True
    assert PAIRED_REPETITIONS == 2
    assert PAIRED_POLICY_MODES == ("original_policy", "skill_guided_deferred")


def test_paired_treatment_instructions_are_conditional_and_never_promote_deferred_to_outcome():
    skill = "---\nname: signalweave\n---\n"
    original = instructions_for("paired-treatment-original_policy", skill)
    deferred = instructions_for("paired-treatment-skill_guided_deferred", skill)
    assert "captured Superset source-response snapshot" in original
    assert "do not consume deferred receipt pages in this mode" in original
    assert "observation_facts" in deferred
    assert "only a specific omitted contract, quality detail, or observation" in deferred
    assert "do not exhaustively fetch" in deferred
    assert "root-level evidence_access" in deferred
    assert "Include source_by_key, source_contracts" not in deferred
    assert "Page each advertised result_path" not in deferred
    assert "They are not a typed policy outcome" not in deferred
    assert "no typed policy outcome" in deferred
    assert "use one only when source evidence and owner policy support it" in deferred
    assert "at most 300 words" in deferred
    assert "at most 300 words" in instructions_for("paired-baseline", skill)


def test_deferred_card_panel_preserves_absence_of_judgment_and_probabilities():
    panel = card_panel({
        "receipt": {"receipt_id": "receipt-1", "status": "decision_deferred", "outcome": None},
        "result": {
            "outcome": None,
            "probabilities": {"notify": 0.9},
            "judgment": {"status": "deferred", "input_budget": {"observed_tokens": 50152}},
            "source_keys": ["primary"],
            "numeric_conditions": [],
        },
        "evidence_access": {"source_snapshot_coverage": {"complete": False}},
    })
    assert panel["receipt_status"] == "decision_deferred"
    assert panel["judgment_status"] == "deferred"
    assert panel["outcome"] is None
    assert panel["probabilities"] is None
    assert panel["input_budget"] == {"observed_tokens": 50152}
    assert panel["numeric_conditions"] == []
    assert panel["evidence_access"]["source_snapshot_coverage"]["complete"] is False
    failed = card_panel({
        "receipt": {"status": "failed", "outcome": "insufficient_data"},
        "result": {"error": "JevPayloadError", "outcome": "insufficient_data"},
    })
    assert failed["judgment_status"] == "failed_no_judgment"
    assert failed["outcome"] is None
    assert failed["probabilities"] is None


def _resource_snapshot(*, captured_at, sales=12, chart_sql="select sales", contract_version="v1"):
    return {
        "source_key": "primary",
        "adapter": "superset",
        "resource": "dashboard:7",
        "title": "Sales dashboard",
        "description": "Approved sales source",
        "observations": [{
            "source_key": "primary", "metric": "sales", "current": sales,
            "captured_at": captured_at,
        }],
        "analytical_comparisons": [],
        "evidence": [{"statement": "Sales observed", "values": {"sales": sales}}],
        "metadata": {"charts": [{"id": "9", "query_definition": chart_sql}], "captured_at": captured_at},
        "error": None,
        "source_url": "https://superset.local/dashboard/7",
        "captured_at": captured_at,
        "source_captured_at": None,
        "contract": {
            "version": contract_version,
            "grain": "month",
            "available_comparison_windows": ["previous_month"],
        },
    }


def _page_from_saved_result(result, path, offset, limit):
    value = result
    for part in path:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isascii() and part.isdecimal() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise AssertionError(f"invalid nested receipt path: {path}")
    kind = "list" if isinstance(value, list) else "object" if isinstance(value, dict) else "scalar"
    entries = list(value.items()) if kind == "object" else value if kind == "list" else [value]
    page = {
        "path": path, "kind": kind, "offset": offset, "total": len(entries),
        "items": [], "has_more": False, "next_offset": None,
        "oversized_item": None,
    }
    for index in range(offset, min(len(entries), offset + limit)):
        entry = {"key": entries[index][0], "value": entries[index][1]} if kind == "object" else entries[index]
        candidate = {**page, "items": [*page["items"], entry]}
        if len(json.dumps(candidate, separators=(",", ":")).encode()) > 31 * 1024:
            if not page["items"]:
                child = entries[index][0] if kind == "object" else str(index)
                page["oversized_item"] = {
                    "index": index,
                    "path": path if kind == "scalar" else [*path, child],
                }
            break
        page["items"].append(entry)
    next_offset = offset + len(page["items"])
    page["has_more"] = next_offset < len(entries)
    page["next_offset"] = next_offset if page["has_more"] else None
    page["section_complete"] = offset == 0 and next_offset == len(entries) and page["oversized_item"] is None
    page["coverage"] = "complete_section" if page["section_complete"] else "partial_section"
    page["byte_budget"] = 32 * 1024
    return page


def test_source_snapshot_digests_ignore_capture_times_but_compare_business_and_definition_fields():
    helper = _resource_snapshot(captured_at="helper-time")
    native = _resource_snapshot(captured_at="native-time")
    equal = compare_paired_source_snapshots(
        {"primary": helper}, {"primary": native}, native_status="available_from_deferred_receipt"
    )
    assert equal["status"] == "equal"
    assert equal["business_data_status"] == "equal"
    assert equal["source_definition_status"] == "equal"
    assert equal["per_source"]["primary"]["helper_digests"] == equal["per_source"]["primary"]["native_digests"]
    assert equal["capture_times_excluded_from_digests"] == ["captured_at", "source_captured_at"]
    assert equal["atomic_warehouse_snapshot_or_total_source_cost_claim"] is False
    assert "raw saved-chart query params are not compared" in equal["source_definition_limit"]

    changed_data = compare_paired_source_snapshots(
        {"primary": helper}, {"primary": _resource_snapshot(captured_at="later", sales=11)},
        native_status="available_from_deferred_receipt",
    )
    assert changed_data["status"] == "different"
    assert changed_data["business_data_status"] == "different"
    assert changed_data["source_definition_status"] == "equal"
    assert changed_data["per_source"]["primary"]["business_data_fields"]["observations"] == "different"
    assert changed_data["per_source"]["primary"]["business_data_fields"]["evidence"] == "different"
    assert changed_data["per_source"]["primary"]["business_data_fields"]["analytical_comparisons"] == "equal"
    assert changed_data["per_source"]["primary"]["business_data_mismatch_paths"] == {
        "observations": {"paths": ["/observations/0/current"], "truncated": False},
        "evidence": {"paths": ["/evidence/0/values/sales"], "truncated": False},
    }

    changed_definition = compare_paired_source_snapshots(
        {"primary": helper},
        {"primary": _resource_snapshot(captured_at="later", chart_sql="select net_sales")},
        native_status="available_from_deferred_receipt",
    )
    assert changed_definition["business_data_status"] == "equal"
    assert changed_definition["source_definition_status"] == "different"
    assert changed_definition["per_source"]["primary"]["source_definition_fields"]["metadata"] == "different"
    assert changed_definition["per_source"]["primary"]["source_definition_fields"]["contract"] == "equal"
    assert changed_definition["per_source"]["primary"]["source_definition_mismatch_paths"] == {
        "metadata": {
            "paths": ["/metadata/charts/0/query_definition"],
            "truncated": False,
        },
    }

    changed_contract = _resource_snapshot(captured_at="later")
    changed_contract["contract"]["available_comparison_windows"] = ["previous_week"]
    contract_diff = compare_paired_source_snapshots(
        {"primary": helper}, {"primary": changed_contract},
        native_status="available_from_deferred_receipt",
    )
    assert contract_diff["status"] == "different"
    assert contract_diff["source_definition_status"] == "different"
    assert contract_diff["per_source"]["primary"]["source_definition_mismatch_paths"] == {
        "contract": {
            "paths": ["/contract/available_comparison_windows/0"],
            "truncated": False,
        },
    }


def test_missing_native_source_material_is_unverified_not_assumed_equal():
    result = compare_paired_source_snapshots(
        {"primary": _resource_snapshot(captured_at="helper")}, None,
        native_status="not_exposed_for_non_deferred_result",
    )
    assert result["status"] == "unverified"
    assert "business_data_status" not in result
    assert result["helper_snapshot_is_frozen_but_native_evaluation_uses_separate_live_reads"] is True


def test_helper_snapshots_are_joined_using_card_alias_and_approved_dashboard_scope():
    snapshot = PairedSourceSnapshot(
        dashboards={"7": _resource_snapshot(captured_at="helper")},
        charts={}, resources=[], manifest={},
    )
    result = helper_source_snapshots_by_key(snapshot, {"sources": [{
        "key": "primary", "resource": "dashboard:7",
    }]})
    assert result == {"primary": snapshot.dashboards["7"]}
    assert helper_source_snapshots_by_key(snapshot, {"sources": [{
        "key": "other", "resource": "dashboard:8",
    }]}) == {}


def test_posthoc_helper_snapshots_require_matching_source_scope_and_stable_replays(tmp_path):
    snapshot = _resource_snapshot(captured_at="request-one")
    events = [
        {"kind": "tool.result", "episode": "paired-baseline", "name": "read_dashboard", "result": snapshot},
        {"kind": "tool.result", "episode": "paired-baseline", "name": "read_dashboard", "result": {
            **snapshot, "captured_at": "request-two",
        }},
        {"kind": "tool.result", "episode": "paired-treatment-skill_guided_deferred", "name": "read_dashboard", "result": {
            **snapshot, "observations": [{"metric": "ignored-treatment-event"}],
        }},
    ]
    path = tmp_path / "audit.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    sources, status, issue, counts = helper_source_snapshots_from_audit(
        path, [{"key": "primary", "resource": "dashboard:7"}],
    )
    assert status == "available"
    assert issue is None
    assert counts == {"primary": 2}
    assert sources["primary"]["captured_at"] == "request-one"

    conflicting = dict(snapshot, observations=[{"metric": "changed"}])
    path.write_text("\n".join(json.dumps(event) for event in (
        events[0],
        {"kind": "tool.result", "episode": "paired-baseline", "name": "read_dashboard", "result": conflicting},
    )) + "\n", encoding="utf-8")
    sources, status, issue, _ = helper_source_snapshots_from_audit(
        path, [{"key": "primary", "resource": "dashboard:7"}],
    )
    assert status == "conflicting"
    assert issue == {"reason": "replayed_helper_snapshot_digest_changed", "source_key": "primary"}


def test_paired_agent_source_parity_includes_contracts_and_quality_metadata():
    snapshot = _resource_snapshot(captured_at="shared")
    snapshot["metadata"]["data_quality"] = {
        "status": "partial", "warnings": ["baseline period is absent"],
    }
    snapshot["contract"].update({
        "population": "orders", "available_comparison_windows": ["previous_month"],
    })
    events = [
        {
            "kind": "tool.result", "episode": episode,
            "name": "read_dashboard", "result": copy.deepcopy(snapshot),
        }
        for episode in (
            "paired-baseline",
            "paired-treatment-original_policy",
            "paired-treatment-skill_guided_deferred",
        )
    ]
    parity = source_tool_snapshot_parity_from_events(
        events, [{"key": "primary", "resource": "dashboard:7"}],
        expected_modes=PAIRED_POLICY_MODES,
    )
    assert parity["status"] == "equal"
    assert parity["catalog_contract_and_metadata_quality_are_included"] is True
    for mode in PAIRED_POLICY_MODES:
        assert parity["per_mode"][mode]["per_source"]["primary"]["status"] == "equal"

    changed = copy.deepcopy(snapshot)
    changed["captured_at"] = "new-capture-time"
    changed["metadata"]["data_quality"]["warnings"] = ["comparison window is unknown"]
    changed["contract"]["available_comparison_windows"] = ["previous_week"]
    events[-1]["result"] = changed
    mismatch = source_tool_snapshot_parity_from_events(
        events, [{"key": "primary", "resource": "dashboard:7"}],
        expected_modes=PAIRED_POLICY_MODES,
    )
    source = mismatch["per_mode"]["skill_guided_deferred"]["per_source"]["primary"]
    assert mismatch["status"] == "different"
    assert source["business_data_fields"]["observations"] == "equal"
    assert source["source_definition_mismatch_paths"] == {
        "metadata": {
            "paths": ["/metadata/data_quality/warnings/0"],
            "truncated": False,
        },
        "contract": {
            "paths": ["/contract/available_comparison_windows/0"],
            "truncated": False,
        },
    }


@pytest.mark.asyncio
async def test_deferred_receipt_pages_reassemble_only_snapshot_fields_under_real_page_shape():
    resource = _resource_snapshot(captured_at="native")
    resource["observations"] = [
        {
            "source_key": "primary", "metric": f"metric-{index}", "current": index,
            "attributes": {"context": "x" * 1800},
        }
        for index in range(80)
    ]
    resource["metadata"] = {
        "chart_definitions": [
            {"chart": f"chart-{index}", "sql": f"SELECT {index} AS value " + "x" * 6000}
            for index in range(12)
        ],
        "opaque_connector_metadata": {"nested": {"definition": "d" * 9000}},
        "captured_at": "native-time",
    }
    full_result = {"source_by_key": {"primary": resource}}

    class FakeNative:
        def __init__(self):
            self.calls = []

        async def call_tool(self, name, arguments):
            assert name == "get_decision_receipt"
            assert arguments["limit"] == 100
            assert len(arguments["result_path"]) <= MAX_RECEIPT_PATH_DEPTH
            self.calls.append(arguments)
            return [], {
                "status": "found",
                "receipt": {
                    "receipt_id": "receipt-1",
                    "idempotency_key": "run-1",
                },
                "result_page": _page_from_saved_result(
                    full_result,
                    arguments["result_path"], arguments["offset"], arguments["limit"]
                ),
            }

    native = FakeNative()
    evaluation = {
        "receipt": {"receipt_id": "receipt-1", "status": "decision_deferred"},
        "result": {"judgment": {"status": "deferred"}},
    }
    sources, status, calls, issue = await native_source_snapshots_for_comparison(
        native, evaluation, idempotency_key="run-1",
    )
    assert sources == {"primary": {
        key: value for key, value in resource.items()
        if key in {
            "source_key", "adapter", "resource", "title", "description", "observations",
            "analytical_comparisons", "evidence", "metadata", "error", "source_url", "contract",
        }
    }}
    assert status == "available_from_deferred_receipt"
    assert issue is None
    assert 1 < calls < MAX_RECEIPT_PAGE_CALLS
    assert len(native.calls) == calls
    assert all(call["idempotency_key"] == "run-1" for call in native.calls)
    assert any(call["result_path"] == ["source_by_key", "primary", "metadata", "chart_definitions"] for call in native.calls)
    assert any(call["result_path"] == ["source_by_key", "primary", "observations"] for call in native.calls)
    helper = copy.deepcopy(resource)
    helper["captured_at"] = "helper-time"
    helper["metadata"]["captured_at"] = "helper-time"
    parity = compare_paired_source_snapshots(
        {"primary": helper}, sources, native_status=status, receipt_page_calls=calls,
    )
    assert parity["business_data_status"] == "equal"
    assert parity["source_definition_status"] == "equal"


@pytest.mark.asyncio
async def test_oversized_scalar_reports_exact_unverified_path_without_fabricating_value():
    resource = _resource_snapshot(captured_at="native")
    resource["source_url"] = "x" * (40 * 1024)
    full_result = {"source_by_key": {"primary": resource}}

    class FakeNative:
        async def call_tool(self, name, arguments):
            page = _page_from_saved_result(
                full_result,
                arguments["result_path"], arguments["offset"], arguments["limit"],
            )
            return [], {
                "status": "found",
                "receipt": {"receipt_id": "receipt-1", "idempotency_key": "run-1"},
                "result_page": page,
            }

    sources, status, calls, issue = await native_source_snapshots_for_comparison(
        FakeNative(),
        {"receipt": {"receipt_id": "receipt-1", "status": "decision_deferred"},
         "result": {"judgment": {"status": "deferred"}}},
        idempotency_key="run-1",
    )
    assert sources is None
    assert status == "unverified_receipt_source_snapshot"
    assert calls <= MAX_RECEIPT_PAGE_CALLS
    assert issue == {
        "reason": "oversized_scalar_unreadable",
        "path": ["source_by_key", "primary", "source_url"],
    }


@pytest.mark.asyncio
async def test_paired_reports_are_rejected_above_300_words_and_accept_exact_limit(monkeypatch):
    calls = []

    async def save_report(self, name, arguments):
        calls.append(arguments)
        self.submission = arguments
        return {"saved": True}

    monkeypatch.setattr("evaluations.native_superset_card_journey.ReportSession.call", save_report)
    session = CardJourneySession(None, stage="paired-baseline", max_report_words=MAX_PAIRED_REPORT_WORDS)
    with pytest.raises(ValueError, match="report_word_limit_exceeded: 301 words"):
        await session.call("submit_report", {"report": "word " * 301, "evidence_refs": ["dashboard:7"]})
    assert calls == []
    with pytest.raises(ValueError, match="source_references_required"):
        await session.call("submit_report", {"report": "Evidence-backed report", "evidence_refs": []})
    await session.call("submit_report", {"report": "word " * 300, "evidence_refs": ["dashboard:7"]})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_production_superset_adapter_capture_preserves_registry_contracts_and_quality():
    requests = []
    dashboard_metadata = {
        "id": "7",
        "dashboard_title": "Sales dashboard",
        "description": "approved source",
        "url": "https://superset.local/dashboard/7",
        "roles": ["approved-source"],
        "available_comparison_windows": ["previous_month"],
        "position_json": {
            "CHART-9": {
                "type": "CHART",
                "meta": {"chartId": 9, "sliceName": "Monthly sales", "viz_type": "table"},
            },
        },
    }
    chart_metadata = {
        "id": "9",
        "slice_name": "Monthly sales",
        "viz_type": "table",
        "url": "https://superset.local/chart/9",
        "params": {
            "datasource": "17__table",
            "metrics": ["net_sales"],
            "granularity_sqla": "month",
            "time_range": "Last 2 months",
        },
    }

    async def handler(request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/v1/dashboard/7":
            return httpx.Response(200, json={"result": dashboard_metadata})
        if request.url.path == "/api/v1/chart/9":
            return httpx.Response(200, json={"result": chart_metadata})
        if request.url.path == "/api/v1/chart/9/data/":
            return httpx.Response(200, json={
                "result": [{
                    "data": [{"month": "2026-09", "net_sales": 12}],
                    "is_cached": False,
                }],
                "dashboard_filters": {"period": "default"},
            })
        if request.url.path == "/api/v1/chart/data":
            return httpx.Response(200, json={
                "result": [{
                    "data": [{"month": "2026-09", "net_sales": 12}],
                    "is_cached": False,
                }],
            })
        raise AssertionError(f"unexpected offline Superset request: {request.method} {request.url.path}")

    client = SupersetClient(
        "https://superset.local", transport=httpx.MockTransport(handler),
    )
    adapter = SupersetAdapter(client, tenant_id="local")
    card = {"sources": [{
        "key": "primary", "adapter": "superset", "resource": "dashboard:7", "label": "Sales",
        "parameters": {"chart_ids": ["9"]},
    }]}
    source = SourceRef.model_validate(card["sources"][0])
    raw_adapter_snapshot = (await adapter.inspect(source)).model_dump(mode="json")
    with pytest.raises(ValueError, match="paired_snapshot_data_read_budget_exhausted"):
        await capture_paired_source_snapshot(adapter, card, max_data_reads=1)
    snapshot = await capture_paired_source_snapshot(adapter, card, max_data_reads=2)
    assert snapshot.manifest["dashboard_count"] == 1
    assert snapshot.manifest["chart_query_count"] == 1
    assert snapshot.manifest["data_read_calls"] == 2
    assert snapshot.manifest["snapshot_payload_bytes"] <= MAX_PAIRED_SNAPSHOT_BYTES
    assert snapshot.manifest["snapshot_payload_byte_cap"] == MAX_PAIRED_SNAPSHOT_BYTES
    assert snapshot.manifest["capture_is_atomic"] is False
    assert snapshot.manifest["timestamps_are_query_capture_times_not_warehouse_as_of"] is True
    assert snapshot.manifest["source_snapshot_capture_method"].startswith("production SourceRegistry.resolve")
    assert snapshot.manifest["source_snapshot_sha256_by_key"]["primary"]
    assert snapshot.manifest["superset_http_attempts"] == 7
    assert snapshot.manifest["superset_http_request_counts_by_path"] == {
        "/api/v1/dashboard/7": 3,
        "/api/v1/chart/9": 2,
        "/api/v1/chart/9/data/": 1,
        "/api/v1/chart/data": 1,
    }
    captured = snapshot.dashboards["7"]
    assert captured["metadata"]["signalweave_resolution"] == {
        "authorized": True, "reason": "authorized",
    }
    assert captured["metadata"]["data_quality"]["status"] == "partial"
    assert captured["metadata"]["data_quality"]["missing_baseline_chart_ids"] == ["9"]
    assert captured["metadata"]["charts"][0]["cache_status"] == "uncached"
    assert captured["contract"]["domain"] == "bi"
    assert captured["contract"]["population"] == ""
    assert captured["contract"]["grain"] == ""
    assert captured["contract"]["available_comparison_windows"] == ["previous_month"]
    assert captured["contract"]["roles"] == ["approved-source"]

    old_capture_comparison = compare_paired_source_snapshots(
        {"primary": raw_adapter_snapshot}, {"primary": captured},
        native_status="captured_by_source_registry",
    )
    old_paths = old_capture_comparison["per_source"]["primary"]["source_definition_mismatch_paths"]
    assert old_capture_comparison["source_definition_status"] == "different"
    assert old_paths == {
        "metadata": {"paths": ["/metadata/signalweave_resolution"], "truncated": False},
        "contract": {"paths": ["/contract/roles/0"], "truncated": False},
    }

    baseline = CardJourneySession(None, stage="paired-baseline", source_snapshot=snapshot)
    treatment = CardJourneySession(None, stage="paired-treatment", source_snapshot=snapshot)
    baseline_result = await baseline.call("read_dashboard", {"id": "7"})
    treatment_result = await treatment.call("read_dashboard", {"id": "dashboard:7"})
    assert baseline_result == treatment_result == captured
    assert baseline.data_reads == treatment.data_reads == 1
    assert snapshot.manifest["superset_http_attempts"] == 7
    assert snapshot.call("find_dashboards", {"query": "sales"})["total_count"] == 1
    rows = snapshot.call("read_chart_rows", {"id": "chart:9", "limit": 10})
    assert rows["rows"] == [{"month": "2026-09", "net_sales": 12}]
    assert rows["coverage"] == "all_returned_query_rows"


def test_historical_monitor_prompt_contract_remains_unchanged():
    assert instructions_for("monitor", "skill") == (
        COMMON_INSTRUCTIONS + "\n\nInstalled SignalWeave skill (verbatim):\n<signalweave-skill>\n"
        "skill\n</signalweave-skill>\n\n" + MONITOR_INSTRUCTIONS
    )
    assert MAX_PAIRED_REPORT_WORDS == 300


def test_skill_is_read_from_installed_user_scope_and_supplied_verbatim_to_both_arms(tmp_path):
    path = skill_path(tmp_path)
    path.parent.mkdir(parents=True)
    skill = "---\nname: signalweave\ndescription: trial skill\n---\nUse exact sources.\n"
    path.write_text(skill, encoding="utf-8")
    loaded, digest = load_installed_skill(tmp_path)
    assert loaded == skill
    assert digest == hashlib.sha256(skill.encode()).hexdigest()
    assert skill in instructions_for("baseline", loaded)
    assert skill in instructions_for("setup", loaded)
    assert skill in instructions_for("monitor", loaded)


def test_missing_or_wrong_installed_skill_fails_closed(tmp_path):
    with pytest.raises(RuntimeError, match="did not install"):
        load_installed_skill(tmp_path)
    path = skill_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("---\nname: other\n---\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="frontmatter"):
        load_installed_skill(tmp_path)


@pytest.mark.asyncio
async def test_owner_approval_requires_interactive_confirmation_and_reason(monkeypatch):
    class Native:
        calls = []

        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return [], {"status": "approved"}

    native = Native()
    session = CardJourneySession(None, native, stage="setup")
    session.card = {
        "id": "draft-1",
        "retrieval_mode": "fixed",
        "investigation_mode": "none",
        "sources": [{"key": "primary"}],
    }
    session.review = {"readiness_status": "ready_for_approval"}
    monkeypatch.setattr("evaluations.native_superset_card_journey.sys.stdin", SimpleNamespace(isatty=lambda: False))
    result = await _owner_approval(native, session, "superset")
    assert result["status"] == "awaiting_owner"
    assert native.calls == []


@pytest.mark.asyncio
async def test_owner_approval_does_not_acknowledge_dynamic_scope_or_oversized_cards(monkeypatch):
    class Native:
        calls = []

        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return [], {"status": "approved"}

    monkeypatch.setattr("evaluations.native_superset_card_journey.sys.stdin", SimpleNamespace(isatty=lambda: True))
    native = Native()
    session = CardJourneySession(None, native, stage="setup")
    session.card = {
        "id": "dynamic-draft",
        "retrieval_mode": "expand",
        "investigation_mode": "none",
        "sources": [{"key": "primary"}],
    }
    session.review = {"readiness_status": "ready_for_approval"}
    result = await _owner_approval(native, session, "superset")
    assert result["status"] == "not_approved"
    assert "dynamic scope" in result["reason"]
    assert native.calls == []


@pytest.mark.asyncio
async def test_trial_does_not_start_without_explicit_execute_flag():
    with pytest.raises(SystemExit, match="No provider calls"):
        await run(SimpleNamespace(execute=False))
