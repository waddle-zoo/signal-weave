import json
from types import SimpleNamespace

import pytest

from evaluations.watch_evidence_trial import RecordedJudger, cases


def test_trial_has_balanced_domains_without_case_labels_in_inference_inputs():
    rows = list(cases())
    assert len(rows) == 12
    assert len({r[0] for r in rows}) == 12
    assert {state: sum(r[3] == state for r in rows) for state in ("present", "absent", "unknown")} == {
        "present": 3, "absent": 3, "unknown": 6,
    }
    for name, card, snapshot, _expected in rows:
        encoded = json.dumps({"card": card.model_dump(mode="json"), "source": snapshot.model_dump(mode="json")})
        assert name not in encoded
        assert "expected_watch" not in encoded
        assert snapshot.error is None
        assert snapshot.contract.source_status == "healthy"
        assert card.compiled_plan is not None
        assert len(card.watch_for) == 1


async def test_live_attempt_budget_is_enforced_before_transport(monkeypatch):
    judger = RecordedJudger("offline-test")
    judger.calls = [{}] * 12
    with pytest.raises(RuntimeError, match="budget exhausted"):
        await judger._system_one_with_retry(state={}, questions={}, stage="test")


async def test_interrupted_trial_cannot_leave_a_green_partial_report(monkeypatch, tmp_path):
    import evaluations.watch_evidence_trial as harness
    from signalweave.models import Outcome, WatchStatus

    async def one_success_then_interrupt(engine, card, snapshots):
        if engine.judger.calls:
            raise KeyboardInterrupt("test interruption")
        engine.judger.calls.append({"offline_transport": True})
        return SimpleNamespace(result=SimpleNamespace(
            watch_results=[SimpleNamespace(status=WatchStatus.PRESENT, probabilities={
                "present": .98, "absent": .01, "unknown": .01,
            })], outcome=Outcome.NOTIFY, evidence_plan=SimpleNamespace(missing_slot_keys=[]),
            delivery_methods=[SimpleNamespace(key="owner")], model_dump=lambda **kwargs: {},
        ))

    monkeypatch.setattr(harness, "load_api_key", lambda _: "offline-test")
    monkeypatch.setattr(harness.InsightEngine, "evaluate", one_success_then_interrupt)
    output = tmp_path / "partial"
    with pytest.raises(KeyboardInterrupt):
        await harness.trial(output, "unused")
    report = json.loads((output / "report.json").read_text())
    assert len(report["cases"]) == 1
    assert all(report["cases"][0]["checks"].values())
    assert report["planned_cases"] == 12
    assert report["status"] == "running"
    assert report["passed"] is False
