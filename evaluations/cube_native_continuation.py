"""Opt-in continuation of the closed public-install Cube pilot, never product code.

The original installed home is retained. Source drift, expert reapproval and a
source-owned data correction precede ten paired readers. Stops are retained, not
rescored; independent prose review and actual Codex registry discovery remain
separate requirements even when the structured gates pass.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import jwt

from evaluations.bootstrap_agent_trial import Audit
from evaluations.cube_fixture_control import capture, postgres
from evaluations.cube_native_trial import CubeEpisode, grade
from evaluations.cube_revision_probe import connect, expected_credit_adjustment, source_environment
from evaluations.cube_source import CubeCompany
from evaluations.decisions_semantic_trial import PROMPTS, actor, reader_instructions, save
from evaluations.installed_trial_transport import _source_server, _SourceSession
from evaluations.semantic_company import SemanticCompany
from scripts.binary_provenance import verify_binary
from signalweave.models import Evidence, SourceRef

ROOT = Path(__file__).resolve().parents[1]


class PublishedCubeCompany(CubeCompany):
    """Adds a declared fictional source-owner correction, not inferred Cube history."""
    publication = None

    def notes(self):
        return [*super().notes(), *([self.publication] if self.publication else [])]

    async def inspect(self, source):
        snapshot = await super().inspect(source)
        if self.publication and source.resource == self.canonical_resource:
            snapshot.evidence.append(Evidence(
                source_key=source.key, statement=self.publication["body"],
                values=self.publication["identities"], provenance=self.publication["provenance"]))
        return snapshot


def revision_checks(submission, frozen, expected, *, treatment):
    checks = grade(submission, frozen, SimpleNamespace(expected=lambda _: expected))
    # The prior reviewed r3 policy is not authority for the new r4 meaning. A
    # frontier agent may report attributed current r4 facts while requesting
    # review; do not demand that it suppress supported measurements.
    checks["policy"] = (submission or {}).get("outcome") in {"deferred", "investigate", "insufficient_data"}
    checks["recipients"] = (submission or {}).get("recipients") == ["agent://finance"]
    checks["unresolved"] = (submission or {}).get("resolution_status") == "unresolved"
    return checks


def native_checks(packet, stored, card, frozen, expected, *, revision):
    result, receipt = stored["result"], stored["receipt"]
    checks = {
        "exact_card": result.get("card_id") == card["id"] and receipt.get("card_id") == card["id"],
        "exact_version": receipt.get("card_version") == card["version"],
        "delivery_disabled": receipt.get("delivery_enabled") is False,
    }
    if revision:
        judgment = result.get("judgment", {})
        checks.update(
            native_deferred=result.get("outcome") is None and result.get("delivery_methods") == [],
            native_reason=judgment.get("reason") == "context_review_required",
            native_no_provider=judgment.get("provider_call_attempted") is False and judgment.get("provider_call_attempts") == 0,
            native_no_action=packet.get("policy_action_available") is False,
        )
    else:
        outcome = "notify" if expected["change_pct"] is not None and expected["change_pct"] < -10 else "ignore"
        checks.update(
            native_outcome=result.get("outcome") == outcome,
            native_routes=[route["destination"] for route in result.get("delivery_methods", [])] == (["agent://finance"] if outcome == "notify" else []),
            native_context_current=stored.get("current_context_dependencies", {}).get("required_current") is True,
            native_source=any(source.get("resource") == frozen["resource"] and source.get("contract") == frozen["contract"]
                              for source in result.get("source_contracts", [])),
        )
        facts = [item["values"] for item in result.get("evidence", [])
                 if item.get("values", {}).get("data_snapshot_id") == frozen["metadata"]["data_snapshot_id"]]
        checks["native_measurements"] = any(
            values.get("metric_revision") == frozen["metadata"]["metric_revision"]
            and values.get("unit") == frozen["observations"][0]["unit"]
            and values.get("current_period") == "2026-09" and values.get("previous_period") == "2026-08"
            and all(type(values.get(key)) in (int, float) and abs(Decimal(str(values[key])) - Decimal(str(expected[key]))) <= Decimal("0.005")
                    for key in ("current", "previous")) for values in facts)
    return checks


def expected_from_phase(phase, oracle):
    amounts = expected_credit_adjustment(phase, oracle)
    current, previous = amounts["2026-09"], amounts["2026-08"]
    return {"metric_id": oracle.metric_id, "current": current, "previous": previous,
            "change_pct": (current - previous) / previous * 100 if previous else None}


def backup_state(person, path):
    with path.open("xb"):
        pass
    path.chmod(0o600)
    with sqlite3.connect(person / ".signalweave/state/signalweave.db") as source, sqlite3.connect(path) as destination:
        source.backup(destination)


async def run(args):
    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    pilot = json.loads((args.pilot / "report.json").read_text())
    probe = json.loads((args.revision_probe / "report.json").read_text())
    if not pilot.get("pilot_complete") or not probe.get("complete"):
        raise ValueError("Require the closed passing install pilot and actual source-revision probe")
    person = args.pilot / "person"
    binary = person / ".local/bin/signalweave"
    identity = verify_binary(binary)
    if identity["source_sha256"] != pilot["build"]["source_sha256"]:
        raise ValueError("Actual published runtime changed")
    backup_state(person, root / "native-before.db")
    info = json.loads((args.fixture / "fixture.json").read_text())
    oracle = SemanticCompany(args.fixture / "ledger", info["company"], seed=info["seed"])
    before = capture(args, oracle)
    if any(before[field] != probe["after"][field] for field in ("raw_rows_sha256", "model_sha256", "semantic_view_sql")):
        raise ValueError("Source phase differs from the closed revision probe")
    helpers = [path for path in (ROOT / "evaluations").glob("*.py") if path.name in {
        "cube_native_continuation.py", "cube_native_trial.py", "cube_revision_probe.py", "cube_source.py",
        "cube_fixture_control.py", "semantic_company.py", "decisions_semantic_trial.py",
        "installed_trial_transport.py", "codex_trial_transport.py", "codex_workspace.py", "bootstrap_agent_trial.py"}]
    helpers += [ROOT / "skills/signalweave/SKILL.md", ROOT / "evaluations/protocols/cube-native-2026-10-25.json"]
    save(root / "protocol.json", {
        "protocol": json.loads((ROOT / "evaluations/protocols/cube-native-2026-10-25.json").read_text()),
        "source_hashes": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in helpers},
        "pilot_report_sha256": hashlib.sha256((args.pilot / "report.json").read_bytes()).hexdigest(),
        "probe_report_sha256": hashlib.sha256((args.revision_probe / "report.json").read_bytes()).hexdigest(),
        "cohort_prompts": PROMPTS, "postgres_before": before,
        "auth_scope": "Existing Codex login with research MCP proxy to actual public native binary; not registered-entry autodiscovery.",
    })
    key = (person / ".signalweave/openai.key").read_text().strip()
    audit = Audit(path=root / "native-audit.jsonl", secrets=(key,))
    environment = dict(line.split("=", 1) for line in (args.fixture / "private.env").read_text().splitlines())
    token = jwt.encode({"sub": "finance-readonly", "exp": int(time.time()) + 10800}, environment["SW_CUBE_API_SECRET"], algorithm="HS256")
    endpoint = json.loads((args.pilot / "sources.json").read_text())["connections"][0]["transport"]["url"]
    report = {"complete": False, "structured_complete": False, "build": identity, "revision_readers": [], "readers": [],
              "pending": ["independent prose review", "whole-study audit including separate registered-entry evidence"],
              "provider_usage_instrumented": False}
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{info['port']}/cubejs-api/v1/", headers={"Authorization": token}, trust_env=False) as client:
        company = PublishedCubeCompany(client, oracle)
        await company.refresh_catalog()
        async with _source_server(_SourceSession(company, audit, company.tenant_id), stable_url=endpoint):
            async def continuation(server):
                ref = SourceRef(key="phase", adapter="company", resource="metric:net-revenue", label="Revenue")
                frozen = (await company.inspect(ref)).model_dump(mode="json")
                expected = expected_from_phase(before, oracle)

                async def reader(arm, question, index, notes, target, *, revision=False):
                    episode = CubeEpisode(company, server if arm == "signalweave" else None, notes=notes)
                    run_key = f"{root.name}:{'revision' if revision else 'reader'}:{index}:{arm}"
                    result = await actor(episode, Audit(path=root / f"{'revision' if revision else 'reader'}-{index}-{arm}.jsonl", secrets=(key,)),
                        args.codex, reader_instructions(arm == "signalweave"),
                        {"question": question, "run_key": run_key, "as_of": "2026-10-25"})
                    checks = (revision_checks(episode.submission, frozen, target, treatment=arm == "signalweave") if revision
                              else grade(episode.submission, frozen, SimpleNamespace(expected=lambda _: target)))
                    checks["agent_complete"] = result["status"] == "complete"
                    if not revision:
                        checks["resolved"] = (episode.submission or {}).get("resolution_status") == "resolved"
                    if arm == "signalweave":
                        calls = [call for call in episode.calls if call["name"] == "evaluate_insight_card"]
                        packets = episode.native_packets
                        checks["native_called_once"] = len(calls) == 1 and calls[0]["arguments"].get("idempotency_key") == run_key
                        checks["fresh_key_receipt"] = len(packets) == 1 and packets[0].get("replayed") is False and packets[0].get("receipt", {}).get("idempotency_key") == run_key
                        stored = None
                        if len(packets) == 1:
                            stored = (await server.call_tool("get_decision_receipt", {"idempotency_key": run_key}))[1]
                            card = pilot["onboarding"]["submission"]["card"] if revision else report["reapproval"]["submission"]["card"]
                            checks.update(native_checks(packets[0], stored, card, frozen, target, revision=revision))
                        if revision:
                            checks["no_policy_call"] = len(packets) == 1 and packets[0]["result"]["judgment"].get("provider_call_attempted") is False
                        else:
                            checks["decisions_provider"] = len(packets) == 1 and packets[0]["result"].get("evaluator") == "openai-decisions"
                    row = {"arm": arm, "case": index, "question": question, "agent": result, "submission": episode.submission,
                           "checks": checks, "calls": episode.calls, "native_packets": episode.native_packets, "frozen_source": frozen,
                           "native_audit": stored if arm == "signalweave" else None,
                           "human_review": "pending independent review"}
                    report["revision_readers" if revision else "readers"].append(row)
                    save(root / "report.json", report)
                    print(json.dumps({"stage": "revision" if revision else "cohort", "case": index, "arm": arm, "passed": all(checks.values())}), flush=True)
                    if not all(checks.values()):
                        raise ValueError("Reader structured gate failed; preserve this attempt without rescore")

                for arm in ("ordinary_context", "signalweave"):
                    await reader(arm, "Prepare Finance's September versus August revenue review on our previously agreed reporting basis. Check whether that basis still holds before giving a business conclusion.",
                                 0, pilot["onboarding"]["submission"], expected, revision=True)

                # An explicit fictional owner consent event, not inferred from a
                # passing test or a provider outcome. Agent performs every edit.
                consent = {
                    "actor": "fictional-finance-owner", "basis": "explicit simulation owner consent",
                    "decision": "Approve the active source-owned net revenue definition that now subtracts credits. Preserve the exact archival periods, >10% decline policy and Finance routes. Delegate technical definition review, pinning and card reapproval to the expert agent. Never send or schedule.",
                    "source_definition": frozen["contract"], "prior_card_id": pilot["onboarding"]["submission"]["card_id"],
                }
                save(root / "owner-consent.json", consent)
                maintenance = CubeEpisode(company, server, onboarding=True, notes=pilot["onboarding"]["submission"])
                instructions = ((ROOT / "skills/signalweave/SKILL.md").read_text() +
                    "\nThis is a fictional owner-authorized maintenance session. Use only the exposed tools. Inspect current source meaning, revise the SAME shared context entry and SAME card rather than create duplicates. "
                    "Review the revised shared definition, bind its exact reviewed revision as required, review and approve the existing card within the explicit owner delegation. Keep current values out of the shared definition. "
                    "Use finish_onboarding to capture the reapproved card/context and a concise handoff. Do not send or schedule.")
                response = await actor(maintenance, Audit(path=root / "reapproval.jsonl", secrets=(key,)), args.codex,
                                       instructions, consent, onboarding=True)
                report["reapproval"] = {"agent": response, "submission": maintenance.submission, "calls": maintenance.calls}
                save(root / "report.json", report)
                if response["status"] != "complete" or not maintenance.submission:
                    raise ValueError("Expert reapproval did not complete")
                updated = maintenance.submission
                old = pilot["onboarding"]["submission"]
                dependency = (await server.call_tool("inspect_insight_context", {"card_id": updated["card_id"]}))[1]
                report["reapproval_checks"] = {
                    "same_card": updated["card_id"] == old["card_id"], "same_context": updated["context_id"] == old["context_id"],
                    "version_increased": updated["card"]["version"] > old["card"]["version"],
                    "required_current": dependency["required_current"] is True,
                    "context_revision_increased": updated["context"]["entries"][0]["revision"] > old["context"]["entries"][0]["revision"],
                    # Content sanity is not semantic verification; independent
                    # review of the actual revised entry is still mandatory.
                    "new_meaning_recorded": "credit" in updated["context"]["entries"][0]["content"]["body"].lower()
                        and frozen["metadata"]["metric_revision"] in updated["context"]["entries"][0]["content"]["body"],
                    "comparison_scope_preserved": all(updated["card"][field] == old["card"][field] for field in (
                        "comparison_windows", "max_source_age_hours", "numeric_conditions", "evidence_requirements")),
                    "source_scope_preserved": [{key: value for key, value in source.items() if key != "label"} for source in updated["card"]["sources"]]
                        == [{key: value for key, value in source.items() if key != "label"} for source in old["card"]["sources"]],
                    "destinations_preserved": sorted((route["outcome"], route["destination"]) for route in updated["card"]["delivery_methods"])
                        == sorted((route["outcome"], route["destination"]) for route in old["card"]["delivery_methods"]),
                    "reviewed_revision_pinned": any(binding["entry_id"] == updated["context_id"] and binding["required_for_action"]
                        and binding["revision"] == updated["context"]["entries"][0]["revision"] for binding in updated["card"]["context_bindings"]),
                }
                if not all(report["reapproval_checks"].values()):
                    raise ValueError("Reapproval postcondition failed")
                backup_state(person, root / "native-reapproved.db")

                # Source-owned correction on the disposable Postgres only. The
                # calculation/model remains unchanged, unlike the prior phase.
                count = postgres(args, "SELECT COUNT(*) FROM transactions WHERE period='2026-09' AND activity_bp=8200;").stdout.strip()
                if count != "48":
                    raise ValueError("Source correction precondition differs from the preregistered seed")
                postgres(args, "UPDATE transactions SET activity_bp=10000 WHERE period='2026-09' AND activity_bp=8200;")
                after = capture(args, oracle)
                expected = expected_from_phase(after, oracle)
                changed = (await company.inspect(ref)).model_dump(mode="json")
                report["correction_checks"] = {
                    "data_changed": before["raw_rows_sha256"] != after["raw_rows_sha256"],
                    "same_model": before["model_sha256"] == after["model_sha256"],
                    "same_view": before["semantic_view_sql"] == after["semantic_view_sql"],
                    "same_query": frozen["metadata"]["cube_query"] == changed["metadata"]["cube_query"],
                    "new_result": frozen["metadata"]["data_snapshot_id"] != changed["metadata"]["data_snapshot_id"],
                    "current_correct": abs(Decimal(str(changed["observations"][0]["current"])) - expected["current"]) <= Decimal("0.005"),
                    "previous_correct": abs(Decimal(str(changed["observations"][0]["previous"])) - expected["previous"]) <= Decimal("0.005"),
                }
                save(root / "source-correction.json", {"before": before, "after": after, "checks": report["correction_checks"], "independent_expected": expected})
                if not all(report["correction_checks"].values()):
                    raise ValueError("Source correction failed independent controls")
                company.publication = {
                    "title": "Finance source-owner correction publication", "author": "fictional Retail Controller",
                    "body": "In this simulation the source owner approved a September ledger activity-factor correction from 0.82 to 1.00 after reconciliation. The later result supersedes the earlier result for the same archival periods and unchanged r4 calculation. Older agent handoffs remain history, not current measurements. This publication is a simulated owner record provided by the company gateway, not native Cube revision history or evidence of an operational business cause.",
                    "provenance": ["fictional-finance-owner:correction-2026-10-25"],
                    "identities": {"superseded_result": frozen["metadata"]["data_snapshot_id"], "current_result": changed["metadata"]["data_snapshot_id"],
                        "previous_raw_data_sha256": before["raw_rows_sha256"], "current_raw_data_sha256": after["raw_rows_sha256"],
                        "unchanged_model_sha256": after["model_sha256"], "definition_revision": changed["metadata"]["metric_revision"]},
                }
                save(root / "owner-publication.json", company.publication)
                frozen = (await company.inspect(ref)).model_dump(mode="json")
                notes = {"current_reviewed_handoff": updated, "historical_pre_revision_handoff": old}
                for index, question in enumerate(PROMPTS):
                    for arm in (["ordinary_context", "signalweave"] if index % 2 == 0 else ["signalweave", "ordinary_context"]):
                        await reader(arm, question, index, notes, expected)
                report["structured_complete"] = True
                backup_state(person, root / "native-after.db")
            try:
                await connect(binary, person, source_environment(person), audit, continuation)
            finally:
                report["cube_requests"] = company.requests
                save(root / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("fixture", "pilot", "revision-probe", "output", "codex", "docker"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live or not args.project.startswith("sw-cube-"):
        parser.error("Requires explicit --live and disposable sw-cube- project")
    for name in ("fixture", "pilot", "revision_probe", "output", "codex", "docker"):
        setattr(args, name, getattr(args, name).resolve())
    report = asyncio.run(run(args))
    print(json.dumps({"structured_complete": report["structured_complete"], "readers": len(report["readers"]), "complete": False}))


if __name__ == "__main__":
    main()
