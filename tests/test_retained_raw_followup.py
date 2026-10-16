import asyncio
import json
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from evaluations import retained_raw_followup as followup
from evaluations.raw_superset_tools import RawSupersetTools
from evaluations.raw_superset_workflow import REPORT_NATIVE, REPORT_RULES, ReportEpisode


def _published_profiles():
    data = followup.MANIFEST.parent
    v2 = json.loads((data / "raw-northstar-workflow-v2-summary.json").read_text())
    onboarding = json.loads((data / "raw-northstar-onboarding-summary.json").read_text())
    monthly = v2["recorded_source_excerpt"]
    daily = onboarding["daily_source_profile"]
    source_urls = {entry["resource"].split(":", 1)[1]: entry["source_url"]
                   for entry in v2["native_decision"]["source_contracts"]}
    return {
        "1": {"chart_id": "1", "query_definition": monthly["query_definition"],
              "columns": monthly["columns"], "source_url": source_urls["1"]},
        "10": {"chart_id": "10", "query_definition": daily["query_definition"],
               "columns": daily["columns"], "source_url": source_urls["10"]},
    }


def _prior_captures():
    return {chart_id: {"query_definition_sha256": followup.json_digest(item["query_definition"]),
                       "columns": item["columns"]}
            for chart_id, item in _published_profiles().items()}


def _profile(chart_id):
    item = _published_profiles()[str(chart_id)]
    return {**item, "returned_rows_sha256": ("a" if str(chart_id) == "1" else "b") * 64,
            "returned_rows_fingerprint_encoding": followup.ROW_FINGERPRINT_ENCODING,
            "query_scope": {"kind": "saved_chart_query"}}


def _source_state():
    return {chart_id: followup.source_profile_identity(_profile(chart_id), chart_id, _prior_captures())
            for chart_id in followup.SOURCE_ASSETS}


def _native_inspection(chart_id):
    item = _published_profiles()[str(chart_id)]
    params = json.loads(item["query_definition"]["params"])
    selected = {key: params[key] for key in (
        "metrics", "groupby", "granularity_sqla", "time_grain_sqla", "time_range",
        "adhoc_filters", "row_limit", "all_columns",
    ) if key in params}
    return {"adapter": "superset", "resource": f"chart:{chart_id}",
            "source_url": item["source_url"], "error": None,
            "metadata": {"chart_id": str(chart_id), "result_columns": item["columns"],
                         "saved_query_definition": {"source_chart_id": str(chart_id),
                                                     "status": "available", "parameters": selected}}}


class SourceStub:
    def __init__(self):
        self.telemetry = {"logical_tool_calls": 0, "chart_query_http_requests": 0}

    async def specs(self):
        return [{"name": name, "description": "", "parameters": {}}
                for name in followup.BI_TOOLS]

    async def call(self, name, args):
        self.telemetry["logical_tool_calls"] += 1
        chart_id = str(args.get("id", ""))
        if name == "profile_saved_chart":
            self.telemetry["chart_query_http_requests"] += 1
            return _profile(chart_id)
        if name == "read_chart_rows":
            return {**_profile(chart_id), "rows": [{"channel": "Online"}]}
        if name == "aggregate_chart_rows":
            return {"chart_id": chart_id, "rows": [{"channel": "Online"}],
                    "source_provenance": _profile(chart_id)}
        return {"name": name}


class NativeStub:
    def __init__(self, *, budget=None, audit=None, state=None):
        self.calls = []
        self.budget, self.audit, self.state = budget, audit, state if state is not None else {}

    async def list_tools(self):
        return [SimpleNamespace(name=name, description="", inputSchema={})
                for name in REPORT_NATIVE]

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        if name == "inspect_resource":
            return [], _native_inspection(args["resource"].split(":", 1)[1])
        if name == "get_insight_card":
            manifest = json.loads(followup.MANIFEST.read_text())
            return [], _approved_card(manifest)
        if name == "evaluate_insight_card":
            if self.budget is not None:
                self.budget.claim()
            if self.audit is not None:
                self.audit.emit("api.request", provider="jev", request_id=1)
                self.audit.emit("api.response", provider="jev", request_id=1,
                                usage={"input_tokens": 31, "output_tokens": 7})
            receipt = {"receipt_id": "receipt-followup-offline",
                       "idempotency_key": args["idempotency_key"],
                       "card_id": args["card_id"], "card_version": 1,
                       "status": "delivery_disabled", "delivery_enabled": False,
                       "delivery_mode": "shadow", "created_at": datetime.now(timezone.utc).isoformat()}
            self.state["receipt"] = receipt
            return [], {"replayed": False, "result": {"outcome": "investigate"},
                        "receipt": dict(receipt)}
        if name == "get_decision_receipt":
            if args.get("receipt_id") == "receipt-134632e7393b45ce87792b6008abbf9c":
                return [], _old_receipt()
            receipt = self.state.get("receipt")
            if receipt and (args.get("receipt_id") == receipt["receipt_id"]
                            or args.get("idempotency_key") == receipt["idempotency_key"]):
                return [], {"status": "found", "receipt": dict(receipt)}
            raise RuntimeError("unknown decision receipt")
        return [], {"status": "found"}


