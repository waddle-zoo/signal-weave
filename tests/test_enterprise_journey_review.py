import copy
import hashlib
import json

import pytest

from evaluations.bootstrap_agent_trial import usage_summary
from evaluations.bootstrap_scenarios import dataset_digest, score_submission
from evaluations.enterprise_journey_review import (
    export,
    export_cohort,
    onboarding_stories,
    validate_execution,
)


def test_story_keeps_failed_setup_interview_and_review_without_inventing_first_value_time():
    fixtures = [{"scenario_id": "one", "private": {"canary": "not exported"}, "public": {
        "company": "Example", "brief": "Explain a change", "catalog": [
            {"adapter": "bi", "resource": "alternate", "metadata": {"scope_note": "Pilot only"}}]}}]
    report = {"rows": [{"scenario_id": "one", "period_id": "setup", "arm": "test",
                        "phase": "onboarding", "status": "failed", "error": "timeout",
                        "seconds": 10, "notes": "Owner policy retained"}]}
    base = {"episode": "one/test/setup"}
    events = [
        {**base, "kind": "tool.result", "name": "get_signalweave_guide", "result": {}, "arguments": {}},
        {**base, "kind": "tool.result", "name": "ask_owner", "arguments": {"topic": "materiality"},
         "result": {"answer": "Owner's threshold"}},
        {**base, "kind": "tool.result", "name": "simulate_insight_card", "result": {"error": "provider failure"}},
        {**base, "kind": "tool.result", "name": "preview_investigation_report", "result": {"status": "preview"}},
        {**base, "kind": "tool.result", "name": "record_owner_review", "actor_role": "owner_reviewer", "result": {}},
        {**base, "kind": "review.result", "approved": False, "reasons": ["Incorrect routing"]},
        {**base, "kind": "source.read", "ref": "bi|alternate"},
        {"episode": "different", "kind": "source.read", "ref": "bi|alternate"},
    ]
    story, = onboarding_stories(report, events, fixtures)
    assert story["status"] == "failed"
    assert story["guide_calls"] == 1 and story["author_tool_calls"] == 4
    assert story["first_successful_preview_tool_ordinal"] == 4
    assert story["first_preview_wall_time"] is None
    assert story["alternate_scope_read_count"] == 1
    assert len(story["owner_interview"]) == len(story["owner_reviews"]) == len(story["tool_errors"]) == 1
    assert "not exported" not in str(story)


@pytest.fixture
def execution():
    fixtures = [{"scenario_id": "one", "public": {"onboarding": {"period_id": "setup"},
                                                   "periods": [{"period_id": "later"}]}}]
    events = [{"episode": "one/luna_signalweave_jev/setup", "provider": "jev", "request_id": 1,
               "kind": kind} for kind in ("api.request", "api.error")]
    rows = [{"scenario_id": "one", "arm": arm, "period_id": period,
             "usage": usage_summary([e for e in events if e["episode"] == f"one/{arm}/{period}"])}
            for arm in ("luna_bi", "luna_signalweave_jev") for period in ("setup", "later")]
    return {"rows": rows, "usage": usage_summary(events)}, events, fixtures


def test_execution_counts_planned_denominators_and_retains_failed_attempt(execution):
    report, events, fixtures = execution
    before = copy.deepcopy(execution)
    assert validate_execution(report, events, fixtures) == {
        "expected_episodes": 4, "expected_onboardings": 2,
        "expected_monitoring_per_arm": 1, "validated": True}
    assert execution == before


@pytest.mark.parametrize("defect", ["missing_row", "duplicate_row", "foreign_episode",
                                   "missing_terminal", "duplicate_request", "unknown_provider",
                                   "report_usage", "episode_usage"])
def test_execution_rejects_mixed_truncated_and_miscounted_artifacts(execution, defect):
    report, events, fixtures = execution
    if defect == "missing_row":
        report["rows"].pop()
    elif defect == "duplicate_row":
        report["rows"][-1] = report["rows"][0]
    elif defect == "foreign_episode":
        events[0]["episode"] = "wrong"
    elif defect == "missing_terminal":
        events.pop()
    elif defect == "duplicate_request":
        events.append(events[0])
    elif defect == "unknown_provider":
        events[0]["provider"] = "unknown"
    elif defect == "report_usage":
        report["usage"]["jev"]["attempts"] += 1
    else:
        report["rows"][0]["usage"]["jev"]["attempts"] += 1
    with pytest.raises(ValueError):
        validate_execution(report, events, fixtures)


