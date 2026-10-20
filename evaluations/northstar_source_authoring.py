"""Opt-in operationalization of actual retained Northstar analyst procedures.

This stage admits source/runner authors, not business success or execution of
their code with credentials. Review exact code, source scope and deployment
consent separately before connection, approval or recurring shadow execution.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

from evaluations import harbor_workflow_journey as shared
from evaluations import northstar_forward_continuation as previous
from evaluations import northstar_workspace_journey as first
from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.codex_trial_transport import codex_episode
from evaluations.harbor_history_preflight import ROOT, _errors
from evaluations.harbor_workflow_actor import WorkspaceSourceActor
from evaluations.harbor_workflow_preflight import _sha
from evaluations.installed_trial_transport import _private_dir, _private_file
from evaluations.raw_superset_onboarding import usage_snapshot
from scripts.binary_provenance import verify_binary

PROTOCOL = "northstar-direct-source-authoring-v1"
ORDER = ("baseline", "signalweave")
LIMITS = {"authors": 2, "jev_requests": 0, "mcp_tools": 20, "workspace_tools": 50,
          "response_seconds": 600, "between_actor_input_stop": 4_000_000,
          "between_actor_uncached_stop": 250_000}
METHOD_FILES = ("evaluations/northstar_source_authoring.py", "evaluations/codex_workspace.py",
                "evaluations/codex_trial_transport.py", "evaluations/harbor_workflow_actor.py",
                "evaluations/northstar_workspace_journey.py", "evaluations/installed_trial_transport.py")


def public_paths(workspace):
    """Public installed dependencies plus exact read-only response captures."""
    return tuple(Path(path).resolve(strict=True) for path in (
        sys.base_prefix, ROOT/".venv/lib/python3.12/site-packages", ROOT/".venv/bin",
        ROOT/".venv/pyvenv.cfg", "/opt/homebrew/opt/gettext/lib",
        "/opt/homebrew/opt/openssl@3/lib", "/opt/homebrew/opt", Path(workspace)/"tool-responses"))


def method():
    return {name: _sha(ROOT/name) for name in METHOD_FILES}


def task(arm, study):
    common = (
        "You are this team's BI/data expert operationalizing your own retained analysis, not "
        "starting over. Read working-notes.md and recurrence-request.md. Preserve the actual "
        "owner scope, comparison, coverage, quiet behavior, threshold and audiences. Reuse your "
        "queries/calculations and repair them yourself if needed; do not rediscover the catalog "
        "without a material reason. Your job is to make the check run again without frontier "
        "preanalysis, editing SQL or writing another analyst publication each time. Use raw "
        "company tools to verify as useful. Original captures are already saved read-only; read "
        "their advertised envelope paths and write derived work elsewhere. Make automation/ "
        "and retain code, tests, and handoff.md with the exact launch commands, dependencies, "
        "source scope, limitations and operator credential/consent steps. Public Python MCP1, "
        "pydantic and httpx SDKs are installed and readable; the interpreter is "
        + str(ROOT/".venv/bin/python") + ". Shell network and credential access are intentionally "
        "disabled. You may test against your captured source replies. Deployment will supply "
        "source access only after reviewing your exact code. Do not try to read credentials or "
        "private data. No installing dependencies, web, sending or scheduling. No invented "
        "causes, currency, completeness, consultations or human approval. Preserve source errors "
        "and incomplete measurements rather than reusing a last good result. Finish with a "
        "concise human explanation of what is ready and what still needs review."
    )
    deployment = {
        "source_command": [study["source_executable"], "--transport", "stdio"],
        "source_environment": {
            "SUPERSET_BASE_URL": "runtime SUPERSET_URL (configured local source URL)",
            "SUPERSET_USERNAME": "runtime SUPERSET_USERNAME",
            "SUPERSET_PASSWORD": "read runtime SUPERSET_PASSWORD_FILE privately at deployment, never embed"},
        "historical_clock": "automation/run-context.json contains cutoff YYYY-MM-DD; explicitly supplied by operator, never host CURRENT_DATE or silently MAX(date)",
        "dependency_interpreter": str(ROOT/".venv/bin/python"),
        "source_result_rule": "Upstream SQL Lab may return JSON-text/nested result and asynchronous results_key; preserve actual query and result identity. MCP company_ prefix is the study facade only; upstream names lack it.",
        "setup_cutoff": "2026-09-18",
        "future_shadow_cutoffs": ["2026-09-04", "2026-09-11"],
    }
    if arm == "signalweave":
        common += (
            " Implement automation/reader.py as a fixed read-only stdio MCP tool returning a "
            "ResourceSnapshot with compact fresh measurements/provenance. Read the public "
            "mcp-source-bridge.md reference for its contract. Do not read analysis-publication.json "
            "or require an LLM-produced input. The reader executes your reviewed SQL and "
            "deterministic calculations; it must not select policy outcomes, recommendations or "
            "recipient routing. Those stay in the card/provider. Write automation/sources.json "
            "as an actual stdio manifest with absolute paths, fixed tool arguments and only "
            "environment references (SUPERSET_URL, SUPERSET_USERNAME, SUPERSET_PASSWORD_FILE). "
            "Use tenant local. Use absolute __file__-relative paths for helper imports/clock: "
            "stdio has no cwd setting. Write a proposed reusable card in automation/card.json "
            "from the existing policy and new source, not a fabricated approval. Native inspection, "
            "card review/approval and the first live check occur separately after code consent "
            "and connection. Also provide automation/render.py accepting --packet PATH "
            "--output-dir PATH to turn the real compact evaluation JSON into a concise brief "
            "and supporting files, using returned evidence, decision and follow-up rather than "
            "recomputing policy. No need to fabricate a packet for tests. Count any remaining "
            "manual step honestly; don't call an untested integration complete."
        )
    else:
        common += (
            " Implement automation/run.py accepting --context PATH --output-dir PATH. It may "
            "invoke the same upstream company MCP with the deployment credential references, "
            "execute your retained query/calculations, implement the owner's agreed policy and "
            "render a useful concise brief plus supporting evidence. You may use deterministic "
            "code without any LLM at recurrence: no obligation to call Luna or create a custom "
            "MCP server. Do not add SignalWeave dependencies. Preserve a documented invocation "
            "with the actual interpreter and required environment names; no embedded secrets."
        )
    return common, {"request": "Make our agreed sales review repeatable directly from the connected source, not another manual publication.",
                    "deployment": deployment}


def prepare(root, parent, binary):
    root, parent = Path(root).absolute(), Path(parent).absolute()
    if root.exists():
        raise ValueError("New study root required; no budget reset or overwrite")
    prior = shared.read(parent/"study.json")
    if prior["protocol"] != previous.PROTOCOL:
        raise ValueError("Expected actual closed forward predecessor")
    identity = verify_binary(Path(binary).absolute(), ROOT)
    if first.warehouse_fingerprint() != prior["warehouse"]:
        raise ValueError("Retained business source changed")
    if first.source_environment_identity(prior["source_executable"]) != prior["source_environment"]:
        raise ValueError("Retained source runtime changed")
    _private_dir(root)
    study = {"protocol": PROTOCOL, "method": method(), "limits": LIMITS,
             "parent": str(parent), "installed_binary": str(Path(binary).absolute()), "binary": identity,
             **{key: prior[key] for key in ("codex", "registry_sha256", "source_executable", "source_environment", "warehouse", "url")},
             "workspaces": {}, "initial_inventory": {}, "predecessors": {}, "public_read_paths": {},
             "scope": "Authoring from actual retained work, not fresh onboarding, deployment, business success or a superiority comparison"}
    for arm in ORDER:
        report_path = parent/f"{arm}.json"
        report = shared.read(report_path)
        if not report["process_complete"] or not report["usage"]["known"]:
            raise ValueError("Actual completed known-usage predecessor required")
        original = Path(prior["workspaces"][arm])
        if first.workspace_inventory(original) != report["workspace_files"]:
            raise ValueError("Actual predecessor workspace changed")
        workspace = root/arm/"workspace"
        shutil.copytree(original, workspace)
        _private_file(workspace/"mcp-source-bridge.md", (ROOT/"docs/mcp-source-bridge.md").read_text())
        study["workspaces"][arm] = str(workspace)
        study["initial_inventory"][arm] = first.workspace_inventory(workspace)
        study["public_read_paths"][arm] = list(map(str, public_paths(workspace)))
        study["predecessors"][str(report_path)] = _sha(report_path)
        instructions, prompt = task(arm, study)
        shared.write(root/f"{arm}-task.json", {"instructions": instructions, "prompt": prompt})
    study["task_hashes"] = {arm: _sha(root/f"{arm}-task.json") for arm in ORDER}
    shared.write(root/"study.json", study)
    return {"prepared": True, "analyst_invocations": 0, "provider_requests": 0}


def verify(study, root):
    if study["protocol"] != PROTOCOL or study["method"] != method() or study["limits"] != LIMITS:
        raise ValueError("Frozen authoring method changed")
    if verify_binary(Path(study["installed_binary"]), ROOT) != study["binary"] or _sha(study["codex"]["path"]) != study["codex"]["sha256"]:
        raise ValueError("Native or Codex identity changed")
    if first.warehouse_fingerprint() != study["warehouse"] or first.source_environment_identity(study["source_executable"]) != study["source_environment"]:
        raise ValueError("Source data or runtime changed")
    for path, digest in study["predecessors"].items():
        if _sha(path) != digest:
            raise ValueError("Actual predecessor record changed")
    for arm in ORDER:
        if _sha(root/f"{arm}-task.json") != study["task_hashes"][arm]:
            raise ValueError("Author instructions changed after preparation")
        if list(map(str, public_paths(study["workspaces"][arm]))) != study["public_read_paths"][arm]:
            raise ValueError("Public dependency roots changed")


async def actor(root, arm):
    root = Path(root).absolute()
    study = shared.read(root/"study.json")
    verify(study, root)
    with shared.single_actor(root):
        reports = []
        for earlier in ORDER:
            if (root/f"{earlier}.claimed").exists():
                if not (root/f"{earlier}.json").exists():
                    raise ValueError("Unreported prior attempt; no further actor")
                reports.append(shared.read(root/f"{earlier}.json"))
        if len(reports) >= len(ORDER) or ORDER[len(reports)] != arm or any(not r["process_complete"] for r in reports):
            raise ValueError("Author order/completion admission stopped")
        for key, cap in (("input_tokens", "between_actor_input_stop"), ("uncached_input_tokens", "between_actor_uncached_stop")):
            if any(not r["usage"]["known"] for r in reports) or sum(r["usage"]["usage"][key] for r in reports) >= LIMITS[cap]:
                raise ValueError("Known-usage between-author admission stopped")
        workspace = Path(study["workspaces"][arm])
        if first.workspace_inventory(workspace) != study["initial_inventory"][arm]:
            raise ValueError("Unadmitted workspace changes")
        _private_file(root/f"{arm}.claimed", PROTOCOL)
        audit = Audit(path=root/f"{arm}.jsonl", episode=arm)
        budget = RequestBudget(0)
        result = {"protocol": PROTOCOL, "arm": arm, "frontier_invocations": 0, "process_complete": False, "errors": []}
        try:
            async with first.servers(study, root, audit, budget, False) as (source, _):
                bridge = WorkspaceSourceActor(source, audit, workspace, source_tools=first.SOURCE_TOOLS)
                task_data = shared.read(root/f"{arm}-task.json")
                result["frontier_invocations"] = 1
                result["episode"] = await codex_episode(bridge, key="", model="gpt-6-luna", effort="xhigh", budget=budget,
                    audit=audit, max_turns=1, max_tool_calls=LIMITS["mcp_tools"], max_output_tokens=1,
                    instructions_override=task_data["instructions"], prompt_override=task_data["prompt"],
                    timeout_seconds=LIMITS["response_seconds"], codex_executable=study["codex"]["path"],
                    accounting_drain=True, report_remaining_budget=True, allow_trial_resource_discovery=True,
                    expected_registry_sha256=study["registry_sha256"], strict_single_turn_usage=True,
                    enforce_wall_response_timeout=True, finish_on_final_message=True,
                    workspace_dir=str(workspace), workspace_read_paths=study["public_read_paths"][arm],
                    max_workspace_tool_calls=LIMITS["workspace_tools"])
                result["process_complete"] = result["episode"]["status"] == "complete"
        except Exception as error:  # noqa: BLE001 - preserve every attempt, no rescue/retry
            result["errors"] = _errors(error, audit)
        finally:
            result.update(usage=usage_snapshot(audit.events, result["frontier_invocations"]),
                          provider_attempts=budget.used, workspace_files=first.workspace_inventory(workspace))
            before = study["initial_inventory"][arm]
            result["original_captures_unchanged"] = all(result["workspace_files"].get(p) == v for p, v in before.items() if p.startswith("tool-responses/"))
            result["process_complete"] &= bool(result["usage"]["known"] and not result["errors"] and result["original_captures_unchanged"])
            shared.write(root/f"{arm}.json", audit.redact(result))
        return {key: result[key] for key in ("process_complete", "usage", "provider_attempts", "errors", "original_captures_unchanged")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "actor"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--arm", choices=ORDER)
    args = parser.parse_args()
    if args.mode == "prepare" and args.parent and args.binary:
        result = prepare(args.root, args.parent, args.binary)
    elif args.mode == "actor" and args.arm:
        result = asyncio.run(actor(args.root, args.arm))
    else:
        parser.error("prepare requires parent/binary; actor requires arm")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
