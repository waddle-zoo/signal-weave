"""Offline orchestration contracts, not business-outcome evidence."""

import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluations import retained_owner_periods as trial
from evaluations.domain_context_onboarding_trial import usage_totals
from signalweave.models import InsightCard, SourceRef


def patch_trial(tmp_path, monkeypatch, *, live=True, unknown_usage=False):
    root = tmp_path / "prior"
    root.mkdir()
    owned = root / "private-native-state"
    home = owned / "native-home"
    home.mkdir(parents=True)
    (home / "config.toml").write_text("test-only placeholder")
    fixture, _, _ = trial.attach_steward_notes(trial.scenario(), trial.NOTES)
    public = trial.public_episode(fixture)
    asset = next(a for a in public["catalog"] if a["contract"].get("roles") == ["primary"])
    card = InsightCard(id="unit-owned-card", title="Offline card", what_to_watch="Sales", why_watch="Test orchestration",
                       status="approved", sources=[SourceRef(key="sales", adapter=asset["adapter"], resource=asset["resource"], label=asset["title"])])
    canonical = (Path(__file__).resolve().parents[1] / "skills/signalweave/SKILL.md").read_text()
    authors = [{"arm": arm, "stage": "author", "notes": "Previously authored notes", "setup": {"unresolved": []},
                "independent_review": {"approved": True}, **({"card": card.model_dump(mode="json")} if arm == "signalweave" else {})}
               for arm in ("baseline", "signalweave")]
    prior = {"protocol": "public-explicit-owner-v5", "completed": True, "usage_known": True,
             "agent_invocations_started": 6, "episodes": authors, "usage": {}, "measurement_offset_seconds": 0,
             "installed_skill_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
             "scenario_sha256": hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest()}
    (root / "report.json").write_text(json.dumps(prior))
    (root / "trace.jsonl").write_text("{}\n")
    manifest = json.loads(trial.MANIFEST.read_text())
    manifest.update(prior_report_sha256=trial.digest(root / "report.json"), prior_trace_sha256=trial.digest(root / "trace.jsonl"))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(trial, "MANIFEST", path)
    binary, codex, key = (tmp_path / name for name in ("binary", "codex", "key"))
    for p in (binary, codex, key):
        p.write_text("offline-only-" + p.name)
    monkeypatch.setattr(trial, "verify_binary", lambda _: {"source_sha256": "source", "binary_sha256": trial.digest(binary)})
    monkeypatch.setattr(trial, "source_fingerprint", lambda: "source")

    async def pinned(_):
        return {"path": str(codex), "sha256": trial.digest(codex)}

    monkeypatch.setattr(trial, "pinned_codex", pinned)
    state = {"credentials": [], "calls": [], "prompts": [], "model_calls": [], "budget": None}

    async def credential(_binary, supplied_home, supplied_key):
        assert supplied_home == home
        state["credentials"].append(supplied_key.read_text())

    monkeypatch.setattr(trial, "credential", credential)

    @asynccontextmanager
    async def native(_binary, _key, supplied_public, adapter, audit, supplied_owned, *, request_budget):
        assert supplied_owned == owned and not ({"private", "periods"} & supplied_public.keys())
        state["budget"] = request_budget

        class Native:
            async def call_tool(self, name, arguments):
                state["calls"].append(name)
                if name == "get_insight_card":
                    return [], card.model_dump(mode="json")
                if name == "inspect_resource":
                    result = await adapter.inspect(card.sources[0])
                    return [], result.model_dump(mode="json")
                if name == "evaluate_insight_card":
                    request_budget.claim()
                    audit.emit("api.request", provider="jev")
                    audit.emit("api.response", provider="jev", usage={"input_tokens": 10, "output_tokens": 2})
                    return [], {"receipt": {"card_id": card.id, "card_version": card.version,
                                "idempotency_key": arguments["idempotency_key"], "delivery_enabled": False,
                                "status": "decision_deferred"}, "result": {"card_id": card.id}}
                raise AssertionError("No authoring, approval or unknown tools in this replay")

        yield Native(), canonical

    monkeypatch.setattr(trial, "native_context", native)

    async def actor(session, **kwargs):
        state["model_calls"].append(session.treatment)
        state["prompts"].append(kwargs["prompt_override"])
        audit = kwargs["audit"]
        audit.emit("api.request", provider="openai")
        if session.treatment:
            await session.call("evaluate_insight_card", {"card_id": session.approved_card_id, "idempotency_key": session.run_key})
        await session.call("record_report", {"outcome": "ignore", "recipients": [], "summary": "Deliberately arbitrary mock report; not a quality score"})
        if not unknown_usage:
            audit.emit("api.response", provider="openai", usage={"input_tokens": 20, "output_tokens": 3, "input_tokens_details": {"cached_tokens": 5}})
        return {"status": "complete"}

    monkeypatch.setattr(trial, "codex_episode", actor)
    args = SimpleNamespace(prior=str(root), binary=str(binary), codex_executable=str(codex),
                           output=str(tmp_path / "output"), run=live, key_file=str(key))
    return args, state, root