def _approved_card(manifest):
    return {"id": manifest["prior"]["card_id"], "version": 1, "status": "approved",
            "title": "Approved offline card", "what_to_watch": "Refresh source evidence",
            "why_watch": "Keep the saved policy intact", "delivery_methods": []}


def _old_receipt():
    prior = json.loads(followup.MANIFEST.read_text())["prior"]
    return {"status": "found", "receipt": {"receipt_id": prior["receipt_id"],
            "idempotency_key": prior["run_key"], "card_id": prior["card_id"],
            "card_version": prior["card_version"], "delivery_enabled": False}}


def _zero_usage():
    return {"input_tokens": 0, "cached_input_tokens": 0, "uncached_input_tokens": 0,
            "output_tokens": 0, "responses": 0}


def test_closed_manifest_rejects_before_prior_or_output_access(tmp_path):
    manifest = json.loads(followup.MANIFEST.read_text())
    manifest["execution_status"] = "closed"
    path = tmp_path / "closed.json"
    path.write_text(json.dumps(manifest))
    output = tmp_path / "must-not-exist"
    args = SimpleNamespace(manifest=path, prior_root=tmp_path / "missing-prior",
                           output=output, binary="unused", codex_executable="unused", run=False)

    with pytest.raises(ValueError, match="closed"):
        asyncio.run(followup.run(args))
    assert not output.exists()


def test_manifest_fidelity_to_published_v2_approval_record():
    manifest = json.loads(followup.MANIFEST.read_text())
    published = json.loads((followup.MANIFEST.parent / "raw-northstar-workflow-v2-summary.json").read_text())
    approved = published["synthetic_owner_consent"]
    prior_receipt = published["native_run_receipt"]
    assert published["raw_report_sha256"] == manifest["prior"]["report_sha256"]
    assert published["raw_trace_sha256"] == manifest["prior"]["trace_sha256"]
    assert approved["card_id"] == manifest["prior"]["card_id"]
    assert approved["version"] == manifest["prior"]["card_version"]
    assert approved["policy_digest"] == followup.CARD_POLICY_SHA256
    assert manifest["prior"]["card_policy_sha256"] == approved["policy_digest"]
    assert prior_receipt["receipt_id"] == manifest["prior"]["receipt_id"]
    assert prior_receipt["idempotency_key"] == manifest["prior"]["run_key"]
    assert prior_receipt["delivery_enabled"] is False


def test_manifest_pins_caps_order_key_and_published_source_urls():
    manifest = json.loads(followup.MANIFEST.read_text())
    # Exercise admission on an in-memory fixture even after the real cohort
    # closes. Never reopen the checked-in protocol or its native run key.
    manifest["execution_status"] = "planned"
    followup.validate_manifest(manifest)
    for field, value in (("model", "gpt-6-astra"), ("reasoning_effort", "max"),
                         ("frontier_invocations", 3), ("tools_per_episode", 25),
                         ("seconds_per_episode", 301), ("max_output_tokens", 4001),
                         ("jev_attempts_total", 2),
                         ("between_invocation_input_stop", 700000)):
        altered = json.loads(json.dumps(manifest))
        altered["limits"][field] = value
        with pytest.raises(ValueError, match="fixed key, order, limits, or source identity"):
            followup.validate_manifest(altered)
    altered = json.loads(json.dumps(manifest))
    altered["run_key"] = "alternate-output-retry"
    with pytest.raises(ValueError, match="fixed key"):
        followup.validate_manifest(altered)
    published = _published_profiles()
    assert {key: {"source_url": item["source_url"]} for key, item in published.items()} == followup.SOURCE_ASSETS


@pytest.mark.parametrize("field", [
    "scope", "comparison", "request", "policy_boundary", "method", "stops", "owner_reference_file",
])
def test_complete_preregistration_rejects_changed_method_before_preflight(field):
    manifest = json.loads(followup.MANIFEST.read_text())
    manifest["execution_status"] = "planned"
    manifest[field] = "changed before preflight"
    with pytest.raises(ValueError, match="complete preregistered protocol"):
        followup.validate_manifest(manifest)