@pytest.fixture
def staged_cohort(tmp_path, monkeypatch):
    fixtures = [{"scenario_id": f"company-{i}", "public": {
        "company": f"Company {i}", "brief": "Report scoped changes", "glossary": {}, "catalog": [],
        "owner_topics": ["policy"], "owner_answers": {"policy": "Notify operations"},
        "submission_contract": {},
        "onboarding": {"period_id": "setup", "as_of": "2026-10-01T00:00:00+00:00"},
        "periods": [{"period_id": f"period-{j}", "snapshots": {"bi|metric": {}},
                     "as_of": "2026-10-02T00:00:00+00:00"} for j in range(3)],
        "numeric_vocabulary": [],
        "destinations": [{"key": "operations", "destination": "route://operations"}],
    }, "private": {"periods": {f"period-{j}": {
        "outcome": "notify", "recipients": ["operations"], "condition": "event",
        "required_evidence_refs": ["bi|metric"], "required_owner_topics": ["policy"],
        "numeric_facts": {}, "required_numeric_facts": [], "allowed_claim_types": [],
        "required_claim_types": [],
    } for j in range(3)}}} for i in range(6)]
    monkeypatch.setattr("evaluations.enterprise_journey_review.journeys", lambda seed: fixtures)
    config = {
        "seed": 20261003, "model": "gpt-5.6-luna", "effort": "low",
        "owner_review": "independent_synthetic", "owner_review_model": "gpt-5.6-luna",
        "owner_review_effort": "high", "owner_review_attempts_per_arm_company": 3,
        "owner_review_timeout_seconds": 90, "agent_transport": "codex_cli",
        "episode_timeout_seconds": 360, "max_tool_calls": 45, "max_turns": None,
        "max_output_tokens": None, "api_request_budget_scope": "Jev only",
        "source_fingerprint": {"git_revision": "frozen", "sha256": {"runtime.py": "a" * 64}},
    }
    paths = []
    for index, subset in enumerate((fixtures[:1], fixtures[1:])):
        folder = tmp_path / f"part-{index}"
        folder.mkdir()
        component_config = {**copy.deepcopy(config), "selected_companies": len(subset),
                            "selected_scenario_ids": [s["scenario_id"] for s in subset],
                            "dataset_digest": dataset_digest(subset),
                            "public_context_digest": f"subset-{index}",
                            "max_api_requests": (32, 112)[index],
                            "clock_rebased_to": f"2026-10-03T0{index}:00:00+00:00"}
        rows, events = [], []
        for fixture in subset:
            for arm in ("luna_bi", "luna_signalweave_jev"):
                for period in [fixture["public"]["onboarding"], *fixture["public"]["periods"]]:
                    episode = f"{fixture['scenario_id']}/{arm}/{period['period_id']}"
                    phase = "onboarding" if period["period_id"] == "setup" else "monitoring"
                    local = [{"episode": episode, "kind": kind, "provider": provider,
                              "request_id": len(events) + 1,
                              **({"usage": {"input_tokens": 1, "output_tokens": 1}}
                                 if kind == "api.response" else {})}
                             for provider in (("openai", "jev") if arm == "luna_signalweave_jev" else ("openai",))
                             for kind in ("api.request", "api.response")]
                    events.extend(local)
                    row = {"scenario_id": fixture["scenario_id"], "arm": arm,
                           "period_id": period["period_id"], "phase": phase, "status": "complete", "seconds": 1,
                           "usage": usage_summary(local), "inspected_refs": ["bi|metric"],
                           "asked_owner_topics": ["policy"],
                           "submission": {"outcome": "notify", "recipients": ["operations"],
                                          "evidence_refs": ["bi|metric"], "numeric_claims": [], "claims": [],
                                          "summary": "Scoped change."}}
                    if phase == "monitoring":
                        row["score"] = score_submission(
                            fixture, period["period_id"], row["submission"],
                            inspected_refs=row["inspected_refs"], asked_owner_topics=row["asked_owner_topics"],
                        )
                        assert row["score"]["exact"] is True
                    if arm == "luna_signalweave_jev" and phase == "monitoring":
                        row["system_output"] = {"result": {"outcome": "notify", "delivery_methods": [
                            {"destination": "route://operations"}]}}
                        row["raw_system_decision"] = {"outcome_correct": True, "recipients_correct": True,
                                                      "agent_changed_outcome": False, "outcome": "notify",
                                                      "recipients": ["operations"], "destinations": ["route://operations"],
                                                      "scope": "raw system routing only; not numerical or narrative correctness"}
                        events.append({"episode": episode, "kind": "system.evaluation",
                                       "response": copy.deepcopy(row["system_output"])})
                    if phase == "monitoring":
                        events.append({"episode": episode, "kind": "tool.result", "actor_role": "author",
                                       "name": "submit_analysis", "arguments": copy.deepcopy(row["submission"]),
                                       "result": {"recorded": True, "delivery_enabled": False}})
                    rows.append(row)
        report = {"config": component_config, "rows": rows, "usage": usage_summary(events),
                  "budget_censored": False, "status": "complete", "summary": {}, "comparative_eligible": True}
        path = folder / "report.json"
        path.write_text(json.dumps(report))
        path.with_name("trace.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        paths.append(path)
    return paths, tmp_path / "cohort"


def test_cohort_retains_components_clocks_and_counts_without_combining_latency(staged_cohort):
    paths, output = staged_cohort
    before = {p: p.read_bytes() for p in paths}
    result = export_cohort(paths, output)
    assert json.loads((output / "cohort.json").read_text()) == result
    assert result["integrity"]["expected_episodes"] == result["retained_episodes"] == 48
    assert result["integrity"]["expected_onboardings"] == 12
    assert result["jev_attempt_cap"] == 144
    assert result["jev_attempts"] == 24 and result["codex_invocations"] == 48
    assert result["narrative_gate"] == "unassessed"
    assert result["acceptance_status"] == "unassessed"
    assert "clock_rebased_to" not in result
    assert "median" not in result and "seconds" not in result and "usage" not in result
    assert len({c["clock_rebased_to"] for c in result["components"]}) == 2
    for component, path in zip(result["components"], paths, strict=True):
        assert component["report_path"] == str(path.resolve())
        assert component["report_sha256"] == hashlib.sha256(before[path]).hexdigest()
        assert component["trace_sha256"] == hashlib.sha256(path.with_name("trace.jsonl").read_bytes()).hexdigest()
        assert path.read_bytes() == before[path]
    for arm, counts in result["arms"].items():
        assert counts["planned_onboardings"] == counts["completed_onboardings"] == 6
        assert counts["planned_monitoring_periods"] == counts["final_structured_exact"] == 18
        assert counts["native_metric_applicable"] == (arm == "luna_signalweave_jev")
    assert result["arms"]["luna_bi"]["native_decisions_missing"] == 18
    assert result["arms"]["luna_signalweave_jev"]["native_outcome_and_recipient_correct"] == 18
    with pytest.raises(FileExistsError):
        export_cohort(paths, output)


def test_cohort_keeps_failed_and_missing_submissions_in_denominators(staged_cohort):
    from evaluations.enterprise_journey_review import journeys

    paths, output = staged_cohort
    report = json.loads(paths[0].read_text())
    report["budget_censored"] = True
    for row in report["rows"]:
        if row["arm"] == "luna_signalweave_jev":
            row["status"] = "failed"
            row.pop("raw_system_decision", None)
            row.pop("system_output", None)
        if row["phase"] == "monitoring":
            row["status"] = "failed"
            row["submission"] = None
            row["score"] = score_submission(
                journeys(report["config"]["seed"])[0], row["period_id"], {},
                inspected_refs=row["inspected_refs"], asked_owner_topics=row["asked_owner_topics"],
            )
    trace = paths[0].with_name("trace.jsonl")
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    events = [e for e in events if e["kind"] not in {"tool.result", "system.evaluation"}]
    trace.write_text("".join(json.dumps(e) + "\n" for e in events))
    paths[0].write_text(json.dumps(report))
    result = export_cohort(paths, output)
    treatment = result["arms"]["luna_signalweave_jev"]
    assert treatment["planned_onboardings"] == 6 and treatment["completed_onboardings"] == 5
    assert treatment["planned_monitoring_periods"] == 18
    assert treatment["completed_agent_reports"] == treatment["final_structured_exact"] == 15
    assert treatment["native_decisions_missing"] == 3
    assert result["arms"]["luna_bi"]["final_structured_exact"] == 15
    assert result["budget_censored"] is True
    assert result["acceptance_status"] == "not_passed"
    assert result["narrative_gate"] == "unassessed"


@pytest.mark.parametrize("defect,match", [
    ("score_flag", "structured score"), ("missing_score", "structured score"),
    ("submission", "submission trace"), ("inspected_refs", "structured score"),
    ("owner_topics", "structured score"), ("failed_row_exact_true", "structured score"),
    ("native_outcome_flag", "native routing"), ("native_route_flag", "native routing"),
    ("native_changed_flag", "native routing"), ("native_routes", "native routing"),
    ("system_route", "native routing"), ("system_outcome", "native routing"),
    ("absent_native", "native routing"), ("absent_system", "native routing"),
])
def test_cohort_rejects_forged_cached_scores_and_native_routes(staged_cohort, defect, match):
    paths, output = staged_cohort
    report = json.loads(paths[0].read_text())
    row = next(r for r in report["rows"] if r["phase"] == "monitoring" and r["arm"] == "luna_signalweave_jev")
    if defect == "score_flag":
        row["score"]["exact"] = False
    elif defect == "missing_score":
        row.pop("score")
    elif defect == "submission":
        # Cached success must not conceal a wrong submitted recipient.
        row["submission"]["recipients"] = ["outsider"]
    elif defect == "inspected_refs":
        row["inspected_refs"] = []
    elif defect == "owner_topics":
        row["asked_owner_topics"] = []
    elif defect == "failed_row_exact_true":
        row["status"] = "failed"
    elif defect == "native_outcome_flag":
        row["raw_system_decision"]["outcome_correct"] = False
    elif defect == "native_route_flag":
        row["raw_system_decision"]["recipients_correct"] = False
    elif defect == "native_changed_flag":
        row["raw_system_decision"]["agent_changed_outcome"] = True
    elif defect == "native_routes":
        row["raw_system_decision"]["recipients"] = ["outsider"]
    elif defect == "system_route":
        row["system_output"]["result"]["delivery_methods"][0]["destination"] = "route://outsider"
    elif defect == "system_outcome":
        row["system_output"]["result"]["outcome"] = "ignore"
    elif defect == "absent_native":
        row.pop("raw_system_decision")
    else:
        row.pop("system_output")
    paths[0].write_text(json.dumps(report))
    before = paths[0].read_bytes()
    with pytest.raises(ValueError, match=match):
        export_cohort(paths, output)
    assert paths[0].read_bytes() == before
    assert not output.exists()


@pytest.mark.parametrize("single", [False, True])
@pytest.mark.parametrize("defect,match", [
    ("submission_and_score", "submission trace"),
    ("system_and_cache", "system evaluation trace"),
    ("score_only", "structured score"),
])
def test_exports_reject_report_falsification_even_with_recomputed_caches(staged_cohort, single, defect, match):
    from evaluations.enterprise_journey_review import journeys

    paths, output = staged_cohort
    report = json.loads(paths[0].read_text())
    row = next(r for r in report["rows"] if r["phase"] == "monitoring" and r["arm"] == "luna_signalweave_jev")
    if defect == "submission_and_score":
        row["submission"]["recipients"] = ["outsider"]
        row["score"] = score_submission(
            journeys(report["config"]["seed"])[0], row["period_id"], row["submission"],
            inspected_refs=row["inspected_refs"], asked_owner_topics=row["asked_owner_topics"],
        )
        assert row["score"]["exact"] is False
    elif defect == "system_and_cache":
        row["system_output"]["result"].update(outcome="ignore", delivery_methods=[])
        row["raw_system_decision"].update(
            outcome="ignore", recipients=[], destinations=[], outcome_correct=False,
            recipients_correct=False, agent_changed_outcome=True,
        )
    else:
        row["score"]["exact"] = False
    paths[0].write_text(json.dumps(report))
    with pytest.raises(ValueError, match=match):
        export(paths[0], output) if single else export_cohort(paths, output)
    assert not output.exists()


@pytest.mark.parametrize("defect,match", [
    ("missing_submit", "successful submission"), ("duplicate_submit", "successful submission"),
    ("rejected_submit", "successful submission"), ("malformed_receipt", "receipt"),
    ("wrong_actor", "receipt"), ("invalid_arguments", "arguments"),
    ("missing_native", "native routing trace"), ("duplicate_native", "native routing trace"),
    ("invalid_native", "native routing trace"), ("baseline_native", "native routing trace"),
])
def test_completed_monitoring_requires_unambiguous_successful_trace(staged_cohort, defect, match):
    paths, output = staged_cohort
    trace = paths[0].with_name("trace.jsonl")
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    submit = next(e for e in events if e["kind"] == "tool.result"
                  and "/luna_signalweave_jev/" in e["episode"])
    native = next(e for e in events if e["kind"] == "system.evaluation")
    if defect == "missing_submit":
        events.remove(submit)
    elif defect == "duplicate_submit":
        events.append(copy.deepcopy(submit))
    elif defect == "rejected_submit":
        submit["result"] = {"error": "ValueError", "message": "Citation rejected"}
    elif defect == "malformed_receipt":
        submit["result"] = {"recorded": "true", "delivery_enabled": False}
    elif defect == "wrong_actor":
        submit["actor_role"] = "owner_reviewer"
    elif defect == "invalid_arguments":
        submit["arguments"] = {"outcome": "invalid"}
    elif defect == "missing_native":
        events.remove(native)
    elif defect == "duplicate_native":
        events.append(copy.deepcopy(native))
    elif defect == "invalid_native":
        native["response"] = None
    else:
        native["episode"] = native["episode"].replace("luna_signalweave_jev", "luna_bi")
    trace.write_text("".join(json.dumps(e) + "\n" for e in events))
    with pytest.raises(ValueError, match=match):
        export(paths[0], output)
    assert not output.exists()


def test_single_export_normalizes_recorded_arguments_without_inventing_success(staged_cohort):
    paths, output = staged_cohort
    trace = paths[0].with_name("trace.jsonl")
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    submit = next(e for e in events if e["kind"] == "tool.result")
    # Runner fills optional empty lists; the receipt records raw arguments.
    submit["arguments"].pop("numeric_claims")
    submit["arguments"].pop("claims")
    failed = copy.deepcopy(submit)
    failed["result"] = {"error": "ValueError", "message": "Earlier rejected attempt"}
    failed["arguments"] = {"outcome": "invalid"}
    events.insert(events.index(submit), failed)
    trace.write_text("".join(json.dumps(e) + "\n" for e in events))
    before = paths[0].read_bytes(), trace.read_bytes()
    result = export(paths[0], output)
    assert result["planned_episodes"] == 8
    assert result["acceptance_status"] == result["narrative_gate"] == "unassessed"
    assert (paths[0].read_bytes(), trace.read_bytes()) == before
    compact = json.loads((output / "results.json").read_text())
    assert compact["acceptance_status"] == compact["narrative_gate"] == "unassessed"
    assert "do not authenticate" in result["ledger_limit"]


@pytest.mark.parametrize("retained_submission", [False, True])
def test_failed_episode_distinguishes_rejected_call_from_recorded_submission(staged_cohort, retained_submission):
    from evaluations.enterprise_journey_review import journeys

    paths, output = staged_cohort
    report = json.loads(paths[0].read_text())
    row = next(r for r in report["rows"] if r["phase"] == "monitoring" and r["arm"] == "luna_signalweave_jev")
    row["status"] = "failed"
    trace = paths[0].with_name("trace.jsonl")
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    identity = f"{row['scenario_id']}/{row['arm']}/{row['period_id']}"
    submit = next(e for e in events if e["episode"] == identity and e["kind"] == "tool.result")
    if not retained_submission:
        row["submission"] = None
        submit["result"] = {"error": "ValueError", "message": "Submission rejected"}
        row["raw_system_decision"]["agent_changed_outcome"] = True  # Runner comparison to absent final.
    row["score"] = score_submission(
        journeys(report["config"]["seed"])[0], row["period_id"], row["submission"] or {},
        inspected_refs=row["inspected_refs"], asked_owner_topics=row["asked_owner_topics"],
    )
    row["score"]["exact"] = False
    paths[0].write_text(json.dumps(report))
    trace.write_text("".join(json.dumps(e) + "\n" for e in events))
    result = export(paths[0], output)
    assert result["acceptance_status"] == "not_passed"
    assert result["narrative_gate"] == "unassessed"
    assert result["native_correctness"]["luna_signalweave_jev"]["completed_agent_reports"] == 2
    cases = json.loads((output / "results.json").read_text())["cases"]
    retained = next(r for r in cases if r["phase"] == "monitoring" and r["arm"] == row["arm"])
    assert retained["submission"] == row["submission"]
    assert retained["score"]["exact"] is False


@pytest.mark.parametrize("defect", [
    "fingerprint", "missing_fingerprint", "model", "seed", "effort", "owner_review",
    "max_tool_calls", "owner_review_attempts_per_arm_company", "cap_total", "cap_exceeded",
    "duplicate_company", "duplicate_episode", "missing_episode", "wrong_phase", "dataset",
    "missing_terminal", "foreign_trace", "missing_trace", "incomplete_union", "mixed_jev",
])
def test_cohort_rejects_mixed_duplicate_incomplete_or_unmatched_components(staged_cohort, defect):
    paths, output = staged_cohort
    report = json.loads(paths[1].read_text())
    config = report["config"]
    trace = paths[1].with_name("trace.jsonl")
    if defect == "fingerprint":
        config["source_fingerprint"]["sha256"]["runtime.py"] = "b" * 64
    elif defect == "missing_fingerprint":
        config["source_fingerprint"]["sha256"] = {}
    elif defect in {"model", "seed", "effort", "owner_review", "max_tool_calls",
                    "owner_review_attempts_per_arm_company"}:
        config[defect] = "different"
    elif defect == "cap_total":
        config["max_api_requests"] = 113
    elif defect == "cap_exceeded":
        config["max_api_requests"] = 1
    elif defect == "duplicate_company":
        config["selected_scenario_ids"][0] = "company-0"
    elif defect == "duplicate_episode":
        report["rows"][-1] = report["rows"][0]
    elif defect == "missing_episode":
        report["rows"].pop()
    elif defect == "wrong_phase":
        report["rows"][0]["phase"] = "monitoring"
    elif defect == "dataset":
        config["dataset_digest"] = "wrong"
    elif defect == "missing_terminal":
        events = [json.loads(line) for line in trace.read_text().splitlines()]
        events.remove(next(e for e in events if e["kind"] == "api.response"))
        trace.write_text("".join(json.dumps(e) + "\n" for e in events))
    elif defect == "foreign_trace":
        trace.write_text(trace.read_text() + json.dumps({"kind": "tool.result", "episode": "unknown"}) + "\n")
    elif defect == "missing_trace":
        trace.unlink()
    elif defect == "incomplete_union":
        # Two valid but disjoint components covering only five companies.
        from evaluations.enterprise_journey_review import journeys
        config["selected_scenario_ids"].remove("company-5")
        config["selected_companies"] = 4
        config["dataset_digest"] = dataset_digest(journeys(config["seed"])[1:5])
        report["rows"] = [r for r in report["rows"] if r["scenario_id"] != "company-5"]
        events = [json.loads(line) for line in trace.read_text().splitlines()
                  if not json.loads(line)["episode"].startswith("company-5/")]
        report["usage"] = usage_summary(events)
        trace.write_text("".join(json.dumps(e) + "\n" for e in events))
    else:
        # Reported API-model changes in otherwise balanced request/terminal traces.
        for index, path in enumerate(paths):
            t = path.with_name("trace.jsonl")
            events = [json.loads(line) for line in t.read_text().splitlines()]
            event = next(e for e in events if e["kind"] == "api.response" and e["provider"] == "jev")
            event.update(kind="api.response", response={"model": f"jev-{index}"})
            t.write_text("".join(json.dumps(e) + "\n" for e in events))
            part = report if index == 1 else json.loads(path.read_text())
            part["usage"] = usage_summary(events)
            for row in part["rows"]:
                episode = f"{row['scenario_id']}/{row['arm']}/{row['period_id']}"
                row["usage"] = usage_summary([e for e in events if e["episode"] == episode])
            if index == 0:
                path.write_text(json.dumps(part))
    paths[1].write_text(json.dumps(report))
    with pytest.raises((ValueError, FileNotFoundError)):
        export_cohort(paths, output)
    assert not output.exists()
