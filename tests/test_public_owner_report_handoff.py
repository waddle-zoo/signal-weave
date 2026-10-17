"""Accounting and consent checks for a paused author, not business evidence."""

import hashlib
import json

import pytest

from evaluations import public_owner_report_trial as trial
from tests.test_public_owner_report_trial import _patch_offline, _response


def prior_handoff(tmp_path, binary, codex, monkeypatch):
    notes = "The baseline author's original saved business definition and policy."
    entry = {"arm": "baseline", "stage": "author", "agent": {"status": "complete"},
             "notes": notes, "setup": {"card_ids": [], "message": "Saved setup", "unresolved": ["Independent review pending"]},
             "owner_requests": [{"kind": "notes", "id": "working", "saved_artifact": {"notes": notes}}], "native_calls": []}
    report = {"protocol": trial.PROTOCOL, "preflight_only": False, "usage_known": True, "runner_sha256": "c" * 64,
              "scenario_sha256": hashlib.sha256(json.dumps(trial.scenario(), sort_keys=True).encode()).hexdigest(),
              "build": {"binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()},
              "codex": {"sha256": hashlib.sha256(codex.read_bytes()).hexdigest()},
              "agent_invocations_started": 1, "provider_attempts": 0, "episodes": [entry],
              "usage": {"input_tokens": 20, "cached_input_tokens": 5, "uncached_input_tokens": 15, "output_tokens": 3, "responses": 1}}
    events = [{"kind": "api.request", "provider": "openai", "episode": "baseline:setup"},
              {"kind": "api.response", "provider": "openai", "episode": "baseline:setup", "usage": _response()}]
    report_path, trace_path = tmp_path / "prior-report.json", tmp_path / "prior-trace.jsonl"
    report_path.write_text(json.dumps(report))
    trace_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    public_input = tmp_path / "public-onboarding-input.json"
    public_input.write_text(json.dumps(trial.public_episode(trial.scenario())))
    manifest = tmp_path / "frozen-manifest.json"
    manifest.write_text(json.dumps({
        "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        "runner_sha256": "c" * 64,
        "public_input_sha256": hashlib.sha256(public_input.read_bytes()).hexdigest(),
    }))
    monkeypatch.setattr(trial, "HANDOFF_MANIFEST", manifest)
    return report_path, trace_path, report


async def test_recovery_reviews_exact_notes_without_retrying_or_waiving_pending_items(tmp_path, monkeypatch):
    args, state, binary, codex = _patch_offline(monkeypatch, tmp_path, live=True)
    report_path, trace_path, original = prior_handoff(tmp_path, binary, codex, monkeypatch)
    args.baseline_handoff_report, args.baseline_handoff_trace = report_path, trace_path
    review = trial.review_owner_artifact
    observed_notes = []

    async def capture_review(**kwargs):
        observed_notes.append(kwargs["artifact"]["notes"])
        return await review(**kwargs)

    monkeypatch.setattr(trial, "review_owner_artifact", capture_review)
    result = await trial.run(args)
    assert result["completed"]
    assert result["protocol"] == trial.HANDOFF_PROTOCOL
    assert result["agent_invocations_started"] == 6
    assert result["new_agent_invocations_started"] == 5
    assert result["usage"]["responses"] == 6 and result["new_usage"]["responses"] == 5
    assert result["usage"]["input_tokens"] == result["new_usage"]["input_tokens"] + 20
    assert result["provider_attempts"] == 1
    assert state["sequence"] == [("review", "baseline"), ("author", "signalweave"),
        ("review", "signalweave"), ("report", "baseline"), ("report", "signalweave")]
    assert "Independent review pending" in observed_notes[0]
    assert observed_notes[0].startswith(original["episodes"][0]["notes"])
    assert result["episodes"][0]["setup"]["unresolved"] == ["Independent review pending"]
    assert json.loads(report_path.read_text()) == original
    assert result["initial_native_card_count"] == 0


async def test_rejected_handoff_review_stops_before_new_author_or_report(tmp_path, monkeypatch):
    args, state, binary, codex = _patch_offline(monkeypatch, tmp_path, live=True, failure="rejected_review")
    args.baseline_handoff_report, args.baseline_handoff_trace, _ = prior_handoff(tmp_path, binary, codex, monkeypatch)
    result = await trial.run(args)
    assert not result.get("completed", False)
    assert state["sequence"] == [("review", "baseline")]
    assert result["agent_invocations_started"] == 2 and result["new_agent_invocations_started"] == 1
    assert result["provider_attempts"] == 0


async def test_prior_author_consumes_the_original_invocation_budget(tmp_path, monkeypatch):
    args, state, binary, codex = _patch_offline(monkeypatch, tmp_path, live=True)
    args.baseline_handoff_report, args.baseline_handoff_trace, _ = prior_handoff(tmp_path, binary, codex, monkeypatch)
    monkeypatch.setattr(trial, "LIMITS", {**trial.LIMITS, "agent_invocations": 1})
    result = await trial.run(args)
    assert not result.get("completed", False)
    assert state["sequence"] == []
    assert result["agent_invocations_started"] == 1 and result["new_agent_invocations_started"] == 0


@pytest.mark.parametrize("fault", ["unknown-usage", "provider-call", "wrong-fixture", "changed-notes", "missing-trace-response"])
def test_handoff_loader_rejects_invalid_or_uncharged_evidence(tmp_path, monkeypatch, fault):
    binary, codex = tmp_path / "native", tmp_path / "codex"
    binary.write_bytes(b"offline binary")
    codex.write_bytes(b"offline CLI")
    report_path, trace_path, original = prior_handoff(tmp_path, binary, codex, monkeypatch)
    if fault == "unknown-usage":
        original["usage_known"] = False
    elif fault == "provider-call":
        original["provider_attempts"] = 1
    elif fault == "wrong-fixture":
        original["scenario_sha256"] = "wrong"
    elif fault == "changed-notes":
        original["episodes"][0]["notes"] = "Edited after owner consent"
    elif fault == "missing-trace-response":
        trace_path.write_text(json.dumps({"kind": "api.request", "provider": "openai"}) + "\n")
    report_path.write_text(json.dumps(original))
    with pytest.raises(ValueError):
        trial.load_baseline_handoff(report_path, trace_path,
            hashlib.sha256(json.dumps(trial.scenario(), sort_keys=True).encode()).hexdigest(),
            {"binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()},
            {"sha256": hashlib.sha256(codex.read_bytes()).hexdigest()})