def test_only_reviewed_native_build_and_original_owner_declarations_are_accepted(tmp_path):
    manifest = json.loads(followup.MANIFEST.read_text())
    followup.validate_native_build(dict(followup.EXPECTED_NATIVE_BUILD), manifest)
    for key in followup.EXPECTED_NATIVE_BUILD:
        changed = {**followup.EXPECTED_NATIVE_BUILD, key: "unreviewed"}
        with pytest.raises(ValueError, match="preregistered native build"):
            followup.validate_native_build(changed, manifest)
    original = followup.MANIFEST.with_name(manifest["owner_reference_file"])
    assert followup.read_owner_declarations(original)
    changed_owner = tmp_path / "changed-owner.json"
    changed_owner.write_text(json.dumps({"owner_declarations": {"new": "unreviewed rule"}}))
    with pytest.raises(ValueError, match="original declarations"):
        followup.read_owner_declarations(changed_owner)


def test_pinned_query_definitions_and_columns_come_from_public_prior_captures(tmp_path, monkeypatch):
    monkeypatch.setattr(followup, "make_sources", SourceStub)
    profiles = _published_profiles()
    trace = tmp_path / "trace.jsonl"
    trace.write_text("".join(json.dumps({"kind": "tool.result", "name": "profile_saved_chart",
                                         "result": {key: item[key] for key in
                                                    ("chart_id", "query_definition", "columns")}}) + "\n"
                            for item in profiles.values()))
    captures = followup.prior_source_captures(tmp_path)
    assert captures == _prior_captures()
    source_state, telemetry = asyncio.run(followup.probe_sources(
        NativeStub(), captures,
    ))
    assert source_state["profiles"] == _source_state()
    assert source_state["native_inspections"] == {
        chart_id: {"resource": f"chart:{chart_id}", "source_url": profiles[chart_id]["source_url"],
                   "query_definition_sha256": captures[chart_id]["query_definition_sha256"],
                   "columns": profiles[chart_id]["columns"]}
        for chart_id in profiles
    }
    assert telemetry["logical_tool_calls"] == 2


