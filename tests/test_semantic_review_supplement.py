import argparse
import copy
import hashlib
import json
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import tomllib

from evaluations import semantic_review_supplement as supplement
from evaluations.semantic_company import SemanticCompany


def original_run(tmp_path, company="retail"):
    original = tmp_path / ("stable-v2-" + company)
    directory = original / company
    source = SemanticCompany(directory, company)
    source.set_condition("decline")
    publication = source.publish_measurement_refresh()
    source.set_condition("gap")  # The failed review phase stays in the original.
    home = directory / "person/.signalweave"
    (home / "state").mkdir(parents=True)
    for suffix in ("", "-wal", "-shm"):
        (home / ("state/signalweave.db" + suffix)).write_bytes(("private-state" + suffix).encode())
    (home / "openai.key").write_text("original-private-key\n")
    config = {"SIGNALWEAVE_MCP_SOURCES_FILE": str(directory / "sources.json"),
              "SIGNALWEAVE_STORE_PATH": str(home / "state/signalweave.db"),
              "OPENAI_API_KEY_FILE": str(home / "openai.key")}
    (home / "config.toml").write_text("version = 1\n[environment]\n" + "".join(
        f"{key} = {json.dumps(value)}\n" for key, value in config.items()))
    card = {"id": "card-finance", "version": 2, "status": "approved",
            "sources": [{"adapter": "company", "resource": source.canonical_resource}],
            "decision_guidance": "Unchanged owner policy",
            "delivery_methods": [{"outcome": outcome, "destination": "agent://finance"}
                                 for outcome in ("notify", "investigate", "insufficient_data")],
            "context_bindings": [{"entry_id": "definition", "revision": 2, "required_for_action": True}]}
    shared = {"card": card, "context": {"entries": [{"id": "definition", "revision": 2,
              "status": "reviewed", "content": {"body": "Source-owned definition"}}]},
              "handoff": "Retain this old onboarding handoff."}
    prior = {"company": company, "onboarding": {"agent": {"status": "complete"}, "submission": shared},
             "onboarding_checks": {"approved": True, "owner_review_routes": True},
             "measurement_refresh": {"publication": publication},
             "readers": [{"index": index, "arm": arm, "agent": {"status": "complete"},
                          "checks": {"amount": True}} for index in range(10)
                         for arm in ("ordinary_context", "signalweave")],
             "review_handoffs": [{"checks": {"review_owner": False}, "submission": {"recipients": []}}]}
    protocol = {"build": {"binary_sha256": "binary", "source_sha256": "production"},
                "runtime": {"fingerprint": "runtime"}, "seed": 20261025,
                "refresh_after_onboarding": True, "transport": "stdio"}
    (original / "protocol.json").write_text(json.dumps(protocol))
    (original / "report.json").write_text(json.dumps({"complete": False, "stopped": "Original review failed",
                                                    "companies": [prior]}))
    return original, source, protocol, prior


def args_for(tmp_path, original, company="retail"):
    key = tmp_path / "new-provider.key"
    key.write_text("new-private-key\n")
    return argparse.Namespace(original=original, company=company, output=tmp_path / "new-supplement",
                              binary=tmp_path / "binary", key_file=key, codex=tmp_path / "codex", live=True)


def argv_for(args):
    return [item for name in ("binary", "key_file", "codex", "original", "company", "output")
            for item in ("--" + name.replace("_", "-"), str(getattr(args, name)))]


def tree_hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_cli_requires_live_and_an_exclusive_output_before_any_execution(tmp_path):
    args = args_for(tmp_path, tmp_path / "stable-v2-retail")
    with pytest.raises(SystemExit) as error:
        supplement.parse_args(argv_for(args))
    assert error.value.code == 2
    assert not args.output.exists()
    parsed = supplement.parse_args([*argv_for(args), "--live"])
    assert parsed.original == args.original.resolve()
    assert parsed.company == "retail"
    args.output.mkdir()
    (args.output / "keep").write_text("existing attempt")
    with pytest.raises(SystemExit):
        supplement.parse_args([*argv_for(args), "--live"])
    assert (args.output / "keep").read_text() == "existing attempt"


@pytest.mark.asyncio
async def test_imported_runner_also_rejects_unapproved_execution_and_overlapping_paths(tmp_path):
    args = args_for(tmp_path, tmp_path / "stable-v2-retail")
    args.live = False
    with pytest.raises(ValueError, match="--live"):
        await supplement.run(args)
    args.live = True
    args.output = args.original / "nested"
    with pytest.raises(ValueError, match="overlap"):
        await supplement.run(args)
    assert not args.original.exists()


