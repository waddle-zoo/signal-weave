"""Offline preparation/admission controls, not analyst or business efficacy."""
from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evaluations import harbor_handoff_followthrough as trial
from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from signalweave.local_setup import _config_text
from signalweave.models import InsightCard


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def previous():
    return {"notes": "Exact previous notes. Prior errors remain history.\n",
            "briefs": [{"body": "Original brief", "evidence_refs": ["actual-result"]}],
            "queries": [{"arguments": {"sql": "original analyst SQL"},
                         "result": {"rows": [[None, 0, ""]], "truncated": False}}],
            "native_calls": [{"name": "get_insight_card", "result": {"id": "actual-card"}}],
            "private_reference": "NEVER SEED THIS", "expected_findings": ["NOT ANALYST INPUT"]}


@pytest.mark.parametrize("arm", trial.ORDER)
def test_seed_preserves_exact_own_subtrees_without_oracle_or_new_queries(tmp_path, arm):
    old = previous()
    before = deepcopy(old)
    workspace = tmp_path/arm
    trial.seed_workspace(workspace, old, arm)
    assert old == before
    assert (workspace/"working-notes.md").read_text() == old["notes"]
    assert (workspace/"retained/notes.md").read_text() == old["notes"]
    for name in ("briefs", "queries"):
        assert json.loads((workspace/"retained"/(name+".json")).read_text()) == old[name]
    native = workspace/"retained/native_calls.json"
    assert native.exists() is (arm == "signalweave")
    if native.exists():
        assert json.loads(native.read_text()) == old["native_calls"]
    assert not list((workspace/"tool-responses").iterdir())
    for path in workspace.rglob("*"):
        if path.is_file():
            assert "NEVER SEED THIS" not in path.read_text()
            assert "NOT ANALYST INPUT" not in path.read_text()


def test_shared_task_contains_the_job_not_disposition_hints_or_fake_prior_software():
    b, t = trial.task(), trial.task("actual-card")
    assert {k: v for k, v in t["prompt"].items() if k != "approved_card_id"} == b["prompt"]
    assert t["instructions"].startswith(b["instructions"])
    assert b["prompt"]["source_cutoff"] == trial.CUTOFFS[-1]
    for forbidden in ("80", "resolved", "missing response", "SELECT", "recovery", "runner.py"):
        assert forbidden not in json.dumps((b, t))
    assert "already evaluated" in t["instructions"]
    assert trial.LIMITS == {"actors": 2, "jev_requests": 0, "response_seconds": 420,
        "mcp_tools": 30, "workspace_tools": 40, "between_actor_input_stop": 2_500_000,
        "between_actor_uncached_stop": 180_000}


@pytest.mark.parametrize("journal", ["DELETE", "WAL"])
def test_coherent_clone_keeps_actual_card_and_all_receipt_payloads(tmp_path, journal):
    parent, root = tmp_path/"parent", tmp_path/"new"
    old_home = parent/"signalweave/home"
    for p in (old_home, old_home/"state", root/"signalweave"):
        p.mkdir(parents=True, mode=0o700)
    manifest = parent/"signalweave/sources.json"
    write(manifest, {"connections": [{"transport": {"command": ["old-python", "-m",
        "evaluations.harbor_workflow_mcp", "old-active"]}, "resources": [{"sql": "unchanged actual SQL"}]}]})
    (old_home/"typesafe.key").write_text("not-a-live-key\n")
    (old_home/"config.toml").write_text(_config_text({"SIGNALWEAVE_STORE_BACKEND": "sqlite",
        "SIGNALWEAVE_STORE_PATH": "state/signalweave.db", "TYPESAFE_API_KEY_FILE": "typesafe.key",
        "SIGNALWEAVE_MCP_SOURCES_FILE": str(manifest)}))
    for p in (old_home/"config.toml", old_home/"typesafe.key"):
        p.chmod(0o600)
    card = InsightCard(id="actual-card", title="Known work", what_to_watch="Owner rule",
        why_watch="Queue handoff", status="approved", comparison_windows=[]).model_dump(mode="json")
    stored_card = {**card, "compiled_plan": {"card_id": card["id"], "card_version": 1,
        "selected_source_keys": [], "comparison_windows": [], "capabilities": [],
        "card_scope": "Owner rule"}}
    stored_card = InsightCard.model_validate(stored_card).model_dump(mode="json")
    old_db = old_home/"state/signalweave.db"
    calls = []
    with sqlite3.connect(old_db) as db:
        db.execute(f"PRAGMA journal_mode={journal}")
        db.execute("CREATE TABLE insight_cards (id TEXT PRIMARY KEY, payload TEXT)")
        db.execute("CREATE TABLE decision_receipts (idempotency_key TEXT PRIMARY KEY, payload TEXT)")
        db.execute("INSERT INTO insight_cards VALUES (?, ?)", (card["id"], json.dumps(stored_card)))
        for index, cutoff in enumerate(trial.CUTOFFS):
            receipt = {"receipt_id": f"receipt-{index}", "idempotency_key": f"key-{index}", "delivery_enabled": False}
            db.execute("INSERT INTO decision_receipts VALUES (?, ?)", (receipt["idempotency_key"], json.dumps(receipt)))
            calls.append({"name": "evaluate_insight_card", "observation_cutoff": cutoff, "result": {"receipt": receipt}})
    before = trial._store_payloads(old_db)
    restored, last, payloads, parents = trial._clone_native(parent, root, {"approval": {"card": card}, "native_calls": calls})
    assert restored == stored_card and last == calls[-1]["result"]["receipt"]
    assert payloads == before == trial._store_payloads(root/"signalweave/home/state/signalweave.db")
    assert trial._store_payloads(old_db) == before and len(payloads["decision_receipts"]) == 3
    cloned = json.loads((root/"signalweave/sources.json").read_text())
    assert cloned["connections"][0]["resources"] == json.loads(manifest.read_text())["connections"][0]["resources"]
    assert cloned["connections"][0]["transport"]["command"][-1] == str(root/"signalweave/active.sqlite3")
    assert parents == {str(manifest): trial._sha(manifest)}