async def test_four_fresh_reports_no_authoring_no_import_and_no_quality_inference(tmp_path, monkeypatch):
    args, state, _ = patch_trial(tmp_path, monkeypatch)
    result = await trial.run(args)
    assert result["completed"] is True and result["card_unchanged"] is True
    assert state["model_calls"] == [False, True, True, False]
    assert result["agent_invocations_started"] == 4 and result["provider_attempts"] == 2
    assert state["credentials"][-1] == "synthetic-retained-periods-no-inference"
    assert all(e.get("native_evaluation_verified") for e in result["episodes"] if e["arm"] == "signalweave")
    # Native deferral is not silently called a failed agent report; wrong final
    # routing is recorded separately, not discarded or turned into a pass.
    assert any(not e["routing_check_only"]["matches"] for e in result["episodes"])
    assert not any("expected" in p or "private" in p for p in state["prompts"])
    assert not any(name in {"approve_insight_card", "onboard_insight_card"} for name in state["calls"])


async def test_preflight_reads_actual_source_shape_and_spends_nothing(tmp_path, monkeypatch):
    args, state, _ = patch_trial(tmp_path, monkeypatch, live=False)
    result = await trial.run(args)
    assert result["completed"] is True
    assert result["agent_invocations_started"] == result["provider_attempts"] == 0
    assert state["model_calls"] == [] and state["calls"] == ["get_insight_card", "inspect_resource", "inspect_resource", "get_insight_card"]
    assert state["budget"].limit == 0


async def test_unknown_usage_stops_without_retry_and_replaces_live_copy(tmp_path, monkeypatch):
    args, state, _ = patch_trial(tmp_path, monkeypatch, unknown_usage=True)
    result = await trial.run(args)
    assert not result.get("completed") and result["usage_known"] is False
    assert state["model_calls"] == [False]
    assert state["credentials"][-1] == "synthetic-retained-periods-no-inference"


@pytest.mark.parametrize("fault", ["report", "trace", "home"])
def test_missing_or_changed_original_is_not_reconstructed(tmp_path, monkeypatch, fault):
    _, _, root = patch_trial(tmp_path, monkeypatch)
    if fault == "home":
        (root / "private-native-state/native-home/config.toml").unlink()
    else:
        (root / ("report.json" if fault == "report" else "trace.jsonl")).write_text("changed")
    with pytest.raises(ValueError):
        trial.load_prior(root)


def test_manifest_selects_unreported_indices_not_private_outcomes():
    manifest = json.loads(trial.MANIFEST.read_text())
    assert manifest["period_indices"] == [0, 1]
    assert manifest["limits"]["agent_invocations"] == 4
    assert "labels" not in manifest and "outcomes" not in manifest
    assert usage_totals([])["input_tokens"] == 0