@pytest.mark.parametrize("company", ["retail", "saas", "marketplace"])
def test_closed_successful_onboarding_is_admitted_without_rescoring_failed_handoff(tmp_path, company):
    original, _, protocol, prior = original_run(tmp_path, company)
    before = tree_hashes(original)
    loaded_protocol, loaded_prior = supplement.read_original(original, company)
    assert loaded_protocol == protocol
    assert loaded_prior == prior
    assert loaded_prior["review_handoffs"][0]["checks"]["review_owner"] is False
    assert tree_hashes(original) == before


@pytest.mark.parametrize("change", ["running", "reader_failure", "missing_reader", "unapproved", "no_publication"])
def test_original_admission_rejects_incomplete_or_unqualified_inputs(tmp_path, change):
    original, _, _, _ = original_run(tmp_path)
    path = original / "report.json"
    report = json.loads(path.read_text())
    prior = report["companies"][0]
    if change == "running":
        report.pop("stopped")
    elif change == "reader_failure":
        prior["readers"][0]["checks"]["amount"] = False
    elif change == "missing_reader":
        prior["readers"].pop()
    elif change == "unapproved":
        prior["onboarding"]["submission"]["card"]["status"] = "draft"
    else:
        prior.pop("measurement_refresh")
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        supplement.read_original(original, "retail")


@pytest.mark.parametrize("command", [
    "python -m evaluations.decisions_semantic_trial --output {original}",
    "signalweave serve --home {original}/retail/person/.signalweave",
])
def test_active_original_is_rejected_before_clone_writes(tmp_path, monkeypatch, command):
    original = tmp_path / "stable-v2-retail"
    listing = f"123456 {command.format(original=original)}\n"
    monkeypatch.setattr(supplement.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=listing))
    target = tmp_path / "clone"
    with pytest.raises(RuntimeError, match="still running"):
        supplement.clone_company(original, target, "retail", 20261025, "private")
    assert not target.exists()


def test_closed_guard_ignores_supplement_itself_and_other_company(tmp_path, monkeypatch):
    original = tmp_path / "stable-v2-retail"
    listing = (f"{os.getpid()} python -m evaluations.decisions_semantic_trial --output {original}\n"
               "123456 python -m evaluations.decisions_semantic_trial --output stable-v2-saas\n"
               f"123457 python -m evaluations.semantic_review_supplement --original {original}\n")
    monkeypatch.setattr(supplement.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=listing))
    supplement.assert_original_closed(original, "retail")


@pytest.mark.parametrize("company", ["retail", "saas", "marketplace"])
def test_clone_keeps_original_bytes_private_state_and_existing_publication(tmp_path, monkeypatch, capsys, company):
    original, source, _, prior = original_run(tmp_path, company)
    before = tree_hashes(original)
    target = tmp_path / "clone"
    checked = []

    def closed(*_):
        assert not target.exists()
        checked.append(True)

    monkeypatch.setattr(supplement, "assert_original_closed", closed)
    clone = supplement.clone_company(original, target, company, source.seed, "replacement-private-key")
    assert checked == [True]
    assert clone.expected() == source.expected()
    home = target / "person/.signalweave"
    settings = tomllib.loads((home / "config.toml").read_text())["environment"]
    assert settings["SIGNALWEAVE_MCP_SOURCES_FILE"] == str(target / "sources.json")
    assert settings["SIGNALWEAVE_STORE_PATH"] == str(home / "state/signalweave.db")
    assert settings["OPENAI_API_KEY_FILE"] == str(home / "openai.key")
    assert (home / "openai.key").read_text().strip() == "replacement-private-key"
    for suffix in ("", "-wal", "-shm"):
        assert (home / ("state/signalweave.db" + suffix)).read_bytes() == ("private-state" + suffix).encode()
    backup = supplement.save_ledger_snapshot(clone, target, "original-phase")
    clone.set_condition("quiet")
    publication = prior["measurement_refresh"]["publication"]
    with clone._connect() as db:
        assert clone._data_snapshot_id(db) == publication["data_snapshot_id"] != backup["data_snapshot_id"]
        assert db.execute("SELECT COUNT(*) FROM measurement_publications").fetchone()[0] == 1
        assert db.execute("SELECT DISTINCT activity_bp FROM transactions").fetchall()[0][0] == 10000
    assert tree_hashes(original) == before
    assert not capsys.readouterr().out
    assert (home / "openai.key").stat().st_mode & 0o777 == 0o600


