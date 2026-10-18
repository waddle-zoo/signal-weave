"""Formative study admission controls, not business outcome results."""
import json

import pytest

from evaluations import harbor_workflow_journey as shared
from evaluations import redwood_workflow_journey as study
from evaluations.harbor_workflow_preflight import _sha


def completed(inputs=1000, uncached=100, attempts=0):
    return {"process_complete": True, "usage": {"known": True,
        "usage": {"input_tokens": inputs, "uncached_input_tokens": uncached}},
        "provider_attempts": attempts, "provider_usage": {"known": True}}


def test_authors_and_recurrence_share_the_same_allowance(tmp_path):
    shared.write(tmp_path/"onboarding-baseline.json", completed(1_000_000))
    shared.write(tmp_path/"onboarding-signalweave.json", completed(1_000_000))
    assert study.admission(tmp_path) == 0
    shared.write(tmp_path/"recurring-baseline-1.json", completed(1_000_000))
    with pytest.raises(ValueError, match="Cumulative"):
        study.admission(tmp_path)


@pytest.mark.parametrize("failure", ["claim", "usage", "process", "provider", "uncached", "six-actors"])
def test_no_extra_or_retried_actor_after_a_stop(tmp_path, failure):
    if failure == "claim":
        shared._private_file(tmp_path/"onboarding-baseline.claimed", "interrupted")
    elif failure == "six-actors":
        for arm in shared.ARMS:
            shared.write(tmp_path/f"onboarding-{arm}.json", completed())
            for index in (1, 2):
                shared.write(tmp_path/f"recurring-{arm}-{index}.json", completed())
    else:
        result = completed()
        if failure == "usage":
            result["usage"]["known"] = False
        elif failure == "process":
            result["process_complete"] = False
        elif failure == "provider":
            result["provider_usage"]["known"] = False
        else:
            result["usage"]["usage"]["uncached_input_tokens"] = study.LIMITS["between_actor_uncached_stop"]
        shared.write(tmp_path/"onboarding-baseline.json", result)
    with pytest.raises(ValueError):
        study.admission(tmp_path)


def test_owner_reference_contains_intent_not_future_measurements():
    assert study.OWNER["recipient_keys"] == list(study.OWNER["destinations"])
    assert not {"expected_outcome", "expected_counts", "oracle", "future_cutoffs"} & study.OWNER.keys()
    assert study.LIMITS["frontier_invocations"] == 6 and study.LIMITS["jev_requests"] == 6


def test_expert_review_of_actual_author_files_is_pinned_for_all_later_checks(tmp_path):
    authors = {}
    for arm in shared.ARMS:
        value = {"process_complete": True, "notes": "The actual reusable notes",
            "episode": {"final_message": "Actual first readout"}, "artifact_manifest": {},
            "card": {"id": "c", "status": "draft"} if arm == "signalweave" else None,
            "approval_handoff": {"arguments_after_owner_confirmation": {"card_id": "c"}}}
        shared.write(tmp_path/f"onboarding-{arm}.json", value)
        authors[arm] = value
    review = {"reviewer": "Delegated fictional data expert", "reviewer_type": "simulated_expert",
        "approved_for_shadow_recurrence": True, "reason": "Read both actual messages and files",
        "source_selection_reason": "Confirmed selected completed-shipment scope",
        "assessments": {arm: "Reviewed policy and evidence" for arm in shared.ARMS},
        "artifacts": {arm: shared.digest({"message": v["episode"]["final_message"],
            "notes": v["notes"], "card": v["card"]}) for arm, v in authors.items()},
        "author_report_sha256": {arm: _sha(tmp_path/f"onboarding-{arm}.json") for arm in shared.ARMS}}
    path = tmp_path/"review.json"
    shared.write(path, review)
    first = study.freeze_review(tmp_path, path)
    assert first == study.freeze_review(tmp_path, path)
    assert first[2] == _sha(path)
    review["reason"] = "Changed the interpretation after observing recurrence"
    path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="review changed"):
        study.freeze_review(tmp_path, path)


def test_note_history_recovers_only_actual_successful_saves_without_rewriting_them(tmp_path):
    trace = tmp_path/"author.jsonl"
    events = [
        {"kind": "tool.result", "name": "save_working_notes", "arguments": {"notes": "Full original runbook"}, "result": {"saved": True}},
        {"kind": "tool.ingress", "name": "save_working_notes", "arguments": {"notes": "Not completed"}},
        {"kind": "tool.result", "name": "save_working_notes", "arguments": {"notes": "Failed write"}, "result": {"saved": False}},
        {"kind": "tool.result", "name": "save_working_notes", "arguments": {"notes": "Addendum"}, "result": {"saved": True}},
    ]
    trace.write_text("\n".join(json.dumps(event) for event in events))
    before = trace.read_bytes()
    assert study.saved_note_versions(trace) == ["Full original runbook", "Addendum"]
    assert trace.read_bytes() == before
