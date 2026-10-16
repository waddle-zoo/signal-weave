"""Opt-in three-call native publication wiring proof, not an analyst benchmark."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.installed_trial_transport import (
    InstalledServer,
    _initialize_mcp_session,
    _jev_proxy,
)
from scripts.binary_provenance import verify_binary
from tests.test_analysis_publication import PUBLICATION, READER

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evaluations/data/analysis-publication-native-v1.json"
PROTOCOL = "analysis-publication-native-v1"
ADMISSION = ROOT / "artifacts" / f"{PROTOCOL}.claimed"
POLICY = (
    "Use the explicitly delegated analyst publication, not unsupported caller context. "
    "Its change values are signed fractions: -0.08 means an eight-percentage-point decline. "
    "If no completed observed activation change is published, or the publication contains "
    "only hypotheses, investigate with the analyst. Notify the Growth owner when a published "
    "observed activation decline is at least five percentage points. Otherwise ignore. "
    "An analyst hypothesis about onboarding is not an established cause; never present it as one."
)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _admit_once(protocol):
    ADMISSION.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(ADMISSION, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(PROTOCOL + "\n")
    assert json.loads(MANIFEST.read_text()) == protocol
    closed = {**protocol, "execution_status": "closed"}
    descriptor, temporary = tempfile.mkstemp(dir=MANIFEST.parent, prefix=".publication-protocol-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(json.dumps(closed, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, MANIFEST)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    assert json.loads(MANIFEST.read_text()) == closed


def _check_packet(packet, card, revision, parent, captured, publication_hash, *, replayed=False):
    receipt, result = packet["receipt"], packet["result"]
    assert packet["replayed"] is replayed
    assert isinstance(receipt["receipt_id"], str) and receipt["receipt_id"]
    assert receipt["receipt_id"] != parent
    assert receipt["card_id"] == card["id"] and receipt["card_version"] == card["version"]
    assert receipt["idempotency_key"] == f"{PROTOCOL}:{revision}"
    assert receipt["parent_receipt_id"] == parent
    assert receipt["workflow_step_key"] == ("investigate" if parent else None)
    assert receipt["delivery_mode"] == "shadow"
    assert receipt["status"] == ("replayed" if replayed else "delivery_disabled")
    assert receipt["delivery_enabled"] is False and receipt["outcome"] == result["outcome"]
    assert result["context"] is None
    source = next(item for item in result["source_contracts"] if item["source_key"] == "analysis")
    assert (source["adapter"], source["resource"]) == ("analysis_publication", "report:product-growth")
    assert datetime.fromisoformat(source["source_captured_at"].replace("Z", "+00:00")) == datetime.fromisoformat(captured)
    assert any(item.get("values") == {
        "claim_kind": "publication_record", "publication_id": PUBLICATION["metadata"]["publication_id"],
        "revision": revision, "publication_sha256": publication_hash,
    } for item in result["evidence"])


def test_live_admission_is_exclusive_and_persists_verified_closure(tmp_path, monkeypatch):
    module = sys.modules[__name__]
    manifest, admission = tmp_path / "protocol.json", tmp_path / "claimed"
    planned = {"protocol": PROTOCOL, "execution_status": "planned"}
    manifest.write_text(json.dumps(planned))
    monkeypatch.setattr(module, "MANIFEST", manifest)
    monkeypatch.setattr(module, "ADMISSION", admission)
    _admit_once(planned)
    assert json.loads(manifest.read_text())["execution_status"] == "closed"
    manifest.write_text(json.dumps(planned))  # Reopening JSON cannot reopen this admission.
    with pytest.raises(FileExistsError):
        _admit_once(planned)


@pytest.mark.parametrize("fault", ["none", "replay-status", "version", "key", "parent", "step", "hash", "source-revision"])
def test_packet_gate_checks_replay_metadata_and_the_actual_source_revision(fault):
    captured = "2026-10-16T00:00:00+00:00"
    card = {"id": "example-card", "version": 1}
    packet = {
        "replayed": True,
        "receipt": {"receipt_id": "receipt-1", "card_id": card["id"], "card_version": 1,
                    "idempotency_key": f"{PROTOCOL}:1", "parent_receipt_id": None, "workflow_step_key": None,
                    "delivery_mode": "shadow", "delivery_enabled": False, "status": "replayed", "outcome": "investigate"},
        "result": {"context": None, "outcome": "investigate",
                   "source_contracts": [{"source_key": "analysis", "adapter": "analysis_publication",
                                         "resource": "report:product-growth", "source_captured_at": captured}],
                   "evidence": [{"values": {"claim_kind": "publication_record",
                                             "publication_id": PUBLICATION["metadata"]["publication_id"],
                                             "revision": 1, "publication_sha256": "a" * 64}}]},
    }
    changes = {"replay-status": ("status", "delivery_disabled"), "version": ("card_version", 2),
               "key": ("idempotency_key", "wrong"), "parent": ("parent_receipt_id", "foreign"),
               "step": ("workflow_step_key", "foreign")}
    if fault in changes:
        key, value = changes[fault]
        packet["receipt"][key] = value
    elif fault in {"hash", "source-revision"}:
        packet["result"]["evidence"][0]["values"]["publication_sha256" if fault == "hash" else "revision"] = "wrong"
    if fault == "none":
        _check_packet(packet, card, 1, None, captured, "a" * 64, replayed=True)
    else:
        with pytest.raises(AssertionError):
            _check_packet(packet, card, 1, None, captured, "a" * 64, replayed=True)


def _fingerprints(binary):
    protocol = json.loads(MANIFEST.read_text())
    protocol["execution_status"] = "planned"
    return {
        "build": verify_binary(binary), "test_sha256": _sha(__file__), "reader_sha256": _sha(READER),
        "source_manifest_template_sha256": _sha(READER.with_name("manifest.example.json")),
        "protocol_sha256": hashlib.sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest(),
        "helpers": {name: _sha(ROOT / name) for name in (
            "evaluations/installed_trial_transport.py", "evaluations/bootstrap_agent_trial.py",
            "scripts/binary_provenance.py", "tests/test_analysis_publication.py",
        )},
    }


def _publication(revision, captured):
    value = deepcopy(PUBLICATION)
    value["source_captured_at"] = captured
    value["metadata"].update(
        revision=revision, published_at=datetime.now(timezone.utc).isoformat(),
        publication_authority="Scripted synthetic analyst publisher; not a real sign-off",
    )
    if revision == 1:
        value["evidence"] = [{
            "source_key": value["source_key"], "statement": "The analyst has not published a completed comparison.",
            "values": {"publication_state": "pending"}, "origin": "source",
            "provenance": ["synthetic-publication:revision-1"],
        }]
    elif revision == 2:
        value["evidence"][0]["statement"] = "Activation may have declined, but no observed comparison has been published."
        value["evidence"][0]["values"]["claim_kind"] = "hypothesis"
    return value


def test_protocol_has_narrow_inference_and_claim_bounds():
    protocol = json.loads(MANIFEST.read_text())
    assert protocol["protocol"] == PROTOCOL
    assert protocol["max_jev_attempts"] == 3 and protocol["automatic_retries"] == 0
    assert protocol["expected_sequence"] == ["investigate", "investigate", "notify"]
    assert "no frontier analyst" in protocol["scope"]


@pytest.mark.skipif(os.getenv("RUN_ANALYSIS_PUBLICATION_NATIVE") != "1",
                    reason="requires current native binary and explicit three-request live Jev authorization")
async def test_native_approved_publication_advances_same_card_without_caller_trust():
    preflight = os.getenv("ANALYSIS_PUBLICATION_PREFLIGHT_ONLY") == "1"
    protocol = json.loads(MANIFEST.read_text())
    if protocol["execution_status"] != "planned":
        pytest.fail("This cohort is closed; no rerun or allowance transfer")
    assert protocol["protocol"] == PROTOCOL and protocol["max_jev_attempts"] == 3
    assert protocol["expected_sequence"] == ["investigate", "investigate", "notify"] and protocol["automatic_retries"] == 0
    binary = Path(os.environ["SIGNALWEAVE_BINARY"]).resolve()
    frozen = _fingerprints(binary)
    if not preflight:
        prior = json.loads(Path(os.environ["ANALYSIS_PUBLICATION_PREFLIGHT"]).read_text())
        assert prior.get("preflight_complete") is True and prior.get("fingerprints") == frozen
        assert prior.get("provider_attempts") == 0 and prior.get("provider_errors") == 0
    output = Path(os.environ["ANALYSIS_PUBLICATION_PROOF_DIR"]).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    audit = Audit(path=output / "trace.jsonl")
    audit.path.touch(mode=0o600)
    budget = RequestBudget(0)  # No inference during setup or scripted owner approval.
    record = {"protocol": PROTOCOL, "scope": protocol["scope"], "fingerprints": frozen,
              "preflight_complete": False, "completed": False, "packets": []}
    proof_path = output / "proof.json"
    proof_path.write_text(json.dumps(record, indent=2) + "\n")
    proof_path.chmod(0o600)
    home = output / "native-home"
    dummy = output / "dummy.key"
    dummy.write_text("synthetic-publication-probe-no-provider-key")
    dummy.chmod(0o600)
    publication_path = output / "publication.json"
    captured = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    publication_path.write_text(json.dumps(_publication(1, captured)))
    manifest = json.loads(READER.with_name("manifest.example.json").read_text())
    manifest["connections"][0]["transport"]["command"] = [sys.executable, str(READER), str(publication_path)]
    source_manifest = output / "sources.json"
    source_manifest.write_text(json.dumps(manifest))
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "TMPDIR", "LANG", "LC_ALL"}}
    env["HOME"] = str(output)
    setup = subprocess.run([
        str(binary), "setup", "--non-interactive", "--home", str(home), "--key-file", str(dummy),
        "--source", "mcp", "--manifest", str(source_manifest), "--tenant", "local",
        "--principal", "publication-protocol-owner", "--agent", "codex", "--no-register-agent",
    ], env=env, capture_output=True, timeout=90)
    assert setup.returncode == 0, "Native setup failed; diagnostics withheld"
    env.update(TYPESAFE_MAX_RETRIES="0", TYPESAFE_API_KEY_FILE=(str(dummy) if preflight else os.environ["TYPESAFE_API_KEY_FILE"]))
    try:
        async with asyncio.timeout(240), _jev_proxy(audit, budget) as proxy:
            env["TYPESAFE_BASE_URL"] = proxy
            params = StdioServerParameters(command=str(binary), args=["serve", "--home", str(home)], env=env)
            with open(os.devnull, "w") as errlog:
                async with stdio_client(params, errlog=errlog) as streams, ClientSession(*streams) as session:
                    initialized = await _initialize_mcp_session(session)
                    native = InstalledServer(session, initialized.instructions, audit)
                    _, created = await native.call_tool("onboard_insight_card", {
                        "title": "Delegated publication protocol", "what_to_watch": "Published activation findings",
                        "why_watch": "Tell the configured owner about an observed material decline.",
                        "decision_guidance": POLICY, "follow_up_guidance": "Have the authorized analyst publish current evidence, then re-evaluate this card. Do not treat a hypothesis as an observed cause.",
                        "selected_sources": [{"ref": "analysis_publication|report:product-growth", "key": "analysis", "required": True}],
                        "delivery_methods": [
                            {"key": "analyst", "outcome": "investigate", "label": "Analyst", "destination": "agent://analyst"},
                            {"key": "growth", "outcome": "notify", "label": "Growth owner", "destination": "agent://growth-owner"},
                        ],
                    })
                    card_id = created["card"]["id"]
                    _, reviewed = await native.call_tool("review_insight_card", {"card_id": card_id})
                    await native.call_tool("approve_insight_card", {
                        **reviewed["approval_handoff"]["arguments_after_owner_confirmation"],
                        "source_selection_reason": "Scripted fixture owner delegates this exact analyst publication for this shadow integration check; claims are not independently verified by source authorization.",
                    })
                    _, approved = await native.call_tool("get_insight_card", {"card_id": card_id, "response_mode": "full"})
                    record["approved_card"] = approved
                    assert approved["status"] == "approved" and budget.used == 0
                    assert not any(event.get("kind") == "api.rejected" for event in audit.events)
                    record["authoring_provider_attempts"] = budget.used
                    assert approved["decision_guidance"] == POLICY
                    _, snapshot = await native.call_tool("inspect_resource", {"adapter": "analysis_publication", "resource": "report:product-growth"})
                    assert snapshot["error"] is None and snapshot["metadata"]["revision"] == 1
                    if preflight:
                        for revision in (2, 3):
                            publication_path.write_text(json.dumps(_publication(revision, captured)))
                            _, revised = await native.call_tool("inspect_resource", {"adapter": "analysis_publication", "resource": "report:product-growth"})
                            assert revised["error"] is None and revised["metadata"]["revision"] == revision
                            assert revised["source_captured_at"] == snapshot["source_captured_at"]
                            assert revised["evidence"][0]["values"]["change"] == -0.08
                            assert revised["evidence"][0]["values"]["claim_kind"] == ("hypothesis" if revision == 2 else "observation")
                            assert revised["evidence"][-1]["values"]["publication_sha256"] == _sha(publication_path)
                    else:
                        # A shared exclusive admission prevents concurrent processes from
                        # independently spending this protocol's request allowance.
                        _admit_once(protocol)
                        record["closure_verified_before_inference"] = True
                        budget.limit = 3  # Preregistered admission only after zero-inference authoring.
                        audit.emit("protocol.inference_admitted", max_attempts=3)
                        parent = None
                        hashes = {}
                        before_policy = json.dumps(approved, sort_keys=True)
                        for revision, expected in enumerate(protocol["expected_sequence"], 1):
                            assert json.loads(MANIFEST.read_text())["execution_status"] == "closed"
                            if revision > 1:
                                publication_path.write_text(json.dumps(_publication(revision, captured)))
                            arguments = {"card_id": card_id, "idempotency_key": f"{PROTOCOL}:{revision}", "response_mode": "full"}
                            if parent:
                                arguments.update(parent_receipt_id=parent, workflow_step_key="investigate")
                            hashes[revision] = _sha(publication_path)
                            before = budget.used
                            _, packet = await native.call_tool("evaluate_insight_card", arguments)
                            record["packets"].append(packet)
                            assert budget.used == before + 1
                            _check_packet(packet, approved, revision, parent, captured, hashes[revision])
                            result = packet["result"]
                            assert result["context"] is None and result["outcome"] == expected
                            assert [route["key"] for route in result["delivery_methods"]] == ["analyst" if expected == "investigate" else "growth"]
                            assert [route["destination"] for route in result["delivery_methods"]] == ["agent://analyst" if expected == "investigate" else "agent://growth-owner"]
                            assert result["workflow"]["action"] == ("retrieve_evidence" if expected == "investigate" else "deliver")
                            if revision == 1:
                                assert result["evidence"][0]["values"] == {"publication_state": "pending"}
                            elif revision == 2:
                                assert result["evidence"][0]["values"]["claim_kind"] == "hypothesis"
                                assert result["evidence"][0]["values"]["change"] == -0.08
                            else:
                                assert result["evidence"][0]["values"]["change"] == -0.08
                                assert result["evidence"][1]["values"]["claim_kind"] == "hypothesis"
                                assert packet["receipt"]["parent_receipt_id"] == parent
                            parent = packet["receipt"]["receipt_id"]
                        before_replay = budget.used
                        _, replayed = await native.call_tool("evaluate_insight_card", {
                            "card_id": card_id, "idempotency_key": f"{PROTOCOL}:1", "response_mode": "full",
                        })
                        assert replayed["replayed"] is True and replayed["result"] == record["packets"][0]["result"]
                        _check_packet(replayed, approved, 1, None, captured, hashes[1], replayed=True)
                        assert replayed["receipt"]["receipt_id"] == record["packets"][0]["receipt"]["receipt_id"]
                        assert budget.used == before_replay
                        _, saved_first = await native.call_tool("get_decision_receipt", {"receipt_id": replayed["receipt"]["receipt_id"]})
                        assert saved_first["receipt"]["status"] == "delivery_disabled"
                        assert saved_first["result"] == record["packets"][0]["result"]
                        record["stored_receipt_status_after_replay"] = saved_first["receipt"]["status"]
                        _, unchanged = await native.call_tool("get_insight_card", {"card_id": card_id, "response_mode": "full"})
                        assert json.dumps(unchanged, sort_keys=True) == before_policy
                        assert budget.used == 3
        assert _fingerprints(binary) == frozen
        record["preflight_complete" if preflight else "completed"] = True
    finally:
        responses = [event for event in audit.events if event.get("kind") == "api.response" and event.get("provider") == "jev"]
        errors = [event for event in audit.events if event.get("kind") in {"api.error", "api.rejected"}]
        record.update(provider_attempts=budget.used, provider_errors=len(errors),
                      provider_usage=[event.get("usage") for event in responses])
        usage_known = len(responses) == budget.used and not errors and all(
            isinstance(item.get("usage"), dict) and all(type(item["usage"].get(key)) is int
            and item["usage"][key] >= 0 for key in ("input_tokens", "output_tokens")) for item in responses
        )
        record["provider_usage_known"] = usage_known
        try:
            record["protocol_closed"] = json.loads(MANIFEST.read_text())["execution_status"] == "closed"
        except (OSError, ValueError, KeyError):
            record["protocol_closed"] = False
        if not preflight and not record["protocol_closed"]:
            record["completed"] = False
        if not usage_known:
            record["completed"] = record["preflight_complete"] = False
        proof_path.write_text(json.dumps(audit.redact(record), indent=2) + "\n")
        assert usage_known
        assert preflight or record["protocol_closed"]
        assert budget.used == 0 if preflight else budget.used <= 3