def test_clone_rejects_an_unrecognized_manifest_config_key(tmp_path, monkeypatch):
    original, _, _, _ = original_run(tmp_path)
    config = original / "retail/person/.signalweave/config.toml"
    config.write_text(config.read_text().replace("SIGNALWEAVE_MCP_SOURCES_FILE", "UNKNOWN_MANIFEST_KEY"))
    monkeypatch.setattr(supplement, "assert_original_closed", lambda *_: None)
    with pytest.raises(ValueError, match="MCP source manifest"):
        supplement.clone_company(original, tmp_path / "clone", "retail", 20261025, "private")


def test_protocol_freezes_originals_runtime_and_current_full_helper_set(tmp_path):
    original, _, protocol, _ = original_run(tmp_path)
    args = args_for(tmp_path, original)
    frozen = supplement.freeze_protocol(args, protocol, protocol["build"], protocol["runtime"])
    assert frozen["original_report_sha256"] == supplement.sha256(original / "report.json")
    assert frozen["original_protocol_sha256"] == supplement.sha256(original / "protocol.json")
    assert frozen["protocol_sha256"] == supplement.sha256(supplement.PROTOCOL)
    assert frozen["source_hashes"] == supplement.source_hashes()
    for name in ("evaluations/bootstrap_agent_trial.py", "evaluations/codex_workspace.py",
                 "evaluations/semantic_company.py", "evaluations/decisions_semantic_trial.py"):
        assert name in frozen["source_hashes"]
    assert frozen["plan"] == {"canonical_readers": 0, "review_episodes": 4,
                              "native_policy_contrasts": 8, "required_definition_edits": 1}
    assert "contradicting" in frozen["amendment"]
    assert "equally to ordinary_context and signalweave" in frozen["amendment"]
    assert "no rescoring" in frozen["amendment"]
    assert "duplicated measurement-publication prefix" in frozen["amendment"]
    assert frozen["build"] == frozen["original_build"]
    assert frozen["runtime"] == frozen["original_runtime"]
    with pytest.raises(ValueError, match="differs"):
        supplement.freeze_protocol(args, protocol, {"binary_sha256": "changed"}, protocol["runtime"])
    with pytest.raises(ValueError, match="differs"):
        supplement.freeze_protocol(args, protocol, protocol["build"], {"fingerprint": "changed"})


@pytest.mark.parametrize("replayed", [True, None])
def test_freshness_rejects_replayed_or_missing_flag_even_with_delivery_disabled_receipt(replayed):
    packet = {"replayed": replayed, "receipt": {"status": "delivery_disabled", "idempotency_key": "new-key"}}
    assert not supplement.fresh_receipt(packet, "new-key")
    packet["replayed"] = False
    assert supplement.fresh_receipt(packet, "new-key")
    assert not supplement.fresh_receipt(packet, "different-key")


@pytest.mark.asyncio
async def test_admission_errors_are_preserved_redacted_and_do_not_clone(tmp_path, monkeypatch, capsys):
    original, _, _, _ = original_run(tmp_path)
    args = args_for(tmp_path, original)
    before = tree_hashes(original)
    monkeypatch.setattr(supplement, "assert_original_closed", lambda *_: None)

    def fail(_):
        raise RuntimeError("Never print new-private-key")

    monkeypatch.setattr(supplement, "verify_binary", fail)
    report = await supplement.run(args)
    saved = json.loads((args.output / "report.json").read_text())
    assert report["complete"] is False
    assert saved["failure"] == {"type": "RuntimeError", "message": "Never print [REDACTED]"}
    assert not (args.output / args.company).exists()
    assert tree_hashes(original) == before
    assert not capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["complete", "review_failure", "replayed", "actor_error"])
