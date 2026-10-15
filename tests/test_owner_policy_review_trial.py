"""Research harness contracts; inference fixtures are not live evidence."""

import json
from types import SimpleNamespace

import pytest

from evaluations import owner_policy_review_trial as research
from evaluations.owner_policy_review_trial import LIMIT, Probe, cases, decode, questions
from signalweave.typesafe_adapter import JevJudger


def test_fixed_budget_labels_separate_and_positive_controls():
    fixture = list(cases())
    assert len(fixture) == LIMIT == 12
    assert len({c["id"] for c in fixture}) == LIMIT
    assert sum(all(v == "consistent" for v in c["expected"].values()) for c in fixture) == 4
    assert all(set(c["state"]) == {"owner_requirements", "draft"} for c in fixture)
    assert set(questions()) == {"decision_rules", "delivery_mapping"}


@pytest.mark.parametrize("choice,probabilities,accept", [
    ("consistent", {"consistent": .8, "inconsistent": .1, "unclear": .1}, True),
    ("consistent", {"consistent": .79, "inconsistent": .1, "unclear": .11}, False),
    ("unclear", {"consistent": 0., "inconsistent": 0., "unclear": 1.}, False),
    ("consistent", {"consistent": .8, "inconsistent": .1, "unclear": .11}, False),
    ("consistent", {"consistent": float("nan"), "inconsistent": .1, "unclear": .1}, False),
    ("consistent", {"consistent": True, "inconsistent": 0., "unclear": 0.}, False),
    ("consistent", {"consistent": .2, "inconsistent": .7, "unclear": .1}, False),
    ("consistent", {}, False),
    ("invented", {"consistent": 1., "inconsistent": 0., "unclear": 0.}, False),
])
def test_invalid_or_uncertain_answer_never_accepts(choice, probabilities, accept):
    assert decode(SimpleNamespace(choice=choice, probabilities=probabilities))["accept"] is accept


async def test_budget_before_transport_and_no_hidden_label_state(monkeypatch):
    calls = []

    async def transport(self, *, state, questions, stage):
        calls.append(state)
        return SimpleNamespace(choices={}, model="offline-contract", usage=None)

    monkeypatch.setattr(JevJudger, "_system_one_with_retry", transport)
    probe = Probe("offline-test")
    for case in cases():
        result = await probe.check(case["state"])
        assert all(not a["accept"] for a in result["answers"].values())
    with pytest.raises(RuntimeError, match="budget"):
        await probe.check({})
    assert len(calls) == LIMIT
    assert all(set(state) == {"owner_requirements", "draft"} for state in calls)


def test_invalid_answer_retains_json_safe_diagnostics():
    result = decode(SimpleNamespace(choice="unexpected", probabilities={"consistent": float("nan")}))
    assert not result["valid"] and not result["accept"]
    assert result["raw"] == {"choice": "unexpected", "probabilities": {"consistent": {"nonfinite": "nan"}}}
    json.dumps(result, allow_nan=False)


async def test_interruption_retains_pending_case_and_never_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "load_api_key", lambda _: "offline-test")

    async def interrupted(self, state):
        self.attempts += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(Probe, "check", interrupted)
    output = tmp_path / "interrupted"
    with pytest.raises(KeyboardInterrupt):
        await research.trial(output, tmp_path / "unused-key")
    report = json.loads((output / "report.json").read_text())
    assert report["planned_cases"] == 12
    assert report["status"] == "running" and report["passed"] is False
    assert report["attempts_reserved"] == 1
    assert report["cases"][0]["status"] == "pending"


async def test_failures_stay_in_denominator_without_false_detection_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "load_api_key", lambda _: "offline-test")

    async def failed(self, state):
        self.attempts += 1
        raise OSError("never persist this exception text")

    monkeypatch.setattr(Probe, "check", failed)
    output = tmp_path / "failed"
    await research.trial(output, tmp_path / "unused-key")
    encoded = (output / "report.json").read_text()
    report = json.loads(encoded)
    assert "never persist" not in encoded
    assert report["status"] == "complete" and report["passed"] is False
    assert len(report["cases"]) == report["attempts"] == 12
    assert all(r["status"] == "error" and not r["exact"] and not r["would_accept"] for r in report["cases"])
