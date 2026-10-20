"""Offline contracts for the fresh public owner-to-report pair."""

import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from evaluations import public_owner_report_trial as trial
from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter
from evaluations.bootstrap_scenarios import public_episode
from evaluations.human_report_episode import HumanReportEpisode
from signalweave.models import InsightCard, InsightCardStatus, SourceRef


def _response():
    return {"input_tokens": 20, "input_tokens_details": {"cached_tokens": 5}, "output_tokens": 3}


class FakeNative:
    """Local native boundary; cards can only appear through the author tool."""

    instructions = "Offline native instructions"
    tool_names = (
        "get_signalweave_guide", "search_catalog", "inspect_resource", "list_insight_cards",
        "onboard_insight_card", "get_insight_card", "approve_insight_card",
        "evaluate_insight_card", "get_decision_receipt",
    )

    def __init__(self, adapter, tenant):
        self.adapter = adapter
        self.tenant = tenant
        self.card = None
        self.calls = []
        self.evaluation_receipt = True

    async def list_tools(self):
        return [SimpleNamespace(name=name, description=f"Offline {name}", inputSchema={
            "type": "object", "properties": {}, "additionalProperties": True,
        }) for name in self.tool_names]

    async def call_tool(self, name, args):
        self.calls.append((name, dict(args)))
        if name == "list_insight_cards":
            cards = [] if self.card is None else [self.card]
            return [], {"count": len(cards), "cards": cards}
        if name == "inspect_resource":
            snapshot = await self.adapter.inspect(SourceRef(
                key=args["resource"], adapter=args["adapter"], resource=args["resource"],
                label=args["resource"],
            ))
            return [], snapshot.model_dump(mode="json")
        if name == "onboard_insight_card":
            assert self.card is None, "the author must create the first card in this home"
            source = self.adapter.catalog[0]
            card = InsightCard(
                id="agent-authored-card", title=args["title"],
                what_to_watch="Net sales against the previous complete week.",
                why_watch="Surface a policy-relevant sales decline.",
                decision_guidance="Notify for the agreed decline; otherwise ignore.",
                sources=[SourceRef(key="sales", adapter=source.adapter, resource=source.resource,
                                   label=source.title)],
                principal_id="onboarding-owner", principal_tenant=self.tenant,
                status=InsightCardStatus.DRAFT,
            )
            self.card = card.model_dump(mode="json")
            return [], {"card": self.card}
        if name == "get_insight_card":
            assert self.card is not None
            return [], dict(self.card)
        if name == "approve_insight_card":
            assert self.card is not None
            self.card["status"] = InsightCardStatus.APPROVED.value
            return [], {"card": dict(self.card)}
        if name == "evaluate_insight_card":
            assert self.card is not None
            status = "delivery_disabled" if self.evaluation_receipt else "deferred"
            return [], {
                "receipt": {"card_id": self.card["id"], "card_version": self.card["version"],
                            "idempotency_key": args["idempotency_key"], "status": status},
                "result": {"card_id": self.card["id"]},
            }
        return [], {"ok": True, "tool": name}