def completed(**changes):
    result = {"process_complete": True, "provider_attempts": 0, "provider_clean": True,
              "provider_usage": {"known": True}, "usage": {"known": True,
              "usage": {"input_tokens": 100, "uncached_input_tokens": 10}}}
    result.update(changes)
    return result


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    root = tmp_path/"trial"
    root.mkdir(mode=0o700)
    study = {"limits": dict(trial.LIMITS), "arms": {}, "key_file": str(root/"key"),
             "codex": {"path": "NEVER LAUNCH"}, "registry_sha256": "offline"}
    (root/"key").write_text("offline-key")
    for arm in trial.ORDER:
        workspace = root/arm/"workspace"
        workspace.parent.mkdir(mode=0o700)
        trial.seed_workspace(workspace, previous(), arm)
        study["arms"][arm] = {"initial_inventory": trial.workspace_inventory(workspace),
            "read_paths": [str(workspace/"retained"), str(workspace/"tool-responses")]}
        write(root/f"{arm}-task.json", trial.task("actual-card" if arm == "signalweave" else None))
    write(root/"study.json", study)
    proof = {"passed": True, "study_sha256": trial._sha(root/"study.json"),
             "source_tools": ["list_assets", "query_readonly"]}
    write(root/"preflight.json", proof)
    review = root/"review.json"
    write(review, {"approved": True, "reviewer": "Independent offline fixture review",
        "study_sha256": trial._sha(root/"study.json"), "preflight_sha256": trial._sha(root/"preflight.json")})
    monkeypatch.setattr(trial, "verify", lambda *args: None)
    monkeypatch.setattr(trial, "codex_episode", AsyncMock(side_effect=AssertionError("No actor admitted by test")))
    return SimpleNamespace(root=root, study=study, review=review)


def test_admission_requires_exact_study_preflight_and_reviewer(prepared):
    p = prepared
    assert trial.admission(p.root, p.study, "baseline", p.review)["passed"]
    for name, value in (("approved", False), ("reviewer", ""), ("study_sha256", "changed"), ("preflight_sha256", "changed")):
        review = json.loads(p.review.read_text())
        review[name] = value
        wrong = p.root/"wrong-review.json"
        write(wrong, review)
        with pytest.raises(ValueError, match="admission"):
            trial.admission(p.root, p.study, "baseline", wrong)


@pytest.mark.parametrize("fault", ["unknown", "incomplete", "input", "uncached", "provider", "rejected", "unreported"])
def test_between_actor_stops_do_not_reset_or_retry(prepared, fault):
    p = prepared
    (p.root/"baseline.claimed").touch()
    report = completed()
    if fault == "unknown":
        report["usage"]["known"] = False
    elif fault == "incomplete":
        report["process_complete"] = False
    elif fault in {"input", "uncached"}:
        key, cap = (("input_tokens", "between_actor_input_stop") if fault == "input" else
                    ("uncached_input_tokens", "between_actor_uncached_stop"))
        report["usage"]["usage"][key] = trial.LIMITS[cap]
    elif fault == "provider":
        report["provider_attempts"] = 1
    elif fault == "rejected":
        report["provider_clean"] = False
    if fault != "unreported":
        write(p.root/"baseline.json", report)
    with pytest.raises(ValueError):
        trial.admission(p.root, p.study, "signalweave", p.review)
    with pytest.raises(ValueError):
        trial.admission(p.root, p.study, "baseline", p.review)


