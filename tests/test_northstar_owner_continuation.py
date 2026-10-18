"""Continuation method controls, not business accuracy or approval evidence."""
import json

import pytest

from evaluations import northstar_owner_continuation as trial
from examples.analysis_publication.reader import _read_publication


def test_owner_clarification_is_normative_not_prepared_findings():
    assert "Online, Mobile and Marketplace" in trial.OWNER
    assert "10%" in trial.OWNER and "52 weeks earlier" in trial.OWNER
    assert "not card approval" in trial.OWNER
    assert "snapshot" not in trial.OWNER and "484,648" not in trial.OWNER


def test_first_authors_have_same_request_but_baseline_no_unavailable_card_work():
    baseline, request = trial.task("baseline", "clarify")
    treatment, other = trial.task("signalweave", "clarify")
    assert request == other
    assert "SignalWeave" not in baseline and "onboard_insight_card" not in baseline
    assert "clarify-brief.md" in baseline and "Do not approve" in baseline
    assert "operator" in treatment and "replacement draft" in treatment
    assert "same relative files" in baseline


def test_repeat_uses_real_approved_id_and_one_stable_key_without_reonboarding():
    with pytest.raises(ValueError, match="actually approved"):
        trial.task("signalweave", "repeat")
    instructions, request = trial.task("signalweave", "repeat", "actual-reviewed-card")
    assert request["approved_card_id"] == "actual-reviewed-card"
    assert "actual-reviewed-card" in request["idempotency_key"]
    assert "Begin with evaluate_insight_card" in instructions
    assert "same frozen history" in instructions
    _, baseline = trial.task("baseline", "repeat")
    assert "approved_card_id" not in baseline


def test_pending_publication_is_readable_without_prepared_measurements(tmp_path):
    file = tmp_path/"publication.json"
    snapshot = trial.pending_publication()
    file.write_text(json.dumps(snapshot))
    actual = _read_publication(file)
    assert len(actual["evidence"]) == 1
    assert actual["evidence"][0]["values"]["claim_kind"] == "publication_record"
    assert actual["source_captured_at"] is None
    assert actual["metadata"]["capture_status"] == "unknown"
    assert not snapshot["evidence"] and not snapshot.get("observations")
    assert "policy outcomes, alert recommendations" in trial.publication_reference()


def test_declared_budget_covers_whole_continuation_not_each_phase():
    assert trial.LIMITS["actors"] == len(trial.ORDER) == 4
    assert trial.ORDER == ("clarify-baseline", "clarify-signalweave", "repeat-baseline", "repeat-signalweave")
    assert trial.LIMITS["jev_requests"] == 2
    assert "examples/analysis_publication/reader.py" in trial.method()


def test_owner_review_binds_both_actual_reports_card_source_and_current_publication(tmp_path):
    from evaluations.harbor_workflow_preflight import _sha

    publication = tmp_path/"signalweave/workspace/analysis-publication.json"
    publication.parent.mkdir(parents=True)
    publication.write_text("actual publication")
    artifacts = {}
    for name in ("clarify-baseline", "clarify-signalweave"):
        p = tmp_path/f"{name}.json"
        p.write_text(json.dumps({"process_complete": True, "protocol_ok": True}))
        artifacts[name] = _sha(p)
    for name in ("owner-card.json", "operator-source-inspection.json"):
        (tmp_path/name).write_text("actual reviewed object")
        artifacts[name] = _sha(tmp_path/name)
    review = {"protocol": trial.PROTOCOL, "artifacts": artifacts, "publication_sha256": _sha(publication),
              "approved_for_shadow": True, "reviewer_type": "simulated_expert", "reviewer": "Exercise reviewer",
              "reason": "Read actual source and procedure", "owner_confirmation": "I approve only this shadow run",
              "source_selection_reason": "Confirmed exact delegated source", "assessments": {"baseline": "Reviewed own work", "signalweave": "Reviewed own work"}}
    trial.reviewed_artifacts(tmp_path, review)
    publication.write_text("changed after review")
    with pytest.raises(ValueError, match="Published input changed"):
        trial.reviewed_artifacts(tmp_path, review)
    review["publication_sha256"] = _sha(publication)
    review["owner_confirmation"] = ""
    with pytest.raises(ValueError, match="Explicit attributed"):
        trial.reviewed_artifacts(tmp_path, review)