def _patch_offline(monkeypatch, tmp_path, *, live, failure=None, verify_execution=True):
    binary = tmp_path / "native-binary"
    codex = tmp_path / "codex-cli"
    key = tmp_path / "test-key"
    binary.write_bytes(b"offline native binary")
    codex.write_bytes(b"offline Codex executable")
    key.write_text("offline-only-test-key")
    args = SimpleNamespace(binary=str(binary), codex_executable=str(codex),
                           key_file=str(key), output=str(tmp_path / "trial-output"), run=live)
    state = {"sequence": [], "contexts": [], "native_context_calls": 0,
             "review_calls": [], "model_calls": [], "native": None, "budget": None}
    binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    codex_hash = hashlib.sha256(codex.read_bytes()).hexdigest()
    monkeypatch.setattr(trial, "verify_binary", lambda _path: {"binary_sha256": binary_hash})

    async def fake_pinned_codex(_path):
        return _pinned(codex, codex_hash)

    monkeypatch.setattr(trial, "pinned_codex", fake_pinned_codex)

    def _unused():
        raise AssertionError("provider, CLI, or native process boundary must remain mocked")

    async def fake_codex(session, **kwargs):
        is_author = isinstance(session, trial.AuthorEpisode)
        arm = "signalweave" if session.native else "baseline"
        stage = "author" if is_author else "report"
        state["model_calls"].append((stage, arm))
        state["sequence"].append((stage, arm))
        state["contexts"].append((stage, arm, dict(session.adapter.period_context)))
        audit = kwargs["audit"]
        audit.emit("api.request", provider="openai", request_id=len(state["sequence"]))
        unknown = failure == "unknown_usage" and stage == "author" and arm == "baseline"
        if not unknown:
            audit.emit("api.response", provider="openai", usage=_response())
        assert kwargs["model"] == "gpt-6-luna"
        assert kwargs["effort"] == "medium"

        if is_author:
            assert set(kwargs["prompt_override"]) == {
                "scenario_id", "company", "brief", "owner_topics", "destinations",
            }
            if failure == "incomplete_author" and arm == "baseline":
                return {"status": "complete", "exit_code": 0, "foreign_tools": []}
            assets = (await session.call("list_company_assets", {}))["assets"]
            asset = assets[0]
            await session.call("read_company_asset", {
                "ref": f"{asset['adapter']}|{asset['resource']}",
            })
            await session.call("read_company_glossary", {})
            await session.call("ask_owner", {"topic": "context_review"})
            await session.call("save_working_notes", {"notes": f"{arm} agent-authored setup notes."})
            card_ids = []
            if session.native:
                await session.call("get_signalweave_guide", {})
                created = await session.call("onboard_insight_card", {"title": "Agent-authored sales policy"})
                card_id = created["card"]["id"]
                await session.call("request_owner_approval", {
                    "kind": "card", "id": card_id, "summary": "Show the authored card for consent.",
                })
                await session.call("approve_insight_card", {"card_id": card_id})
                card_ids = [card_id]
            else:
                await session.call("request_owner_approval", {
                    "kind": "notes", "id": "working", "summary": session.notes,
                })
            await session.call("finish_setup", {
                "card_ids": card_ids, "message": "Current readout and reusable setup are ready.",
                "unresolved": [],
            })
        else:
            assets = (await session.call("list_company_assets", {}))["assets"]
            asset = assets[0]
            await session.call("read_company_asset", {
                "ref": f"{asset['adapter']}|{asset['resource']}",
            })
            if session.native and verify_execution:
                state["budget"].claim()
                audit.emit("api.request", provider="jev", request_id="mock-policy-evaluation")
                audit.emit("api.response", provider="jev", usage={"input_tokens": 100, "output_tokens": 10})
                await session.call("evaluate_insight_card", {
                    "card_id": session.approved_card_id, "idempotency_key": session.run_key,
                })
            await session.call("record_report", {
                "outcome": "ignore", "recipients": [],
                "summary": f"Current-period report; source {asset['adapter']}|{asset['resource']}.",
            })
        return {"status": "complete", "exit_code": 0, "foreign_tools": []}

    async def fake_review(**kwargs):
        arm = "signalweave" if "card" in kwargs["artifact"] else "baseline"
        state["review_calls"].append(arm)
        state["sequence"].append(("review", arm))
        audit = kwargs["audit"]
        audit.emit("api.request", provider="openai", request_id=len(state["sequence"]))
        audit.emit("api.response", provider="openai", usage=_response())
        assert kwargs["model"] == "gpt-6-luna"
        assert kwargs["effort"] == "medium"
        return {"approved": failure != "rejected_review", "reasons": ["Offline review result."]}

    @asynccontextmanager
    async def fake_native_context(_binary, key_file, public, adapter, _audit, root, *, request_budget):
        state["native_context_calls"] += 1
        state["budget"] = request_budget
        assert request_budget.limit == (trial.LIMITS["jev_attempts"] if live else 0)
        assert request_budget.used == 0
        assert not ({"private", "periods", "labels"} & public.keys())
        assert root.is_dir() and not list(root.iterdir())
        if not live:
            assert key_file.read_text() == "synthetic-public-owner-preflight-no-inference"
        home = root / "native-home"
        home.mkdir()
        assert not list(home.iterdir())
        native = FakeNative(adapter, public["scenario_id"])
        native.evaluation_receipt = verify_execution
        state["native"] = native
        canonical_skill = (trial.Path(__file__).resolve().parents[1] / "skills/signalweave/SKILL.md").read_text()
        yield native, canonical_skill

    monkeypatch.setattr(trial, "native_context", fake_native_context)
    monkeypatch.setattr(trial, "codex_episode", fake_codex if live else _unused)
    monkeypatch.setattr(trial, "review_owner_artifact", fake_review if live else _unused)
    return args, state, binary, codex


def _pinned(path, fingerprint):
    return {"path": str(path), "sha256": fingerprint}