def test_baseline_first_and_original_input_integrity(prepared):
    p = prepared
    with pytest.raises(ValueError, match="Baseline first"):
        trial.admission(p.root, p.study, "signalweave", p.review)
    (p.root/"baseline/workspace/retained/notes.md").write_text("Changed after review")
    with pytest.raises(ValueError, match="inputs changed"):
        trial.admission(p.root, p.study, "baseline", p.review)


async def test_six_native_reads_reject_evaluation_before_underlying_dispatch():
    def tool(name):
        return SimpleNamespace(name=name)
    server = SimpleNamespace(instructions="Actual instructions", list_tools=AsyncMock(
        return_value=[tool(n) for n in trial.AGENT_PROFILE_TOOLS]), call_tool=AsyncMock(return_value=([], {"original": None})))
    allowed = trial.FollowupReads(server)
    assert {t.name for t in await allowed.list_tools()} == trial.READ_TOOLS
    assert await allowed.call_tool("get_decision_receipt", {"receipt_id": "existing"}) == ([], {"original": None})
    for name in set(trial.AGENT_PROFILE_TOOLS)-trial.READ_TOOLS:
        with pytest.raises(ValueError, match="not evaluation or card mutation"):
            await allowed.call_tool(name, {})
    assert server.call_tool.await_count == 1


def test_zero_budget_rejection_is_not_reported_as_clean_zero_usage():
    audit, budget = Audit(), RequestBudget(0)
    assert trial.provider_clean(audit, budget)
    audit.emit("api.rejected", provider="jev", reason="budget_exhausted")
    assert budget.used == 0 and not trial.provider_clean(audit, budget)


async def test_prepare_passes_the_exact_actor_grants_to_sandbox_without_models(tmp_path, monkeypatch):
    root, parent, repo = tmp_path/"new", tmp_path/"old", tmp_path/"repo"
    public, binary, codex = tmp_path/"public-sdk", tmp_path/"native", tmp_path/"codex"
    public.mkdir()
    for p in (binary, codex):
        p.write_text("Offline executable identity, never launched")
    skill = repo/"skills/signalweave/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("Current bundled skill")
    snapshots = []
    for i, cutoff in enumerate(trial.CUTOFFS):
        path = parent/f"{i}.sqlite3"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"Frozen fixture source")
        snapshots.append({"path": str(path), "cutoff": cutoff, "sha256": trial._sha(path)})
    write(parent/"study.json", {"protocol": trial.journey.PROTOCOL, "snapshots": snapshots})
    for arm in trial.ORDER:
        write(parent/f"recurring-{arm}.json", {**previous(), **completed(), "inputs_unchanged": True, "errors": []})

    def clone(_parent, target, _previous):
        home = target/"signalweave/home"
        home.mkdir(mode=0o700)
        for name in ("typesafe.key", "config.toml"):
            (home/name).write_text("Private fixture")
        write(target/"signalweave/sources.json", {"actual": "retained transport"})
        return {"id": "actual-card"}, {"receipt_id": "actual-receipt"}, {}, {}

    async def install(*args, **kwargs):
        assert args[1:] == ("skills", "install", "--agent", "codex", "--scope", "project")
        installed = kwargs["cwd"]/".agents/skills/signalweave/SKILL.md"
        installed.parent.mkdir(parents=True)
        installed.write_text(skill.read_text())
        return SimpleNamespace(returncode=0, wait=AsyncMock(return_value=0))

    grants = []

    def sandbox(_cli, workspace, canary, private_paths, *, readonly_paths):
        assert str(workspace/"retained") in readonly_paths
        assert str(workspace/"tool-responses") in readonly_paths
        assert str(root/"signalweave/home/typesafe.key") not in readonly_paths
        assert root/"private-canary.txt" in private_paths
        grants.append(readonly_paths)
        return {"provider_requests": 0}

    monkeypatch.setattr(trial, "ROOT", repo)
    monkeypatch.setattr(trial, "verify_binary", lambda *args: {"dirty": False})
    monkeypatch.setattr(trial, "pinned_codex", AsyncMock(return_value={"path": str(codex), "sha256": trial._sha(codex)}))
    monkeypatch.setattr(trial, "method", lambda: {"offline": "frozen"})
    monkeypatch.setattr(trial, "verify", lambda *args: None)
    monkeypatch.setattr(trial, "_clone_native", clone)
    monkeypatch.setattr(trial, "public_paths", lambda w: (public, w/"tool-responses"))
    monkeypatch.setattr(trial, "sandbox_preflight", sandbox)
    monkeypatch.setattr(trial, "verify_trial_registry", AsyncMock(return_value={"registry_sha256": "same-registry"}))
    monkeypatch.setattr(trial.asyncio, "create_subprocess_exec", install)
    monkeypatch.setattr(trial, "codex_episode", AsyncMock(side_effect=AssertionError("No analyst in preparation")))
    result = await trial.prepare(root, parent, binary, codex)
    study = json.loads((root/"study.json").read_text())
    assert result["provider_requests"] == result["frontier_invocations"] == 0
    assert grants == [study["arms"][arm]["read_paths"] for arm in trial.ORDER]
    assert str(root/"signalweave/workspace/.agents") in grants[1]


