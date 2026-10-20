"""Staged, operator-assisted continuation of actual Northstar first-use work.

No new source engine: the existing publication reader supplies the boundary
between caller-owned analysis and card policy. This is one frozen historical
state, not simulated months, effortless onboarding or a superiority benchmark.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sqlite3
import subprocess
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from evaluations import harbor_workflow_journey as shared
from evaluations import northstar_workspace_journey as first
from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.codex_trial_transport import codex_episode, verify_trial_registry
from evaluations.harbor_history_preflight import ROOT, _errors
from evaluations.harbor_workflow_actor import WorkspaceSourceActor
from evaluations.harbor_workflow_preflight import _sha
from evaluations.installed_trial_transport import _minimal_environment, _private_dir, _private_file
from evaluations.raw_superset_onboarding import usage_snapshot
from scripts.binary_provenance import verify_binary
from signalweave.models import InsightCard

PROTOCOL = "northstar-owner-continuation-v1"
LIMITS = {"actors": 4, "jev_requests": 2, "mcp_tools": 90, "workspace_tools": 40,
          "response_seconds": 600, "between_actor_input_stop": 4_000_000,
          "between_actor_uncached_stop": 350_000}
ORDER = ("clarify-baseline", "clarify-signalweave", "repeat-baseline", "repeat-signalweave")
OWNER = (
    "By online I mean all digital channels: Online, Mobile and Marketplace. Keep the total-company "
    "net-sales bridge so I can see the business impact. Let's use a seven-day check, ending at the "
    "latest available September 19, 2026 date in this historical exercise, against the same weekdays "
    "52 weeks earlier. Flag an observed decline of 10% or more for investigation if all seven dates "
    "are represented in both periods; missing dates go to Data Trust, not a sales-decline claim. "
    "Date presence is the check, not proof of complete ingestion. Keep holiday/promotion differences "
    "visible and don't invent those events. This is exception checking, not an unsolicited daily "
    "newsletter. For the first delivery-disabled demonstration, show me the readout even if quiet. "
    "Analytics and Data Trust investigate first; leadership gets findings only after the investigation "
    "supports them. I authorize local calculation and source-linked evidence files, not sending or "
    "scheduling. This is a historical review, so don't turn its age into a current-production freshness "
    "failure or invent a live freshness SLA. Show the actual card, source delegation and policy for "
    "review before approval; this clarification is not card approval."
)
COMMON = (
    "You are the owner's BI/data expert continuing your own earlier work, retained in this real "
    "workspace. Read owner-clarification.md and your working-notes.md; old findings are history, "
    "not a reason to restart catalog discovery. Use the same company BI/SQL tools, actual result "
    "files and code as useful. Verify the explicit windows, aggregation and observed-date coverage. "
    "Keep source units if currency is undeclared, and observed movement separate from cause. "
    "The named teams are intended reviewers, not people already consulted. Equal period length "
    "alone is not seasonal equivalence. Do not invent a funnel-to-sales crosswalk. Give the person "
    "a short useful answer and inspectable evidence, not a checklist. Retain actual queries and "
    "deterministic calculations in supporting files and update reusable notes. No web, other projects, "
    "credentials, hidden fixture code, sending or scheduling. Original responses are retained under "
    "tool-responses; old absolute links refer to the previous workspace, while the same relative "
    "files are copied here. Work only here and through supplied tools. Save the requested brief, "
    "then return a short final human handoff. Reserve time and ten MCP calls for finalization."
)


def task(arm, phase, card_id=None):
    instructions = COMMON
    prompt = {"request": "Apply my clarification, verify the seven-day digital-sales assessment and its company-wide impact, and prepare the repeated check for my review.",
              "assessment_mode": "historical_as_of", "source_cutoff": "2026-09-19"}
    if phase == "clarify":
        instructions += " Save clarify-brief.md. Do not approve or evaluate a card in this turn."
        if arm == "signalweave":
            instructions += (
                " Use the installed SignalWeave skill and current tools. Your earlier draft's "
                "time_range override is unsupported; don't silently remove its intended window "
                "or call it a repaired recurring source. An operator has connected the existing "
                "read-only publication example to analysis-publication.json in this workspace. "
                "Read publication-format.md. Publish only compact findings calculated from actual "
                "company queries, with recoverable lineage; the reader does not verify your claims. "
                "Inspect that exact published source, then save and review one replacement draft "
                "for the clarified owner intent. Show what the owner must approve; preserve the "
                "invalid original as history. Disable any invented current-source-age requirement "
                "for this explicitly historical review. A publication is an assisted source bridge, "
                "not new underlying data or an excuse to ask Jev to calculate."
            )
    else:
        prompt["request"] = "Repeat the owner-reviewed seven-day assessment at the same historical cutoff. Show the first local shadow readout even if no exception is triggered."
        instructions += " Save repeat-brief.md; preserve the clarified population, windows, routing and qualifications."
        if arm == "signalweave":
            if not card_id:
                raise ValueError("Repeat requires the actually approved card")
            prompt["approved_card_id"] = card_id
            prompt["idempotency_key"] = f"{PROTOCOL}:first-shadow:{card_id}"
            instructions += (
                " Begin with evaluate_insight_card for that approved card/key, using the returned "
                "evidence rather than restarting onboarding. Current means this declared historical "
                "view, not today's business. Use company tools if more analysis is needed. Explain "
                "the narrow policy decision and analytical findings separately. Do not claim a new "
                "business day or fresh source state: this exercise still has the same frozen history."
            )
    return instructions, prompt


def pending_publication():
    return {"source_key": "sales-analysis", "adapter": "analysis_publication", "resource": "report:sales-review",
            "title": "Awaiting delegated sales analysis", "source_captured_at": None,
            "contract": {"tenant_id": "local", "authorized": True},
            "metadata": {"publication_schema_version": 1, "publication_id": PROTOCOL, "revision": 1,
                "publication_authority": "Exercise operator; awaiting delegated analyst",
                "source_scope": "No analytical findings yet", "published_at": datetime.now(timezone.utc).isoformat(),
                "capture_status": "unknown", "capture_reason": "No source-result capture supplied yet"},
            "evidence": []}


def publication_reference():
    return (
        "# Optional compact analytical evidence file\n\n"
        "This is an ordinary caller-owned file, not approval or proof. Keep actual input replies, "
        "queries and derivation files separately. Use atomic replacement of analysis-publication.json; "
        "the existing reader rejects invalid/in-place changes. Keep the publication compact (a few "
        "relevant findings, windows, coverage, numerical rollups and lineage; not raw dashboards/SQL dumps).\n\n"
        "Preserve the envelope's source_key, adapter, resource, tenant and publication_id below. "
        "Increment revision, use actual UTC published_at, and describe the actual source_scope. "
        "source_captured_at is input-result capture, not the measurement cutoff or publication time. "
        "If capture is unknown, retain null and explicit capture_status=unknown/capture_reason. "
        "Do not invent freshness. Evidence entries need source_key, subject_id, statement, values "
        "and provenance references to actual retained results/calculations. Values are freeform. "
        "Distinguish observed data, calculated quantities and hypotheses; no invented cause. "
        "Keep policy outcomes, alert recommendations and routing decisions out of this evidence "
        "file: the separate policy judgment must not rubber-stamp an analyst's decision label. "
        "The reader appends a publication identity/hash record, not a truth certificate.\n\n"
        "```json\n"+json.dumps(pending_publication(), indent=2)+"\n```\n"
    )


def method():
    names = ["evaluations/northstar_owner_continuation.py", "evaluations/northstar_workspace_journey.py",
             "evaluations/harbor_workflow_actor.py", "evaluations/codex_trial_transport.py",
             "evaluations/codex_workspace.py", "evaluations/installed_trial_transport.py",
             "examples/analysis_publication/reader.py", "skills/signalweave/SKILL.md"]
    return {name: _sha(ROOT/name) for name in names}


async def prepare(root, parent, binary):
    started = time.perf_counter()
    root, parent, binary = (Path(x).absolute() for x in (root, parent, binary))
    previous = shared.read(parent/"study.json")
    identity = verify_binary(binary, ROOT)
    if first.warehouse_fingerprint() != previous["warehouse"]:
        raise ValueError("Parent's business data changed")
    if first.source_environment_identity(previous["source_executable"]) != previous["source_environment"]:
        raise ValueError("Parent's source implementation changed")
    _private_dir(root)
    study = {"protocol": PROTOCOL, "method": method(), "limits": LIMITS, "parent": str(parent),
             "binary": identity, "binary_path": str(binary), "arms": {}, "parent_reports": {},
             "warehouse": previous["warehouse"], "source_environment": previous["source_environment"],
             **{k: previous[k] for k in ("source_executable", "codex", "url", "key_file")},
             "owner_sha256": shared.digest(OWNER),
             "scope": "Operator-assisted continuation of one known historical company. Actual own prior files, owner clarification, compact analyst publication, review/approval then separate shadow runs. Not fresh installation, changing-state recurrence or superiority."}
    _private_file(root/"private-canary.txt", "private grader canary")
    reference = publication_reference()
    for arm in ("baseline", "signalweave"):
        old = shared.read(parent/f"{arm}.json")
        if not old["process_complete"] or not old["usage"]["known"] or not old["inputs_unchanged"]:
            raise ValueError("Actual completed predecessor required")
        study["parent_reports"][str(parent/f"{arm}.json")] = _sha(parent/f"{arm}.json")
        old_workspace = parent/arm/"workspace"
        if first.workspace_inventory(old_workspace) != old["workspace_files"]:
            raise ValueError("Actual predecessor files changed")
        workspace = root/arm/"workspace"
        _private_dir(workspace.parent)
        shutil.copytree(old_workspace, workspace)
        workspace.chmod(0o700)
        _private_file(workspace/"owner-clarification.md", OWNER)
        _private_file(workspace/"publication-format.md", reference)
        _private_file(workspace/"analysis-publication.json", json.dumps(pending_publication(), indent=2))
        study["arms"][arm] = {"initial_inventory": first.workspace_inventory(workspace)}
    home = root/"signalweave/human-home"
    _private_dir(home)
    _private_dir(home/"tmp")
    env = _minimal_environment(home)
    setup = subprocess.run([str(binary), "setup", "--non-interactive", "--home", str(home/".signalweave"),
        "--key-file", study["key_file"], "--source", "superset", "--url", study["url"], "--username", "admin",
        "--secret-file", str(parent/"human-home/.signalweave/superset-password.key"),
        "--tenant", "local", "--principal", "local", "--agent", "codex", "--no-register-agent"],
        env=env, capture_output=True, text=True, timeout=90)
    study["assisted_setup"] = {"exit": setup.returncode, "output": setup.stdout, "errors": setup.stderr}
    shared.write(root/"setup.json", study["assisted_setup"])
    if setup.returncode:
        raise ValueError("Native assisted continuation setup failed")
    # Copy actual persisted card state; do not fabricate or repair the old card.
    destination = home/".signalweave/state/signalweave.db"
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with closing(sqlite3.connect(f"file:{parent}/human-home/.signalweave/state/signalweave.db?mode=ro", uri=True)) as old_db:
        with closing(sqlite3.connect(destination)) as new_db:
            old_db.backup(new_db)
            new_db.commit()
    destination.chmod(0o600)
    manifest = shared.read(ROOT/"examples/analysis_publication/manifest.example.json")
    connection = manifest["connections"][0]
    connection["transport"]["command"] = [str(ROOT/".venv/bin/python"), str(ROOT/"examples/analysis_publication/reader.py"),
                                             str(root/"signalweave/workspace/analysis-publication.json")]
    resource = connection["resources"][0]
    resource.update(source_key="sales-analysis")
    resource["descriptor"].update(resource="report:sales-review", title="Delegated sales analysis", description="Compact caller analysis with original-result lineage; not independently verified findings.")
    resource["descriptor"]["contract"].update(domain="retail", scope="Owner-reviewed sales investigation publication", freshness_sla_hours=None)
    manifest_path = root/"sources.json"
    shared.write(manifest_path, manifest)
    add = subprocess.run([str(binary), "connections", "add", "--source", "mcp", "--manifest", str(manifest_path),
                          "--home", str(home/".signalweave"), "--non-interactive"], env=env,
                         capture_output=True, text=True, timeout=60)
    study["assisted_connection"] = {"exit": add.returncode, "output": add.stdout, "errors": add.stderr}
    shared.write(root/"connection.json", study["assisted_connection"])
    if add.returncode:
        raise ValueError("Publication connection setup failed")
    study.update(installed_binary=str(binary), manifest_path=str(manifest_path), manifest_sha256=_sha(manifest_path))
    study["registry_sha256"] = (await verify_trial_registry(study["codex"]["path"], root/"baseline/workspace", "http://127.0.0.1:1/mcp"))["registry_sha256"]
    for arm in ("baseline", "signalweave"):
        workspace = root/arm/"workspace"
        study["arms"][arm]["sandbox"] = await asyncio.to_thread(first.sandbox_preflight,
            study["codex"]["path"], workspace, root/"private-canary.txt", (Path(study["key_file"]),))
        study["arms"][arm]["initial_inventory"] = first.workspace_inventory(workspace)
    audit = Audit(path=root/"preflight.jsonl", secrets=(Path(study["key_file"]).read_text().strip(),))
    budget = RequestBudget(0)
    async with first.servers(study, root/"signalweave", audit, budget, True) as (_, native):
        _, snapshot = await native.call_tool("inspect_resource", {"adapter": "analysis_publication", "resource": "report:sales-review"})
        if snapshot.get("error") or snapshot.get("observations") or len(snapshot.get("evidence", [])) != 1:
            raise ValueError("Pending reader source not available or contains prepared analysis")
        shared.write(root/"pending-source.json", snapshot)
    if budget.used:
        raise ValueError("Preflight unexpectedly used a provider")
    study["preparation_seconds"] = time.perf_counter()-started
    shared.write(root/"study.json", study)
    return {"prepared": True, "analyst_calls": 0, "provider_calls": 0}


def verify(study, root):
    if study["protocol"] != PROTOCOL or study["method"] != method() or study["limits"] != LIMITS:
        raise ValueError("Frozen method changed")
    if verify_binary(Path(study["binary_path"]), ROOT) != study["binary"]:
        raise ValueError("Native changed")
    if first.warehouse_fingerprint() != study["warehouse"] or first.source_environment_identity(study["source_executable"]) != study["source_environment"]:
        raise ValueError("Frozen source changed")
    for path, digest in {**study["parent_reports"], study["manifest_path"]: study["manifest_sha256"], study["codex"]["path"]: study["codex"]["sha256"]}.items():
        if _sha(Path(path)) != digest:
            raise ValueError("Frozen input changed")


def reviewed_artifacts(root, review):
    """Bind an attributed exercise-owner review to actual work, not expected labels."""
    for name in ("clarify-baseline", "clarify-signalweave"):
        report = shared.read(root/f"{name}.json")
        if not report["process_complete"] or not report["protocol_ok"]:
            raise ValueError("Completed actual clarification work is required")
        if review.get("artifacts", {}).get(name) != _sha(root/f"{name}.json"):
            raise ValueError("Review must bind both actual reports")
    for name in ("owner-card.json", "operator-source-inspection.json"):
        if review.get("artifacts", {}).get(name) != _sha(root/name):
            raise ValueError("Review must bind the actual card and published source")
    if review.get("publication_sha256") != _sha(root/"signalweave/workspace/analysis-publication.json"):
        raise ValueError("Published input changed after owner review")
    if (review.get("protocol") != PROTOCOL or review.get("approved_for_shadow") is not True
            or review.get("reviewer_type") not in {"human", "simulated_expert"}
            or any(not isinstance(review.get(k), str) or not review[k].strip()
                   for k in ("reviewer", "reason", "owner_confirmation", "source_selection_reason"))
            or any(not str(review.get("assessments", {}).get(arm, "")).strip()
                   for arm in ("baseline", "signalweave"))):
        raise ValueError("Explicit attributed source/policy review is required")


async def approve(root, review_file):
    root, review_file = Path(root).absolute(), Path(review_file).absolute()
    study, review = shared.read(root/"study.json"), shared.read(review_file)
    verify(study, root)
    reviewed_artifacts(root, review)
    with shared.single_actor(root):
        _private_file(root/"approval.claimed", PROTOCOL)
        author = shared.read(root/"clarify-signalweave.json")
        reviewed = shared.read(root/"owner-card.json")
        handoff = author.get("approval_handoff") or {}
        if handoff.get("dynamic_scope_requires_separate_acknowledgment"):
            raise ValueError("This study has no dynamic-scope approval")
        arguments = handoff.get("arguments_after_owner_confirmation")
        if not arguments or arguments.get("card_id") != reviewed.get("id"):
            raise ValueError("Exact reviewed approval handoff required")
        audit = Audit(path=root/"approval.jsonl", secrets=(Path(study["key_file"]).read_text().strip(),))
        budget = RequestBudget(0)
        async with first.servers(study, root/"signalweave", audit, budget, True) as (_, native):
            _, current = await native.call_tool("get_insight_card", {"card_id": reviewed["id"], "response_mode": "full", "include_history": True})
            if current != reviewed:
                raise ValueError("Card changed since the actual owner review")
            _, response = await native.call_tool("approve_insight_card", {
                **arguments, "source_selection_reason": review["source_selection_reason"]})
            _, approved = await native.call_tool("get_insight_card", {"card_id": reviewed["id"], "response_mode": "full", "include_history": True})
        if budget.used or response.get("status") != "approved" or approved.get("status") != "approved":
            raise ValueError("Actual no-inference approval did not complete")
        result = {"protocol": PROTOCOL, "owner_review_path": str(review_file), "owner_review_sha256": _sha(review_file),
                  "approved_card_id": approved["id"], "approval": response, "approved_card": approved,
                  "execution_sha256": shared.digest(InsightCard.model_validate(approved).execution_payload())}
        shared.write(root/"approval.json", result)
        return {"approved_card_id": approved["id"], "provider_calls": 0}


async def actor(root, arm, phase):
    root = Path(root).absolute()
    study = shared.read(root/"study.json")
    verify(study, root)
    name = f"{phase}-{arm}"
    with shared.single_actor(root):
        reports = []
        for planned in ORDER:
            path = root/f"{planned}.json"
            if (root/f"{planned}.claimed").exists() and not path.exists():
                raise ValueError("Unreported attempt; no further inference")
            if path.exists():
                reports.append(shared.read(path))
        if len(reports) >= len(ORDER) or ORDER[len(reports)] != name or any(not r["process_complete"] or not r["usage"]["known"] or not r["provider_usage"]["known"] or not r.get("protocol_ok") for r in reports):
            raise ValueError("Actor order/completion admission stopped")
        for key, bound in (("input_tokens", "between_actor_input_stop"), ("uncached_input_tokens", "between_actor_uncached_stop")):
            if sum(r["usage"]["usage"][key] for r in reports) >= LIMITS[bound]:
                raise ValueError("Cumulative usage admission stopped")
        approval = None
        if phase == "repeat":
            approval = shared.read(root/"approval.json")
            if not approval.get("owner_review_path") or not approval.get("approved_card_id") or approval.get("protocol") != PROTOCOL:
                raise ValueError("Actual reviewed approval is required")
            review_path = Path(approval["owner_review_path"])
            if _sha(review_path) != approval["owner_review_sha256"]:
                raise ValueError("Attributed owner review changed")
            reviewed_artifacts(root, shared.read(review_path))
        workspace = root/arm/"workspace"
        if phase == "clarify" and first.workspace_inventory(workspace) != study["arms"][arm]["initial_inventory"]:
            raise ValueError("Starting workspace changed")
        _private_file(root/f"{name}.claimed", PROTOCOL)
        audit = Audit(path=root/f"{name}.jsonl", episode=name, secrets=(Path(study["key_file"]).read_text().strip(),))
        remaining = LIMITS["jev_requests"]-sum(r["provider_attempts"] for r in reports)
        budget = RequestBudget(remaining if arm == "signalweave" and phase == "repeat" else 0)
        result = {"protocol": PROTOCOL, "arm": arm, "phase": phase, "process_complete": False, "frontier_invocations": 0, "errors": []}
        try:
            async with first.servers(study, root/"signalweave", audit, budget, arm == "signalweave") as (source, native):
                if native and phase == "repeat":
                    _, current = await native.call_tool("get_insight_card", {"card_id": approval["approved_card_id"], "response_mode": "full", "include_history": True})
                    if current.get("status") != "approved" or shared.digest(InsightCard.model_validate(current).execution_payload()) != approval["execution_sha256"]:
                        raise ValueError("Approved policy or source scope changed")
                bridge = WorkspaceSourceActor(source, audit, workspace, source_tools=first.SOURCE_TOOLS, native=native)
                bridge.phase = "onboarding" if phase == "clarify" else "recurring"
                instructions, prompt = task(arm, phase, approval.get("approved_card_id") if approval else None)
                result["frontier_invocations"] = 1
                result["episode"] = await codex_episode(bridge, key="", model="gpt-6-luna", effort="xhigh", budget=budget,
                    audit=audit, max_turns=1, max_tool_calls=LIMITS["mcp_tools"], max_output_tokens=1,
                    instructions_override=instructions, prompt_override=prompt, timeout_seconds=LIMITS["response_seconds"],
                    codex_executable=study["codex"]["path"], accounting_drain=True, report_remaining_budget=True,
                    allow_trial_resource_discovery=True, expected_registry_sha256=study["registry_sha256"],
                    strict_single_turn_usage=True, enforce_wall_response_timeout=True, finish_on_final_message=True,
                    workspace_dir=str(workspace), max_workspace_tool_calls=LIMITS["workspace_tools"])
                brief = workspace/f"{phase}-brief.md"
                result["brief"] = brief.read_text() if brief.is_file() and not brief.is_symlink() else ""
                result["workspace_files"] = first.workspace_inventory(workspace)
                result["process_complete"] = result["episode"]["status"] == "complete" and bool(result["brief"].strip())
                if native and phase == "clarify":
                    _, published = await native.call_tool("inspect_resource", {"adapter": "analysis_publication", "resource": "report:sales-review"})
                    shared.write(root/"operator-source-inspection.json", published)
                    result["operator_source_inspection"] = {"path": str(root/"operator-source-inspection.json"),
                                                              "sha256": _sha(root/"operator-source-inspection.json")}
                    drafts = [e.get("result", {}) for e in audit.events if e.get("kind") == "tool.result"
                              and e.get("name") in {"onboard_insight_card", "review_insight_card"}
                              and e.get("result", {}).get("approval_handoff", {}).get("arguments_after_owner_confirmation")]
                    if drafts:
                        latest = drafts[-1]
                        card_id = latest["card"]["id"]
                        _, card = await native.call_tool("get_insight_card", {"card_id": card_id, "response_mode": "full", "include_history": True})
                        shared.write(root/"owner-card.json", card)
                        result["approval_handoff"] = latest["approval_handoff"]
                        result["owner_card_sha256"] = _sha(root/"owner-card.json")
        except Exception as error:  # noqa: BLE001 - preserve failed attempts
            result["errors"] = _errors(error, audit)
        finally:
            calls = [e for e in audit.events if e.get("kind") == "tool.result" and not e.get("name", "").startswith("company_")]
            result["native_calls"] = calls
            result["protocol_ok"] = not (phase == "clarify" and any(e.get("name") in {"approve_insight_card", "evaluate_insight_card"} for e in calls))
            result.update(usage=usage_snapshot(audit.events, result["frontier_invocations"]), provider_attempts=budget.used,
                          provider_usage=shared.provider_usage(audit, budget.used))
            if phase == "repeat" and arm == "signalweave":
                evaluations = [e for e in calls if e.get("name") == "evaluate_insight_card"]
                packet = evaluations[0].get("result", {}) if len(evaluations) == 1 else {}
                receipt = packet.get("receipt", {})
                result["policy_exercised"] = bool(len(evaluations) == 1 and packet.get("replayed") is False
                    and receipt.get("card_id") == approval["approved_card_id"]
                    and receipt.get("status") == "delivery_disabled"
                    and str(packet.get("result", {}).get("evaluator", "")).startswith("jev")
                    and budget.used and result["provider_usage"]["known"])
                result["protocol_ok"] &= result["policy_exercised"]
            try:
                verify(study, root)
                result["inputs_unchanged"] = True
            except Exception as error:  # noqa: BLE001
                result["inputs_unchanged"] = False
                result["errors"].extend(_errors(error, audit))
            result["process_complete"] &= bool(result["usage"]["known"] and result["provider_usage"]["known"] and result["inputs_unchanged"] and not result["errors"])
            shared.write(root/f"{name}.json", audit.redact(result))
        return {k: result[k] for k in ("process_complete", "provider_attempts", "errors")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--parent", type=Path, required=True)
    prep.add_argument("--binary", type=Path, required=True)
    run = sub.add_parser("actor")
    run.add_argument("--arm", choices=("baseline", "signalweave"), required=True)
    run.add_argument("--phase", choices=("clarify", "repeat"), required=True)
    approval = sub.add_parser("approve")
    approval.add_argument("--review-file", type=Path, required=True)
    for command in (prep, run, approval):
        command.add_argument("--root", type=Path, required=True)
    args = vars(parser.parse_args())
    command = args.pop("command")
    operation = {"prepare": prepare, "actor": actor, "approve": approve}[command]
    print(json.dumps(asyncio.run(operation(**args))))


if __name__ == "__main__":
    main()