def test_opening_brief_is_only_public_business_context():
    fixture = trial.scenario()
    public = public_episode(fixture)
    brief = trial.public_brief(public)
    assert set(brief) == {"scenario_id", "company", "brief", "owner_topics", "destinations"}
    assert "owner_answers" not in brief
    assert "private" not in brief and "periods" not in brief and "period" not in brief
    assert fixture["public"]["company"] == "Juniper Trail Retail"
    assert public["period"]["period_id"] == fixture["public"]["onboarding"]["period_id"]
    assert not ({p["period_id"] for p in fixture["public"]["periods"]} &
                {public["period"]["period_id"]})


@pytest.mark.asyncio
async def test_author_calculator_and_shared_tool_hashes_match():
    public = public_episode(trial.scenario())
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    baseline = trial.AuthorEpisode(public, adapter)
    treatment = trial.AuthorEpisode(public, adapter, FakeNative(adapter, public["scenario_id"]))
    baseline_specs, treatment_specs = await baseline.specs(), await treatment.specs()
    baseline_hashes, treatment_hashes = trial.pin_tools(baseline_specs), trial.pin_tools(treatment_specs)
    shared = set(baseline_hashes) & set(treatment_hashes)
    assert {name for name in shared if baseline_hashes[name] != treatment_hashes[name]} == {
        "finish_setup", "request_owner_approval",
    }
    assert await baseline.call("calculate", {"expression": "(12.5 * 2) - 5"}) == \
        await treatment.call("calculate", {"expression": "(12.5 * 2) - 5"}) == {"value": 20.0}


@pytest.mark.asyncio
async def test_preflight_uses_blank_home_dummy_key_zero_budget_and_no_model_calls(tmp_path, monkeypatch):
    args, state, _binary, _codex = _patch_offline(monkeypatch, tmp_path, live=False)
    report = await trial.run(args)

    assert report["completed"] is True
    assert report["agent_invocations_started"] == report["provider_attempts"] == 0
    assert report["provider_usage_known"] is True
    assert report["initial_native_card_count"] == 0
    assert report["preflight_bridge_fidelity_verified"] is True
    assert state["native"].calls[0][0] == "list_insight_cards"
    assert state["model_calls"] == state["review_calls"] == state["sequence"] == []
    assert state["budget"].limit == state["budget"].used == 0
    author_inventory = report["author_tool_inventories"]
    baseline, treatment = author_inventory["baseline"], author_inventory["signalweave"]
    assert {name for name in baseline if baseline[name] != treatment[name]} == {
        "finish_setup", "request_owner_approval",
    }
    report_inventory = report["report_tool_inventories"]
    assert all(report_inventory["baseline"][name] == digest
               for name, digest in report_inventory["signalweave"].items()
               if name in report_inventory["baseline"])

    exported = json.loads((tmp_path / "trial-output" / "public-onboarding-input.json").read_text())
    assert exported["period"]["period_id"] == trial.scenario()["public"]["onboarding"]["period_id"]
    assert not ({"private", "periods", "labels"} & exported.keys())


@pytest.mark.asyncio
async def test_preflight_fails_on_shared_author_schema_hash_drift(tmp_path, monkeypatch):
    args, state, _binary, _codex = _patch_offline(monkeypatch, tmp_path, live=False)
    original_specs = trial.AuthorEpisode.specs

    async def drifted_specs(self):
        specs = await original_specs(self)
        if self.native:
            next(tool for tool in specs if tool["name"] == "read_company_glossary")["description"] += " changed"
        return specs

    monkeypatch.setattr(trial.AuthorEpisode, "specs", drifted_specs)
    report = await trial.run(args)

    assert "failure" in report and not report.get("completed", False)
    baseline = report["author_tool_inventories"]["baseline"]
    treatment = report["author_tool_inventories"]["signalweave"]
    assert baseline["read_company_glossary"] != treatment["read_company_glossary"]
    assert state["model_calls"] == state["review_calls"] == []


