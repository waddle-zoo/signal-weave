"""Offline evidence-packet contract checks."""

import copy
import json

import pytest

from evaluations.report_review_packet import build_report_review_packet


def fixture_data():
    protocol = "reports-v1"
    clock = "2026-10-15T10:00:00+00:00"
    report = {"protocol": protocol, "cohort_status": "stopped", "planned_episode_count": 6, "episodes": []}
    events = []
    specs = [("baseline", "period-old", "2026-10-01T00:00:00+00:00", None, "ignore", []),
             ("signalweave", "period-new", "2026-10-08T00:00:00+00:00", "card-opaque", "notify", ["route-opaque"]),
             ("baseline", "period-mid", "2026-10-04T00:00:00+00:00", None, "ignore", []),
             ("signalweave", "period-later", "2026-10-11T00:00:00+00:00", "card-opaque", "notify", ["route-opaque"])]
    for arm, period_id, cutoff, card_id, outcome, routes in specs:
        episode_id, key = f"{arm}:{period_id}", f"{protocol}:{period_id}"
        period = {"period_id": period_id, "as_of": cutoff, "captured_at": clock}
        prompt = {"period": period, "card_id": card_id, "idempotency_key": key if card_id else None,
                  "accepted_context": {"accepted_policy": {"id": "card-opaque", "version": 4}}}
        events.append({"kind": "api.request", "provider": "openai", "episode": episode_id,
                       "prompt": "instructions\n" + json.dumps(prompt, sort_keys=True)})
        submission = {"outcome": outcome, "recipients": routes, "evidence_refs": ["adapter|resource"],
                      "summary": f"Recorded {outcome} for {period_id}.", "diagnostic": "kept"}
        report["episodes"].append({"arm": arm, "period_id": period_id, "agent": {"status": "complete", "final_message": "Draft recorded."}, "submission": submission})
        events.append({"kind": "source.read", "episode": episode_id, "ref": "adapter|resource", "snapshot": {"captured_at": clock, "source_captured_at": clock, "observations": [{"value": period_id}]}})
        events.append({"kind": "tool.result", "name": "submit_analysis", "episode": episode_id, "arguments": copy.deepcopy(submission), "result": {"recorded": True, "delivery_enabled": False, "audit_note": "preserved"}})
        if card_id:
            result_routes = [{"key": route} for route in routes]
            receipt = {"receipt_id": f"receipt-{period_id}", "card_id": card_id, "card_version": 4,
                       "idempotency_key": key, "delivery_mode": "shadow", "status": "delivery_disabled",
                       "delivery_enabled": False, "outcome": outcome, "delivery_method_keys": list(routes)}
            native = {"receipt": receipt, "result": {"card_id": card_id, "outcome": outcome, "delivery_methods": result_routes}}
            events.append({"kind": "tool.result", "name": "evaluate_insight_card", "episode": episode_id, "arguments": {"card_id": card_id, "idempotency_key": key, "response_mode": "compact"}, "result": native})
    report["episodes"].append({"arm": "baseline", "period_id": "period-incomplete", "agent": {"status": "timed_out"}})
    return report, events


def build(report, events):
    return build_report_review_packet(report, events, {"owner_policy": "review supplied policy"},
                                      {"gates": ["evidence", "usefulness"]})


def test_packet_preserves_actual_period_sources_submissions_and_separate_coordinates():
    packet, coordinates = build(*fixture_data())
    assert packet["case_counts"] == {"completed": 4, "observed": 5, "incomplete": 1,
                                     "planned": 6, "unrun": 1}
    assert packet["timing_interpretation"] == (
        "reporter_period.as_of is assigned measurement cutoff; captured_at is separate read clock; "
        "capture age is not proof of metric freshness"
    )
    cases = {case["reporter_period"]["period_id"]: case for case in packet["cases"]}
    old, new = cases["period-old"], cases["period-new"]
    assert old["actual_measurement_cutoff"] == "2026-10-01T00:00:00+00:00"
    assert new["actual_measurement_cutoff"] == "2026-10-08T00:00:00+00:00"
    assert old["actual_read_clock"] == new["actual_read_clock"]
    assert old["source_truth"][0]["source_snapshot_capture_age_hours"] == 0
    assert new["source_truth"][0]["source_snapshot_capture_age_hours"] == 0
    assert old["recorded_report"]["summary"].startswith("Recorded ignore")
    assert old["verified_workflow_receipts"] == []
    assert new["successful_submit_analysis"]["result"]["delivery_enabled"] is False
    assert new["successful_submit_analysis"]["result"]["audit_note"] == "preserved"
    receipt = new["verified_workflow_receipts"][0]["receipt"]
    assert receipt["receipt_id"] == "receipt-period-new"
    assert receipt["card_version"] == 4
    assert new["verified_workflow_receipts"][0]["native_outcome"] == "notify"
    assert "probabilities" not in receipt
    assert set(new["verified_workflow_receipts"][0]) == {
        "call_arguments", "receipt", "native_outcome", "native_routes",
    }
    assert all(not {"arm", "episode"} & case.keys() for case in packet["cases"])
    assert {value["arm"] for value in coordinates.values()} == {"baseline", "signalweave"}
    assert all(case["id"].startswith("case-") for case in packet["cases"])


