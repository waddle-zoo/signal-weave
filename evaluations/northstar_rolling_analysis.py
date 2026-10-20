"""Opt-in retrospective continuity study using the agents' actual retained work.

No new analytical engine or prepared publisher. The agents adapt their own
procedures; the existing publication connection remains in place. Earlier closed
cohorts stay closed. These cutoffs do not model contemporaneous data visibility.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

from evaluations import harbor_workflow_journey as shared
from evaluations import northstar_workspace_journey as first
from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.codex_trial_transport import codex_episode
from evaluations.harbor_history_preflight import ROOT, _errors
from evaluations.harbor_workflow_actor import WorkspaceSourceActor
from evaluations.harbor_workflow_preflight import _sha
from evaluations.installed_trial_transport import _minimal_environment, _private_dir, _private_file
from evaluations.raw_superset_onboarding import usage_snapshot
from scripts.binary_provenance import verify_binary

PROTOCOL = "northstar-rolling-analysis-v1"
CUTOFFS = ("2026-09-05", "2026-09-12", "2026-09-19")
ORDER = tuple(f"{cutoff}-{arm}" for cutoff in CUTOFFS for arm in ("baseline", "signalweave"))
LIMITS = {"actors": 6, "jev_requests": 3, "mcp_tools": 60, "workspace_tools": 40,
          "response_seconds": 600, "between_actor_input_stop": 8_000_000,
          "between_actor_uncached_stop": 600_000}
OWNER = (
    "Keep our agreed all-digital definition (Online, Mobile and Marketplace), source units, "
    "company-wide net-sales bridge, observed-date coverage check and 10% decline investigation "
    "rule. Make the check rolling: for each supplied cutoff D, compare the seven calendar dates "
    "D-6 through D with D-370 through D-364, exactly 52 weeks earlier. Missing dates go to Data "
    "Trust without a sales-decline claim. Analytics and Data Trust investigate qualifying declines "
    "first; leadership receives findings only after investigation supports them. Date presence is "
    "not ingestion completeness or seasonal equivalence; don't invent holiday/promotion events "
    "or causes. These are retrospective recomputations over the currently retained warehouse, "
    "not claims about what information was available then or new production days. "
    "You are my delegated BI/data expert. You may adapt the retained analysis using authorized "
    "company tools, review the exact saved procedure/source scope and policy, and sign off a "
    "matching rolling workflow for local delivery-disabled checks. This is authority for your "
    "actual expert review, not a claim that any human or named team has reviewed it. Do not "
    "silently carry approval of the old fixed windows forward. Use the existing delegated analysis "
    "source if applicable; do not broaden its business population. No sending or scheduling. "
    "Show a short local demonstration at each requested cutoff even when quiet; this does not "
    "authorize an unsolicited daily newsletter. Retain the working refresh procedure so I do not "
    "have to reconstruct technical preparation or answer the same business questions next time."
)


def method():
    names = ["evaluations/northstar_rolling_analysis.py", "evaluations/northstar_workspace_journey.py",
             "evaluations/harbor_workflow_actor.py", "evaluations/codex_trial_transport.py",
             "evaluations/codex_workspace.py", "evaluations/installed_trial_transport.py",
             "examples/analysis_publication/reader.py", "skills/signalweave/SKILL.md"]
    return {name: _sha(ROOT/name) for name in names}


def task(arm, cutoff, card_id):
    instructions = (
        "Continue your actual BI work in this workspace. Read recurrence-request.md and your own "
        "working-notes.md. The new request changes the fixed-window policy into a rolling one; old "
        "examples are history, not today's measurement. Reuse your actual SQL/calculation files "
        "and authorized company tools instead of rediscovering the catalog. Adapt your own procedure "
        "as necessary; no operator has prepared a calculation or publisher for you. Execute the "
        "queries for the requested cutoff and derive numerical results from those fresh replies, "
        "not memorized figures or old response numbers. Preserve original replies and working "
        "queries/calculations. Keep a usable invocation and input/output locations in notes. Missing "
        "dates should produce a useful coverage result, not a crash or reuse of yesterday's findings. "
        "Give the person the smallest useful readout with digital movement, company impact, next "
        "action and material qualifications; put technical detail in supporting files. Do not invent "
        "consultation, causality or delivery. Work only here and through supplied tools: no web, "
        "other projects, credentials, fixture code, sending or scheduling. Existing absolute links "
        "and files are your actual earlier work. Save rolling-" + cutoff + ".md and return a short "
        "human handoff. Reserve ten MCP calls and time for finalization."
    )
    prompt = {"request": "Apply our rolling-check agreement at this historical cutoff. Refresh the analysis and show what matters, even if no exception is triggered.",
              "historical_cutoff": cutoff}
    if arm == "signalweave":
        instructions += (
            " Use the current installed SignalWeave skill and exposed tools. The existing company "
            "publication connection reads analysis-publication.json; read publication-format.md. "
            "You own the calculation and compact publication refresh before evaluation. Retain its "
            "identity, increment revision, use actual publication time, preserve input capture time "
            "or its explicit uncertainty, and distinguish measurement windows from timestamps. "
            "No policy outcomes, recommendations or routing labels in published evidence. On the "
            "first checkpoint, revise the actual existing card to the owner's rolling policy, "
            "inspect the exact refreshed source, review and approve only if your delegated expert "
            "review finds the saved scope and policy match. Record that actual review; do not "
            "claim a human signed it. Later cutoffs within that policy need refreshed measurements, "
            "not re-onboarding or repeated business questions. Evaluate that approved card once "
            "with the supplied new key, then read its evidence and explain the actual policy result. "
            "Use company tools for further investigation when useful, not to replace a failed "
            "judgment with an invented successful one."
        )
        prompt.update(card_id=card_id, idempotency_key=f"{PROTOCOL}:{cutoff}:{card_id}")
    return instructions, prompt


def prepare(root, parent, binary):
    root, parent, binary = (Path(p).absolute() for p in (root, parent, binary))
    if root.exists():
        raise ValueError("New study directory required; no retries or budget reset")
    prior = shared.read(parent/"study.json")
    identity = verify_binary(binary, ROOT)
    if first.warehouse_fingerprint() != prior["warehouse"] or first.source_environment_identity(prior["source_executable"]) != prior["source_environment"]:
        raise ValueError("Predecessor business/source state changed")
    approval = shared.read(parent/"approval.json")
    _private_dir(root)
    study = {"protocol": PROTOCOL, "method": method(), "limits": LIMITS, "cutoffs": CUTOFFS,
             "parent": str(parent), "installed_binary": str(binary), "binary": identity,
             "server_root": str(parent/"signalweave"), "card_id": approval["approved_card_id"],
             "warehouse": prior["warehouse"], "source_environment": prior["source_environment"],
             **{k: prior[k] for k in ("source_executable", "codex", "url", "key_file", "registry_sha256")},
             "scope": "Assisted known-company historical refresh-to-message trajectory, not fresh onboarding, contemporaneous visibility, real delivery or superiority",
             "prior_chain": {}, "workspaces": {}, "initial_inventory": {}}
    for name in ("clarify-baseline", "clarify-signalweave", "repeat-baseline"):
        path = parent/f"{name}.json"
        report = shared.read(path)
        if not report["process_complete"] or not report["usage"]["known"]:
            raise ValueError("Actual completed predecessor work required")
        study["prior_chain"][str(path)] = {"sha256": _sha(path), "usage": report["usage"]}
    for path in [*(Path(prior["parent"])/f"{arm}.json" for arm in ("baseline", "signalweave")),
                 ROOT/"artifacts/northstar-workspace-first-use-v4/baseline.json"]:
        report = shared.read(path)
        study["prior_chain"][str(path)] = {"sha256": _sha(path), "usage": report["usage"],
                                         "process_complete": report["process_complete"]}
    wiring = parent/"operator-policy-check.json"
    study["prior_chain"][str(wiring)] = {"sha256": _sha(wiring),
        "provider_usage": shared.read(wiring)["provider_usage"], "frontier_invocations": 0}
    # Preserve the exact prior user work before continuing it in place.
    for arm in ("baseline", "signalweave"):
        workspace = parent/arm/"workspace"
        predecessor = shared.read(parent/("repeat-baseline.json" if arm == "baseline" else "clarify-signalweave.json"))
        if first.workspace_inventory(workspace) != predecessor["workspace_files"]:
            raise ValueError("Actual predecessor workspace changed")
        archive = root/"predecessor-workspaces"/arm
        shutil.copytree(workspace, archive)
        if first.workspace_inventory(workspace) != first.workspace_inventory(archive):
            raise ValueError("Workspace archive differs")
        study["workspaces"][arm] = str(workspace)
    # Deliberate skill upgrade, not an analytical rescue. The old exact bytes are retained.
    workspace = Path(study["workspaces"]["signalweave"])
    old_skill = workspace/".agents/skills/signalweave"
    study["prior_skill_sha256"] = _sha(old_skill/"SKILL.md")
    shutil.move(old_skill, root/"previous-installed-skill")
    home = parent/"signalweave/human-home"
    update = subprocess.run([str(binary), "skills", "install", "--agent", "codex", "--scope", "project"],
        cwd=workspace, env=_minimal_environment(home), capture_output=True, text=True, timeout=60)
    study["skill_upgrade"] = {"exit": update.returncode, "stdout": update.stdout, "stderr": update.stderr,
                              "assistance": "Operator archived old bundled project skill and installed current native skill; no source reconnection or analytical code supplied"}
    if update.returncode or _sha(old_skill/"SKILL.md") != _sha(ROOT/"skills/signalweave/SKILL.md"):
        raise ValueError("Current native skill installation failed")
    db = home/".signalweave/state/signalweave.db"
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as old:
        with closing(sqlite3.connect(root/"predecessor-state.sqlite")) as backup:
            old.backup(backup)
    study["immutable_files"] = {str(parent/name): _sha(parent/name) for name in ("study.json", "approval.json", "sources.json")}
    study["immutable_files"][study["codex"]["path"]] = study["codex"]["sha256"]
    for arm, path in study["workspaces"].items():
        _private_file(Path(path)/"recurrence-request.md", OWNER)
        study["initial_inventory"][arm] = first.workspace_inventory(Path(path))
    shared.write(root/"study.json", study)
    return {"prepared": True, "analyst_calls": 0, "provider_calls": 0}


def verify(study):
    if study["protocol"] != PROTOCOL or study["method"] != method() or study["limits"] != LIMITS or tuple(study["cutoffs"]) != CUTOFFS:
        raise ValueError("Frozen method changed")
    if verify_binary(Path(study["installed_binary"]), ROOT) != study["binary"] or first.warehouse_fingerprint() != study["warehouse"] or first.source_environment_identity(study["source_executable"]) != study["source_environment"]:
        raise ValueError("Native or business/source state changed")
    for path, sha in {**study["immutable_files"], **{p: r["sha256"] for p, r in study["prior_chain"].items()}}.items():
        if _sha(Path(path)) != sha:
            raise ValueError("Frozen predecessor/configuration changed")


async def actor(root, arm, cutoff):
    root = Path(root).absolute()
    study = shared.read(root/"study.json")
    verify(study)
    name = f"{cutoff}-{arm}"
    with shared.single_actor(root):
        reports = []
        for planned in ORDER:
            path = root/f"{planned}.json"
            if (root/f"{planned}.claimed").exists() and not path.exists():
                raise ValueError("Unreported attempt; no further admission")
            if path.exists():
                reports.append(shared.read(path))
        if len(reports) >= len(ORDER) or ORDER[len(reports)] != name or any(not r["process_complete"] or not r["protocol_ok"] for r in reports):
            raise ValueError("Order or completion admission stopped")
        for key, cap in (("input_tokens", "between_actor_input_stop"), ("uncached_input_tokens", "between_actor_uncached_stop")):
            if sum(r["usage"]["usage"][key] for r in reports) >= LIMITS[cap]:
                raise ValueError("Cumulative usage admission stopped")
        workspace = Path(study["workspaces"][arm])
        previous = [r for r in reports if r["arm"] == arm]
        expected = previous[-1]["workspace_files"] if previous else study["initial_inventory"][arm]
        if first.workspace_inventory(workspace) != expected:
            raise ValueError("User workspace changed between admitted actors")
        _private_file(root/f"{name}.claimed", PROTOCOL)
        audit = Audit(path=root/f"{name}.jsonl", episode=name, secrets=(Path(study["key_file"]).read_text().strip(),))
        remaining = LIMITS["jev_requests"]-sum(r["provider_attempts"] for r in reports)
        budget = RequestBudget(min(1, remaining) if arm == "signalweave" else 0)
        result = {"protocol": PROTOCOL, "arm": arm, "cutoff": cutoff, "frontier_invocations": 0,
                  "process_complete": False, "protocol_ok": False, "errors": []}
        try:
            async with first.servers(study, Path(study["server_root"]), audit, budget, arm == "signalweave") as (source, native):
                bridge = WorkspaceSourceActor(source, audit, workspace, source_tools=first.SOURCE_TOOLS, native=native)
                instructions, prompt = task(arm, cutoff, study["card_id"])
                result["frontier_invocations"] = 1
                result["episode"] = await codex_episode(bridge, key="", model="gpt-6-luna", effort="xhigh", budget=budget,
                    audit=audit, max_turns=1, max_tool_calls=LIMITS["mcp_tools"], max_output_tokens=1,
                    instructions_override=instructions, prompt_override=prompt, timeout_seconds=LIMITS["response_seconds"],
                    codex_executable=study["codex"]["path"], accounting_drain=True, report_remaining_budget=True,
                    allow_trial_resource_discovery=True, expected_registry_sha256=study["registry_sha256"],
                    strict_single_turn_usage=True, enforce_wall_response_timeout=True, finish_on_final_message=True,
                    workspace_dir=str(workspace), max_workspace_tool_calls=LIMITS["workspace_tools"])
                brief = workspace/f"rolling-{cutoff}.md"
                result["brief"] = brief.read_text() if brief.is_file() and not brief.is_symlink() else ""
                result["process_complete"] = result["episode"]["status"] == "complete" and bool(result["brief"].strip())
                if native:
                    _, card = await native.call_tool("get_insight_card", {"card_id": study["card_id"], "response_mode": "full", "include_history": True})
                    result["card_after"] = card
                    result["publication_after"] = shared.read(workspace/"analysis-publication.json")
                    result["publication_sha256"] = _sha(workspace/"analysis-publication.json")
        except Exception as error:  # noqa: BLE001 - retain failures, never retry
            result["errors"] = _errors(error, audit)
        finally:
            result["workspace_files"] = first.workspace_inventory(workspace)
            result["native_calls"] = [e for e in audit.events if e.get("kind") == "tool.result" and not e.get("name", "").startswith("company_")]
            result.update(usage=usage_snapshot(audit.events, result["frontier_invocations"]), provider_attempts=budget.used,
                          provider_usage=shared.provider_usage(audit, budget.used))
            evaluations = [e["result"] for e in result["native_calls"] if e.get("name") == "evaluate_insight_card"]
            packet = evaluations[0] if len(evaluations) == 1 else {}
            result["protocol_ok"] = arm == "baseline" or bool(len(evaluations) == 1 and packet.get("replayed") is False
                and packet.get("receipt", {}).get("card_id") == study["card_id"]
                and packet.get("receipt", {}).get("status") == "delivery_disabled"
                and str(packet.get("result", {}).get("evaluator", "")).startswith("jev") and budget.used)
            try:
                verify(study)
                result["inputs_unchanged"] = True
            except Exception as error:  # noqa: BLE001
                result["inputs_unchanged"] = False
                result["errors"].extend(_errors(error, audit))
            result["process_complete"] &= bool(result["usage"]["known"] and result["provider_usage"]["known"] and result["inputs_unchanged"] and not result["errors"])
            shared.write(root/f"{name}.json", audit.redact(result))
        return {k: result[k] for k in ("process_complete", "protocol_ok", "provider_attempts", "errors")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--parent", type=Path, required=True)
    p.add_argument("--binary", type=Path, required=True)
    a = sub.add_parser("actor")
    a.add_argument("--arm", choices=("baseline", "signalweave"), required=True)
    a.add_argument("--cutoff", choices=CUTOFFS, required=True)
    for command in (p, a):
        command.add_argument("--root", type=Path, required=True)
    args = vars(parser.parse_args())
    operation = args.pop("command")
    print(json.dumps(prepare(**args) if operation == "prepare" else asyncio.run(actor(**args))))


if __name__ == "__main__":
    main()