@pytest.mark.asyncio
async def test_live_run_has_six_invocations_uses_fixed_windows_and_authors_card(tmp_path, monkeypatch):
    args, state, _binary, _codex = _patch_offline(monkeypatch, tmp_path, live=True)
    report = await trial.run(args)

    assert report["completed"] is True
    assert state["budget"].used == 1
    assert report["provider_attempts"] == 1
    assert report["agent_invocations_started"] == 6
    assert state["sequence"] == [
        ("author", "baseline"), ("review", "baseline"),
        ("author", "signalweave"), ("review", "signalweave"),
        ("report", "baseline"), ("report", "signalweave"),
    ]
    assert [entry["stage"] for entry in report["episodes"]] == ["author", "author", "report", "report"]
    assert state["native"].calls[0][0] == "list_insight_cards"
    assert state["native"].calls[1][0] == "get_signalweave_guide"
    assert state["native"].calls[2][0] == "onboard_insight_card"
    assert all(name not in {"restore_reviewed_card", "import_sqlite"}
               for name, _args in state["native"].calls)
    assert report["provider_attempts"] == 1

    fixture = trial.scenario()
    contexts = {(stage, arm): context for stage, arm, context in state["contexts"]}
    offset = timedelta(seconds=report["measurement_offset_seconds"])
    onboarding = fixture["public"]["onboarding"]
    selected = fixture["public"]["periods"][2]
    assert contexts[("author", "baseline")]["period_id"] == onboarding["period_id"]
    assert contexts[("author", "signalweave")]["period_id"] == onboarding["period_id"]
    assert contexts[("report", "baseline")]["period_id"] == selected["period_id"]
    assert contexts[("report", "signalweave")]["period_id"] == selected["period_id"]
    capture = datetime.fromisoformat(report["read_clock"])
    for period, context in ((onboarding, contexts[("author", "baseline")]),
                            (selected, contexts[("report", "baseline")])):
        assert datetime.fromisoformat(context["as_of"]) == datetime.fromisoformat(period["as_of"]) + offset
        assert datetime.fromisoformat(context["captured_at"]) == capture
        assert context["as_of"] != context["captured_at"]
    assert all(set(entry["submission"]) == {"outcome", "recipients", "summary"}
               for entry in report["episodes"] if entry["stage"] == "report")


@pytest.mark.asyncio
@pytest.mark.parametrize(("failure", "expected_sequence"), [
    ("incomplete_author", [("author", "baseline")]),
    ("rejected_review", [("author", "baseline"), ("review", "baseline")]),
    ("unknown_usage", [("author", "baseline")]),
])
async def test_setup_failures_stop_before_next_invocation(tmp_path, monkeypatch, failure, expected_sequence):
    args, state, _binary, _codex = _patch_offline(monkeypatch, tmp_path, live=True, failure=failure)
    report = await trial.run(args)

    assert "failure" in report and not report.get("completed", False)
    assert state["sequence"] == expected_sequence
    assert report["agent_invocations_started"] == len(expected_sequence)
    if failure == "unknown_usage":
        assert report["usage_known"] is False
        assert report["usage"] == {"status": "unknown"}


@pytest.mark.asyncio
async def test_unverified_treatment_gate_stops_cohort_but_preserves_completed_report(tmp_path, monkeypatch):
    args, state, _binary, _codex = _patch_offline(
        monkeypatch, tmp_path, live=True, verify_execution=False,
    )
    report = await trial.run(args)

    assert not report.get("completed", False)
    assert report["failure"]["type"] == "RuntimeError"
    assert "integration gate" in report["failure"]["message"].lower()
    treatment_report = next(entry for entry in report["episodes"]
                            if entry["stage"] == "report" and entry["arm"] == "signalweave")
    assert treatment_report["agent"]["status"] == "complete"
    assert treatment_report["submission"]["summary"]
    assert treatment_report["approved_card_execution_verified"] is False
    assert not any(name == "evaluate_insight_card" for name, _args in state["native"].calls)
    assert report["provider_attempts"] == 0
    assert report["provider_usage"] == []
    assert report["agent_invocations_started"] == 6
    assert state["sequence"][-1] == ("report", "signalweave")


@pytest.mark.asyncio
async def test_human_report_sink_has_three_fields_and_latches_first_result():
    public = public_episode(trial.scenario())
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    episode = HumanReportEpisode(public, adapter, notes="Fresh test notes.")
    tools = {tool["name"]: tool for tool in await episode.specs()}
    schema = tools["record_report"]["parameters"]
    assert set(schema["properties"]) == {"outcome", "recipients", "summary"}
    assert schema["required"] == ["outcome", "recipients", "summary"]
    assert "numeric_claims" not in schema["properties"]
    report = {"outcome": "ignore", "recipients": [], "summary": "Routine report."}
    assert await episode.call("record_report", report) == {"recorded": True, "delivery_enabled": False}
    with pytest.raises(ValueError, match="already recorded"):
        await episode.call("record_report", {**report, "summary": "replacement"})
    assert episode.submission == report


@pytest.mark.asyncio
async def test_existing_output_is_never_resumed_or_overwritten(tmp_path, monkeypatch):
    args, state, _binary, _codex = _patch_offline(monkeypatch, tmp_path, live=True)
    output = tmp_path / "trial-output"
    output.mkdir()
    marker = output / "report.json"
    marker.write_text("preserve the interrupted attempt")

    with pytest.raises(FileExistsError):
        await trial.run(args)

    assert marker.read_text() == "preserve the interrupted attempt"
    assert state["native_context_calls"] == 0
    assert state["sequence"] == []