def test_order_is_deterministic_and_inputs_are_not_mutated():
    report, events = fixture_data()
    originals = copy.deepcopy((report, events))
    packet, coordinates = build(report, events)
    reversed_packet, reversed_coordinates = build(
        {**report, "episodes": list(reversed(report["episodes"]))}, list(reversed(events)))
    assert packet == reversed_packet
    assert coordinates == reversed_coordinates
    assert (report, events) == originals


def test_agent_and_native_judgments_may_disagree_and_are_both_preserved():
    report, events = fixture_data()
    episode = report["episodes"][1]
    episode["submission"].update(outcome="investigate", recipients=["agent-route"])
    submit = next(event for event in events if event.get("name") == "submit_analysis"
                  and event.get("episode") == "signalweave:period-new")
    submit["arguments"].update(outcome="investigate", recipients=["agent-route"])
    packet, _ = build(report, events)
    case = next(case for case in packet["cases"] if case["reporter_period"]["period_id"] == "period-new")
    native = case["verified_workflow_receipts"][0]
    assert case["proposed_outcome"] == "investigate"
    assert case["policy_triggered_routes"] == ["agent-route"]
    assert native["receipt"]["outcome"] == "notify"
    assert native["native_routes"] == ["route-opaque"]


@pytest.mark.parametrize("failure", ["wrong_period", "duplicate"])
def test_prompt_period_and_cardinality_are_enforced(failure):
    report, events = fixture_data()
    request = next(event for event in events if event.get("episode") == "baseline:period-old")
    if failure == "wrong_period":
        prompt = json.loads(request["prompt"].splitlines()[-1])
        prompt["period"]["period_id"] = "another-period"
        request["prompt"] = "instructions\n" + json.dumps(prompt, sort_keys=True)
    else:
        events.append(copy.deepcopy(request))
    error = "mismatched reporter period" if failure == "wrong_period" else "exactly one matching prompt"
    with pytest.raises(ValueError, match=error):
        build(report, events)


@pytest.mark.parametrize("field,value", [("idempotency_key", "reports-v1:older-period"), ("receipt_id", " ")])
def test_stale_or_unidentified_native_receipt_is_rejected(field, value):
    report, events = fixture_data()
    native = next(event for event in events if event.get("name") == "evaluate_insight_card")
    native["result"]["receipt"][field] = value
    with pytest.raises(ValueError, match="mismatched or delivering receipt"):
        build(report, events)


@pytest.mark.parametrize("field", ["as_of", "captured_at"])
def test_naive_reporter_clocks_are_rejected(field):
    report, events = fixture_data()
    request = next(event for event in events if event.get("episode") == "baseline:period-old")
    prompt = json.loads(request["prompt"].splitlines()[-1])
    prompt["period"][field] = "2026-10-01T00:00:00"
    request["prompt"] = "instructions\n" + json.dumps(prompt, sort_keys=True)
    with pytest.raises(ValueError, match="timezone"):
        build(report, events)


@pytest.mark.parametrize("has_read_clock,expected_field,expected_age", [
    (True, "captured_at", 0), (False, None, None),
])
def test_capture_clock_fallback_and_unknown_age_are_explicit(has_read_clock, expected_field, expected_age):
    report, events = fixture_data()
    for source in (event for event in events if event.get("kind") == "source.read"):
        source["snapshot"].pop("source_captured_at")
        if not has_read_clock:
            source["snapshot"].pop("captured_at")
    packet, _ = build(report, events)
    assert all(snapshot["capture_clock_field_used"] == expected_field
               and snapshot["source_snapshot_capture_age_hours"] == expected_age
               for case in packet["cases"] for snapshot in case["source_truth"])