async def test_cloned_phase_plan_preserves_attempts_and_stops_at_first_new_failure(tmp_path, monkeypatch, mode):
    original, _, protocol, prior = original_run(tmp_path)
    args = args_for(tmp_path, original)
    before = tree_hashes(original)
    monkeypatch.setattr(supplement, "assert_original_closed", lambda *_: None)
    monkeypatch.setattr(supplement, "verify_binary", lambda _: protocol["build"])
    monkeypatch.setattr(supplement, "inventory_native_runtime", lambda *_: protocol["runtime"])

    class Native:
        def __init__(self):
            self.card = copy.deepcopy(prior["onboarding"]["submission"]["card"])

        async def call_tool(self, name, arguments):
            if name == "get_insight_card":
                return [], copy.deepcopy(self.card)
            if name == "retrieve_domain_context":
                return [], copy.deepcopy(prior["onboarding"]["submission"]["context"])
            if name == "bind_insight_context":
                assert arguments["expected_card_version"] == self.card["version"]
                self.card.update(version=3, status="draft")
                return [], copy.deepcopy(self.card)
            if name == "review_insight_card":
                return [], {"approval_handoff": {"arguments_after_owner_confirmation": {
                    "card_id": self.card["id"], "source_scope_confirmations": {"company|metric:net-revenue": "Exact source scope"}}}}
            if name == "approve_insight_card":
                assert arguments["source_scope_confirmations"] == {"company|metric:net-revenue": "Exact source scope"}
                self.card["status"] = "approved"
                return [], copy.deepcopy(self.card)
            if name == "save_domain_context":
                return [], {"status": "draft", "revision": arguments["expected_revision"] + 1}
            assert name == "evaluate_insight_card"
            key = arguments["idempotency_key"]
            definition_edit = key.endswith(":definition-edit")
            condition = key.split(":")[-2]
            outcome = None if definition_edit else {
                "quiet": "ignore", "decline": "notify", "gap": "insufficient_data",
                "definition_conflict": "investigate",
            }[condition]
            return [], {"replayed": mode == "replayed", "result": {
                "outcome": outcome, "evaluator": "openai-decisions",
                "delivery_methods": [] if definition_edit or condition == "quiet" else [{"destination": "agent://finance"}],
                "judgment": {"reason": "context_review_required" if definition_edit else "policy"},
                "source_by_key": {"net": {"evidence": [{"statement": "Actual source evidence retained"}]}},
            }, "receipt": {"delivery_enabled": False, "status": "delivery_disabled", "idempotency_key": key}}

    @asynccontextmanager
    async def native(*_):
        yield Native()

    async def actor(episode, *_):
        await episode.call("read_finance_notes", {})
        if mode == "actor_error":
            raise RuntimeError("Failed actor with new-private-key")
        source_ref = "company|metric:net-revenue"
        message = "Finance: source evidence needs data/definition review before any business conclusion."
        await episode.call("send_finance_review", {
            "destination": "agent://finance", "message": message, "source_refs": [source_ref]})
        await episode.call("submit_report", {
            "outcome": "insufficient_data", "resolution_status": "unresolved", "current": None,
            "previous": None, "recipients": [] if mode == "review_failure" else ["agent://finance"],
            "message": message, "source_refs": [source_ref], "uncertainties": ["Unresolved source evidence"],
        })
        return {"status": "complete"}

    monkeypatch.setattr(supplement, "cloned_native", native)
    monkeypatch.setattr(supplement, "actor", actor)
    report = await supplement.run(args)
    saved = json.loads((args.output / "report.json").read_text())
    assert tree_hashes(original) == before
    assert (args.output / "original-report.json").read_bytes() == (original / "report.json").read_bytes()
    assert saved["revalidated_brief"]["card"]["status"] == "approved"
    assert saved["revalidated_brief"]["card"]["delivery_methods"] == prior["onboarding"]["submission"]["card"]["delivery_methods"]
    assert all(attempt["status"] == "complete" for attempt in saved["operator_calls"])
    for backup in saved["ledger_snapshots"]:
        path = args.output / args.company / backup["path"]
        assert supplement.sha256(path) == backup["sha256"]
    if mode == "complete":
        assert report["complete"]
        assert len(saved["review_handoffs"]) == 4
        assert len(saved["policy_contrasts"]) == 8
        assert len(saved["ledger_snapshots"]) == 9
        assert all(saved["definition_change"]["checks"].values())
        keys = [c["arguments"]["idempotency_key"] for c in saved["operator_calls"]
                if c["tool"] == "evaluate_insight_card"]
        assert len(keys) == len(set(keys)) == 9
    else:
        assert report["complete"] is False
        assert "definition_change" not in saved
        if mode == "replayed":
            assert len(saved["review_handoffs"]) == 4
            assert len(saved["policy_contrasts"]) == 1
            assert saved["policy_contrasts"][0]["checks"]["fresh_receipt"] is False
        else:
            assert len(saved["review_handoffs"]) == 1
            assert saved["policy_contrasts"] == []
            first = saved["review_handoffs"][0]
            assert first["calls"][0]["name"] == "read_finance_notes"
            if mode == "actor_error":
                assert saved["failure"]["message"] == "Failed actor with [REDACTED]"
                assert first["submission"] is None
            else:
                assert first["checks"]["review_owner"] is False
                assert len(first["inbox"]) == 1  # Correct real dispatch does not relax the metadata gate.