def test_coordinator_config_checks_only_loopback_superset_endpoint(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[environment]\nSUPERSET_URL = "http://127.0.0.1:18089"\nSUPERSET_PASSWORD = "not-emitted"\n')
    assert followup.coordinator_superset_url(config) == followup.SOURCE_URL
    config.write_text('[environment]\nSUPERSET_URL = "https://remote.example"\n')
    with pytest.raises(ValueError, match="expected loopback"):
        followup.coordinator_superset_url(config)


def test_output_and_prior_artifacts_are_isolated(tmp_path):
    prior = tmp_path / "prior"
    prior.mkdir()
    (prior / "report.json").write_text("closed report")
    (prior / "trace.jsonl").write_text("closed trace")
    for output in (prior, prior / "child", tmp_path):
        with pytest.raises(ValueError, match="isolated"):
            followup.output_disjoint(output, prior)
    output = tmp_path / "separate"
    followup.output_disjoint(output, prior)
    assert (prior / "report.json").read_text() == "closed report"
    assert (prior / "trace.jsonl").read_text() == "closed trace"


def test_key_metadata_is_stat_only_and_private(tmp_path, monkeypatch):
    key = tmp_path / "dummy.key"
    key.write_bytes(b"scrubbed-test-key-material")
    key.chmod(0o600)
    read_bytes, read_text = Path.read_bytes, Path.read_text

    def guarded_bytes(path):
        assert path != key
        return read_bytes(path)

    def guarded_text(path, *args, **kwargs):
        assert path != key
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", guarded_bytes)
    monkeypatch.setattr(Path, "read_text", guarded_text)
    metadata = followup.key_file_metadata(key)
    assert metadata["mode"] == stat.S_IMODE(key.stat().st_mode) == 0o600
    assert metadata["size"] == len(b"scrubbed-test-key-material")
    assert metadata["device"] == key.stat().st_dev


def test_dynamic_parent_import_does_not_change_helper_fingerprint(monkeypatch):
    before = followup.helper_hashes()
    assert "src/signalweave/superset_client.py" in before
    assert "src/signalweave/models.py" in before
    late = ModuleType("evaluations.late_parent_import")
    late.__file__ = str(Path(followup.__file__).resolve().parents[1] / "tests/test_raw_superset_workflow.py")
    monkeypatch.setitem(sys.modules, late.__name__, late)
    assert followup.helper_hashes() == before


def test_notes_are_optional_but_current_evidence_is_required_by_instructions():
    assert "recover your notes" in REPORT_RULES  # Closed v2 wording remains untouched.
    assert "recover your notes" not in followup.REPORT_INSTRUCTIONS
    assert "as needed" in followup.REPORT_INSTRUCTIONS
    assert "Current factual claims require refreshed evidence from this run" in followup.REPORT_INSTRUCTIONS
    assert "Read your own retained notes" not in followup.REPORT_INSTRUCTIONS


def test_prior_card_and_receipt_reads_validate_exact_identity(monkeypatch):
    manifest = json.loads(followup.MANIFEST.read_text())
    expected = manifest["prior"]
    card = {"id": expected["card_id"], "version": expected["card_version"], "status": "approved"}
    receipt = {"status": "found", "receipt": {
        "receipt_id": expected["receipt_id"], "idempotency_key": expected["run_key"],
        "card_id": expected["card_id"], "card_version": expected["card_version"],
        "delivery_enabled": False,
    }}

    class ReadOnlyNative:
        def __init__(self):
            self.calls = []

        async def call_tool(self, name, args):
            self.calls.append((name, args))
            return [], card if name == "get_insight_card" else receipt

    monkeypatch.setattr(followup, "approval_digest", lambda kind, value: expected["card_policy_sha256"])
    native = ReadOnlyNative()
    state, observed_card = asyncio.run(followup.read_prior_state(native, manifest))
    assert observed_card == card
    assert state["card_policy_sha256"] == expected["card_policy_sha256"]
    assert state["receipt_sha256"] == followup.json_digest(receipt)
    assert [name for name, _ in native.calls] == ["get_insight_card", "get_decision_receipt"]


def test_report_episode_guards_card_new_receipt_one_evaluation_and_submission():
    manifest = json.loads(followup.MANIFEST.read_text())
    prior = manifest["prior"]
    native = NativeStub()
    episode = followup.RetainedReportEpisode(
        SourceStub(), {}, "own retained notes", native,
        approved_card_id=prior["card_id"], run_key=manifest["run_key"],
        source_state=_source_state(),
    )

    async def exercise():
        early_read = await episode.call("profile_saved_chart", {"id": "1"})
        assert early_read["chart_id"] == "1"  # Harmless extra reads remain visible to quality review.
        with pytest.raises(ValueError, match="Evaluate the approved card once"):
            await episode.call("record_report", {
                "outcome": "notify", "recipients": ["unapproved recipient"], "message": "Draft",
            })
        await episode.call("evaluate_insight_card", {
            "card_id": prior["card_id"], "idempotency_key": manifest["run_key"],
        })
        with pytest.raises(ValueError, match="retained approved card"):
            await episode.call("get_insight_card", {"card_id": "other-card"})
        for selector in ({}, {"receipt_id": prior["receipt_id"]},
                         {"idempotency_key": prior["run_key"]}):
            with pytest.raises(ValueError, match="follow-up's receipt"):
                await episode.call("get_decision_receipt", selector)
        await episode.call("get_insight_card", {"card_id": prior["card_id"]})
        with pytest.raises(ValueError, match="Only one new evaluation"):
            await episode.call("evaluate_insight_card", {
                "card_id": prior["card_id"], "idempotency_key": manifest["run_key"],
            })
        receipt = await episode.call("get_decision_receipt", {
            "receipt_id": "receipt-followup-offline",
        })
        assert receipt["receipt"]["receipt_id"] == "receipt-followup-offline"
        proposed = {"outcome": "notify", "recipients": ["invented person", "Another arbitrary route"],
                    "message": "Evidence-backed report."}
        await episode.call("record_report", proposed)
        assert episode.submission == proposed
        with pytest.raises(ValueError, match="Report already recorded"):
            await episode.call("get_decision_receipt", {"receipt_id": "receipt-followup-offline"})

    asyncio.run(exercise())
    evaluations = [args for name, args in native.calls if name == "evaluate_insight_card"]
    assert len(evaluations) == 1
    assert evaluations[0]["idempotency_key"] == manifest["run_key"]


def test_both_arms_have_identical_five_bi_tools_and_treatment_only_native(monkeypatch):
    native = NativeStub()
    monkeypatch.setattr(followup, "make_sources", SourceStub)
    manifest = json.loads(followup.MANIFEST.read_text())
    _, _, baseline, treatment = asyncio.run(followup.make_sessions(
        native, {"owner": "declaration"}, {"baseline": "B notes", "signalweave": "T notes"},
        manifest, _source_state(),
    ))
    baseline_names = {spec["name"] for spec in baseline}
    treatment_names = {spec["name"] for spec in treatment}
    assert followup.BI_TOOLS <= baseline_names
    assert baseline_names == followup.SHARED_TOOLS
    assert treatment_names == baseline_names | REPORT_NATIVE
    assert [spec for spec in treatment if spec["name"] not in REPORT_NATIVE] == baseline


def test_closed_v2_tool_surface_stays_unchanged_by_default():
    default_episode = ReportEpisode(RawSupersetTools(object()), {}, "notes")
    aggregate_episode = ReportEpisode(RawSupersetTools(object(), enable_aggregation=True), {}, "notes")
    default_names = {spec["name"] for spec in asyncio.run(default_episode.specs())}
    aggregate_names = {spec["name"] for spec in asyncio.run(aggregate_episode.specs())}
    assert "aggregate_chart_rows" not in default_names
    assert "aggregate_chart_rows" in aggregate_names


def test_matching_preflight_requires_exact_frozen_state_zero_usage_and_zero_calls():
    frozen = {"runner": "abc"}
    valid = {"protocol": followup.PROTOCOL, "frozen": frozen, "completed": True,
             "preflight_only": True, "frontier_invocations_started": 0, "jev_attempts": 0,
             "followup_key_unused": True,
             "usage": _zero_usage(), **{field: True for field in (
                 "source_probe_ok", "shared_tools_equal", "card_policy_valid", "prior_receipt_valid",
                 "prior_artifacts_unchanged", "native_config_unchanged",
                 "persisted_dummy_key_metadata_valid", "usage_known",
             )}}
    followup.validate_preflight(valid, frozen)
    for changes in ({"frozen": {"runner": "changed"}},
                    {"frontier_invocations_started": 1}, {"jev_attempts": 1},
                    {"usage_known": False}, {"usage": None}, {"source_probe_ok": False}):
        with pytest.raises(ValueError, match="matching successful|zero frontier requests"):
            followup.validate_preflight({**valid, **changes}, frozen)


@pytest.mark.asyncio
async def test_actual_offline_mcp_receipt_is_fresh_once_and_replay_is_rejected(tmp_path):
    from signalweave.models import InsightCard, InsightCardStatus, SourceRef
    from tests.test_onboarding import make_server, tool

    audit = followup.Audit()
    budget = followup.RequestBudget(1)

    class AuditedFixtureJudger:
        name = "offline-jeV-fixture"
        skip_semantic_compile = True

        async def rank_resources(self, goal, resources):
            return {f"{item.adapter}|{item.resource}": 0.9 for item in resources}

        async def compile_plan(self, state, card):
            return {"capabilities": [], "baseline": "previous_period"}

        async def judge(self, state, card, plan, observations):
            budget.claim()
            audit.emit("api.request", provider="jev", request_id=1)
            from signalweave.models import InsightResult, Outcome
            result = InsightResult(card_id=card.id, outcome=Outcome.INVESTIGATE,
                                   summary="Offline judgment", rationale="Test fixture",
                                   confidence=0.9, probabilities={"investigate": 0.9},
                                   evidence=state["evidence"], observations=observations,
                                   source_keys=[source["source_key"] for source in state["sources"]],
                                   evaluator=self.name)
            audit.emit("api.response", provider="jev", request_id=1,
                       usage={"input_tokens": 17, "output_tokens": 4})
            return result

    server = make_server(tmp_path, judger=AuditedFixtureJudger())
    manifest = json.loads(followup.MANIFEST.read_text())
    prior = manifest["prior"]
    card = InsightCard(
        id=prior["card_id"], title="Offline approved card", what_to_watch="Test source",
        why_watch="Exercise the actual receipt store", comparison_windows=["previous_period"],
        sources=[SourceRef(key="growth", adapter="superset", resource="dashboard:7", label="Growth")],
        status=InsightCardStatus.APPROVED,
        principal_tenant="default",
    )
    server._test_runtime.card_store.save_card(card)

    class Native:
        async def call_tool(self, name, arguments):
            try:
                result = await tool(server, name)(**arguments)
            except ValueError as error:
                raise RuntimeError(str(error)) from None
            return [], result

    native = Native()
    await followup.require_followup_key_unused(native, manifest)
    started = datetime.now(timezone.utc).isoformat()
    evaluation = await tool(server, "evaluate_insight_card")(
        card_id=prior["card_id"], idempotency_key=manifest["run_key"], response_mode="full",
    )
    lookup = await tool(server, "get_decision_receipt")(idempotency_key=manifest["run_key"])
    assert followup.validate_new_receipt(evaluation, lookup, manifest, started)["receipt_id"] == \
        lookup["receipt"]["receipt_id"]
    assert followup.validate_jev_completion(audit.events, budget) == {"input_tokens": 17, "output_tokens": 4}
    with pytest.raises(ValueError, match="already has a durable receipt"):
        await followup.require_followup_key_unused(native, manifest)
    replay = await tool(server, "evaluate_insight_card")(
        card_id=prior["card_id"], idempotency_key=manifest["run_key"], response_mode="full",
    )
    assert replay["replayed"] is True and budget.used == 1
    with pytest.raises(ValueError, match="fresh, non-replayed"):
        followup.validate_new_receipt(replay, lookup, manifest, started)


def test_invocation_admission_stops_on_unknown_or_threshold_without_retry():
    manifest = json.loads(followup.MANIFEST.read_text())
    limits = manifest["limits"]
    report = {"frontier_invocations_started": 1}
    unknown = followup.Audit()
    unknown.events.append({"kind": "api.request", "provider": "openai", "request_id": 1})
    snapshot = followup.usage_snapshot(unknown.events, 1)
    assert snapshot["known"] is False and snapshot["usage"] is None
    for _ in range(2):
        with pytest.raises(RuntimeError, match="usage stop"):
            followup.ensure_invocation_budget(unknown, report, limits)
    assert report["frontier_invocations_started"] == 1

    stopped = followup.Audit(events=[
        {"kind": "api.request", "provider": "openai", "request_id": 1},
        {"kind": "api.response", "provider": "openai", "request_id": 1,
         "usage": {"input_tokens": 600000, "output_tokens": 1,
                   "input_tokens_details": {"cached_tokens": 480000}}},
    ])
    with pytest.raises(RuntimeError, match="usage stop"):
        followup.ensure_invocation_budget(stopped, report, limits)
    assert followup.usage_snapshot(stopped.events, 1)["usage"]["uncached_input_tokens"] == 120000


def test_source_tool_failure_is_terminal_input():
    assert not followup.has_source_failure([{
        "kind": "tool.result", "name": "aggregate_chart_rows", "result": {"rows": []},
    }])
    assert followup.has_source_failure([{
        "kind": "tool.result", "name": "aggregate_chart_rows",
        "arguments": {"id": "1"},
        "result": {"error": "RawSupersetSourceError", "message": "source unavailable"},
    }])
    assert not followup.has_source_failure([{
        "kind": "tool.result", "name": "read_chart_rows", "arguments": {"id": "999999"},
        "result": {"error": "RawSupersetSourceError", "message": "chart not found"},
    }])
    assert not followup.has_source_failure([{
        "kind": "tool.result", "name": "list_dashboard_charts", "arguments": {"id": "1"},
        "result": {"error": "RawSupersetSourceError", "message": "dashboard not found"},
    }])
    assert not followup.has_source_failure([{
        "kind": "tool.result", "name": "aggregate_chart_rows",
        "result": {"error": "ValueError", "message": "invalid column"},
    }])
    assert not followup.has_source_failure([{
        "kind": "tool.result", "name": "record_report",
        "result": {"error": "ValidationError", "message": "invalid report"},
    }])


def test_completion_requires_one_successful_accounted_jev_attempt():
    good = [
        {"kind": "api.request", "provider": "jev", "request_id": 1},
        {"kind": "api.response", "provider": "jev", "request_id": 1,
         "usage": {"input_tokens": 9, "output_tokens": 3}},
    ]
    budget = followup.RequestBudget(1, used=1)
    assert followup.validate_jev_completion(good, budget) == {"input_tokens": 9, "output_tokens": 3}
    failures = (
        ([], followup.RequestBudget(1)),
        ([*good, {"kind": "api.error", "provider": "jev", "request_id": 2}], budget),
        ([*good, {"kind": "api.rejected", "provider": "jev", "request_id": 2}], budget),
        ([good[0], {**good[1], "usage": {"input_tokens": 9}}], budget),
        ([good[0], {**good[1], "usage": {"input_tokens": -1, "output_tokens": 3}}], budget),
        ([good[0], {**good[1], "request_id": 2}], budget),
        ([{**good[0], "request_id": None}, {**good[1], "request_id": None}], budget),
        ([*good, good[0]], budget),
    )
    for events, attempt_budget in failures:
        with pytest.raises(ValueError, match="Completion requires"):
            followup.validate_jev_completion(events, attempt_budget)


def test_key_path_is_not_reprinted_in_terminal_error():
    audit = followup.Audit()
    message = followup.safe_error_message(FileNotFoundError("missing /private/owner/key"), audit,
                                          ["/private/owner/key"])
    assert "/private/owner/key" not in message
    assert "[PRIVATE_KEY_FILE]" in message


def test_complete_preflight_and_mocked_pair_use_only_frozen_bounded_path(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    prior_root = tmp_path / "retained"
    home = prior_root / "native-home"
    home.mkdir(parents=True)
    (home / "config.toml").write_text(
        '[environment]\nSUPERSET_URL = "http://127.0.0.1:18089"\n'
    )
    dummy = home / "typesafe.key"
    dummy.write_text("scrubbed test key")
    dummy.chmod(0o600)
    prior_files = {prior_root / "report.json": b"retained report",
                   prior_root / "trace.jsonl": b"retained trace\n"}
    for path, value in prior_files.items():
        path.write_bytes(value)
    binary, codex = tmp_path / "binary", tmp_path / "codex"
    binary.write_bytes(b"test binary placeholder")
    codex.write_bytes(b"test codex placeholder")
    key_file = tmp_path / "live-test-key"
    key_file.write_text("not a credential; offline double")
    key_file.chmod(0o600)
    manifest = json.loads(followup.MANIFEST.read_text())
    manifest["execution_status"] = "planned"  # This test owns only its temporary fixture.
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (tmp_path / manifest["owner_reference_file"]).write_text("offline owner declaration fixture")
    card = {
        "id": manifest["prior"]["card_id"], "title": "Approved test card",
        "what_to_watch": "Use current source evidence.", "why_watch": "Offline harness fixture.",
        "version": manifest["prior"]["card_version"], "status": "approved",
        "delivery_methods": [{"key": "route-key", "outcome": "investigate",
                              "label": "Approved route", "destination": "Approved destination"}],
    }
    card_state = {"card_policy_sha256": manifest["prior"]["card_policy_sha256"],
                  "receipt_sha256": "a" * 64, "card_id": card["id"],
                  "card_version": card["version"], "receipt_id": manifest["prior"]["receipt_id"]}
    monkeypatch.setattr(followup, "validate_prior_record",
                        lambda *args: ({"protocol": followup.PRIOR_PROTOCOL},
                                       {"baseline": "B's retained note", "signalweave": "T's retained note"},
                                       {"owner": "same owner declaration"}))
    monkeypatch.setattr(followup, "verify_binary", lambda path: dict(followup.EXPECTED_NATIVE_BUILD))
    async def pinned_codex(_):
        return {"path": str(codex), "sha256": followup.digest(codex)}
    monkeypatch.setattr(followup, "pinned_codex", pinned_codex)
    monkeypatch.setattr(followup, "helper_hashes", lambda: {"frozen-helper.py": "c" * 64})
    monkeypatch.setattr(followup, "make_sources", SourceStub)
    monkeypatch.setattr(followup, "prior_source_captures", lambda root: _prior_captures())
    async def read_state(native, current_manifest):
        return dict(card_state), dict(card)
    monkeypatch.setattr(followup, "read_prior_state", read_state)

    native_receipts = {}

    @followup.asynccontextmanager
    async def fake_native(binary, home, prior_root, provider_key_file, audit, budget):
        yield NativeStub(budget=budget, audit=audit, state=native_receipts)

    monkeypatch.setattr(followup, "retained_native", fake_native)
    monkeypatch.setattr(followup, "check_prior_files",
                        lambda root, current_manifest: all(path.read_bytes() == value
                                                           for path, value in prior_files.items()))
    actor_calls = []
    tool_order = []

    async def fake_codex_episode(session, **kwargs):
        arm = "signalweave" if session.native else "baseline"
        actor_calls.append((arm, session, kwargs))
        audit = kwargs["audit"]
        request_id = len(actor_calls)
        audit.emit("api.request", provider="openai", request_id=request_id)
        calls = 0
        if session.native:
            tool_order.append((arm, "evaluate_insight_card"))
            await session.call("evaluate_insight_card", {
                "card_id": card["id"], "idempotency_key": manifest["run_key"],
            })
            tool_order.append((arm, "aggregate_chart_rows"))
            await session.call("aggregate_chart_rows", {
                "id": "1", "filters": [], "group_by": [], "aggregations": [{"op": "count"}],
            })
            calls += 2
        else:
            tool_order.append((arm, "profile_saved_chart"))
            await session.call("profile_saved_chart", {"id": "1"})
            calls += 1
        tool_order.append((arm, "record_report"))
        await session.call("record_report", {
            "outcome": "investigate", "recipients": ["Approved destination"],
            "message": "Offline evidence-backed report.",
        })
        calls += 1
        audit.emit("api.response", provider="openai", request_id=request_id,
                   usage={"input_tokens": 100, "output_tokens": 5,
                          "input_tokens_details": {"cached_tokens": 10}})
        return {"status": "complete", "tool_calls": calls}

    monkeypatch.setattr(followup, "codex_episode", fake_codex_episode)
    preflight_output = tmp_path / "preflight"
    preflight = asyncio.run(followup.run(SimpleNamespace(
        binary=binary, codex_executable=codex, prior_root=prior_root,
        output=preflight_output, run=False, preflight=None, key_file=None, manifest=manifest_path,
    )))
    assert preflight["terminal_status"] == "preflight_complete"
    assert preflight["frontier_invocations_started"] == preflight["jev_attempts"] == 0
    assert preflight["usage"] == _zero_usage() and not actor_calls

    used_manifest = tmp_path / "used-manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    used_manifest.write_bytes(manifest_bytes)
    (tmp_path / manifest["owner_reference_file"]).write_text("offline owner declaration fixture")
    native_receipts["receipt"] = {
        "receipt_id": "already-used-followup-key", "idempotency_key": manifest["run_key"],
    }
    used = asyncio.run(followup.run(SimpleNamespace(
        binary=binary, codex_executable=codex, prior_root=prior_root,
        output=tmp_path / "used-key", run=True, preflight=preflight_output / "report.json",
        key_file=key_file, manifest=used_manifest,
    )))
    assert used["terminal_status"] == "closed_failure" and actor_calls == []
    assert used["frontier_invocations_started"] == 0
    assert json.loads(used_manifest.read_text())["execution_status"] == "closed"
    assert (tmp_path / "used-key" / "report.json").is_file()
    native_receipts.clear()

    result = asyncio.run(followup.run(SimpleNamespace(
        binary=binary, codex_executable=codex, prior_root=prior_root,
        output=tmp_path / "paired", run=True, preflight=preflight_output / "report.json",
        key_file=key_file, manifest=manifest_path,
    )))
    assert result["terminal_status"] == "closed_complete", (
        result.get("error"), result.get("final_state_check_error"),
        result.get("card_policy_unchanged"), result.get("old_receipt_unchanged"),
        result.get("new_receipt_valid"), result.get("followup_key_unused"),
        result.get("followup_key_consumed_once"), result.get("new_receipt_check_error"),
    )
    assert result["frontier_invocations_started"] == 2 and result["usage_known"] is True
    assert result["usage"]["responses"] == 2 and result["jev_attempts"] == 1
    assert result["jev_usage_known"] is True
    assert result["arm_order"] == ["baseline", "signalweave"]
    assert [arm for arm, _, _ in actor_calls] == ["baseline", "signalweave"]
    baseline, treatment = actor_calls
    assert baseline[1].notes == "B's retained note" and treatment[1].notes == "T's retained note"
    assert tool_order == [("baseline", "profile_saved_chart"), ("baseline", "record_report"),
                          ("signalweave", "evaluate_insight_card"),
                          ("signalweave", "aggregate_chart_rows"),
                          ("signalweave", "record_report")]
    assert "read_working_notes" not in {name for _, name in tool_order}
    assert baseline[2]["accounting_drain"] is treatment[2]["accounting_drain"] is True
    assert baseline[2]["max_tool_calls"] == treatment[2]["max_tool_calls"] == 24
    assert baseline[2]["max_turns"] is treatment[2]["max_turns"] is None
    assert baseline[2]["max_output_tokens"] is treatment[2]["max_output_tokens"] is None
    baseline_prompt, treatment_prompt = (actor[2]["prompt_override"] for actor in (baseline, treatment))
    assert baseline_prompt["request"] == treatment_prompt["request"] == followup.REPORT_REQUEST
    assert baseline_prompt["owner_declarations"] == treatment_prompt["owner_declarations"]
    assert baseline_prompt["reviewed_policy"] == treatment_prompt["reviewed_policy"]
    assert "if useful" in baseline_prompt["retained_notes"]
    assert result["tool_calls_by_episode"] == {"baseline": 2, "signalweave": 3}
    assert result["card_policy_unchanged"] is True and result["old_receipt_unchanged"] is True
    assert result["prior_artifacts_unchanged"] is True
    report_path = tmp_path / "paired" / "report.json"
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    assert str(key_file) not in report_path.read_text()

    actor_calls.clear()
    native_receipts.clear()
    partial_manifest = tmp_path / "partial-manifest.json"
    partial_manifest.write_bytes(manifest_bytes)

    async def incomplete_actor(session, **kwargs):
        actor_calls.append("signalweave" if session.native else "baseline")
        kwargs["audit"].emit("api.request", provider="openai", request_id=1)
        return {"status": "incomplete", "tool_calls": 0}

    monkeypatch.setattr(followup, "codex_episode", incomplete_actor)
    partial = asyncio.run(followup.run(SimpleNamespace(
        binary=binary, codex_executable=codex, prior_root=prior_root,
        output=tmp_path / "partial", run=True, preflight=preflight_output / "report.json",
        key_file=key_file, manifest=partial_manifest,
    )))
    assert partial["terminal_status"] == "closed_failure"
    assert partial["frontier_invocations_started"] == 1 and actor_calls == ["baseline"]
    assert partial["usage_known"] is False and partial["usage"] is None
    assert partial["episodes"][0]["status"] == "incomplete"
    assert partial["card_policy_unchanged"] is partial["old_receipt_unchanged"] is True
    assert json.loads(partial_manifest.read_text())["execution_status"] == "closed"
    assert (tmp_path / "partial" / "report.json").is_file()

    with pytest.raises(ValueError, match="closed or not preregistered"):
        asyncio.run(followup.run(SimpleNamespace(
            binary=binary, codex_executable=codex, prior_root=prior_root,
            output=tmp_path / "incomplete", run=True,
            preflight=preflight_output / "report.json", key_file=key_file,
            manifest=manifest_path,
        )))
    assert not (tmp_path / "incomplete").exists()