@pytest.mark.parametrize("fault", [None, "source-mismatch", "provider-rejected"])
async def test_mock_preflight_checks_actual_values_and_rejected_zero_budget(tmp_path, monkeypatch, fault):
    root = tmp_path/"preflight"
    root.mkdir()
    key = root/"key"
    key.write_text("Offline key")
    card = {"id": "actual-card", "status": "approved"}
    receipt = {"receipt_id": "old-receipt", "delivery_enabled": False}
    write(root/"study.json", {"key_file": str(key), "card": card, "receipt": receipt})

    async def native_call(name, arguments):
        if name == "get_insight_card":
            return [], card
        if name == "get_decision_receipt":
            return [], {"receipt": receipt}
        assert name == "inspect_resource" and arguments["resource"] == trial.QUEUE_RESOURCE
        return [], {"evidence": [{"values": {"unknown": None, "number": 0}}]}

    async def source_call(name, arguments):
        assert name == "query_readonly" and arguments["sql"] == trial.QUEUE_SQL
        return [], {"columns": ["unknown", "number"], "rows": [[None, 1 if fault == "source-mismatch" else 0]], "truncated": False}

    @asynccontextmanager
    async def sessions(_study, _root, _arm, audit, budget):
        assert budget.limit == 0
        if fault == "provider-rejected":
            audit.emit("api.rejected", provider="jev")
        source = SimpleNamespace(list_tools=AsyncMock(return_value=[SimpleNamespace(name="query_readonly")]), call_tool=source_call)
        native = SimpleNamespace(list_tools=AsyncMock(return_value=[SimpleNamespace(name=n) for n in trial.AGENT_PROFILE_TOOLS]), call_tool=native_call)
        yield source, native

    monkeypatch.setattr(trial, "verify", lambda *args: None)
    monkeypatch.setattr(trial.journey, "sessions", sessions)
    result = await trial.preflight(root)
    assert result["passed"] is (fault is None) and result["provider_attempts"] == 0
    assert (root/"preflight.json").is_file() and (root/"preflight.claimed").is_file()
    with pytest.raises(FileExistsError):
        await trial.preflight(root)


@pytest.mark.parametrize("save_files", [False, True])
async def test_mock_actor_preserves_accounting_and_separates_deliverables(prepared, monkeypatch, save_files):
    p = prepared
    tools = [SimpleNamespace(name=n, description="Actual source tool", inputSchema={"type": "object"})
             for n in ["list_assets", "query_readonly"]]
    source = SimpleNamespace(list_tools=AsyncMock(return_value=tools))

    @asynccontextmanager
    async def sessions(*args):
        yield source, None

    async def episode(bridge, **kwargs):
        assert kwargs["timeout_seconds"] == 420 and kwargs["max_tool_calls"] == 30
        assert kwargs["max_workspace_tool_calls"] == 40 and kwargs["budget"].limit == 0
        w = p.root/"baseline/workspace"
        assert kwargs["workspace_read_paths"] == [str(w/"retained"), str(w/"tool-responses")]
        (w/"working-notes.md").write_text("Updated reusable procedure")
        if save_files:
            (w/"brief.md").write_text("Actual human answer")
            (w/"evidence").mkdir()
            (w/"evidence/case.json").write_text('{"actual":null}')
        audit = kwargs["audit"]
        audit.emit("api.request", provider="openai", request_id=-1)
        audit.emit("api.response", provider="openai", request_id=-1,
                   usage={"input_tokens": 100, "input_tokens_details": {"cached_tokens": 90}, "output_tokens": 5})
        return {"status": "complete", "final_message": "Human answer even without files"}

    monkeypatch.setattr(trial.journey, "sessions", sessions)
    monkeypatch.setattr(trial, "codex_episode", episode)
    result = await trial.actor(p.root, "baseline", p.review)
    saved = json.loads((p.root/"baseline.json").read_text())
    assert result["process_complete"] and result["usage"]["known"]
    assert saved["provider_clean"] and saved["originals_unchanged"]
    assert saved["deliverables_complete"] is save_files
    assert saved["final_message"] == "Human answer even without files"
    assert trial.admission(p.root, p.study, "signalweave", p.review)["passed"]
    with pytest.raises(ValueError, match="Baseline first"):
        await trial.actor(p.root, "baseline", p.review)
