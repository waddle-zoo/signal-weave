"""Public, inference-free native context/card walkthrough over synthetic exports.

Creates fresh state through public MCP tools; never imports archived approval
artifacts. Owner choices are scripted. This is NOT agent onboarding or a report
benchmark. No external provider request, message or schedule is permitted.
"""

import argparse
import asyncio
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from evaluations.agent_workflow_cohort import _bridge_identity
from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter, RequestBudget
from evaluations.bootstrap_scenarios import build_scenarios, public_episode
from evaluations.domain_context_onboarding_trial import failure_detail, native_context
from evaluations.public_context_setup import create_public_context_setup, retail_setup_spec
from evaluations.reviewed_setup_report_trial import calendar_measurement_rebase
from scripts.binary_provenance import verify_binary
from signalweave.knowledge_models import KnowledgeContent


async def run(binary, output):
    binary = Path(binary).resolve()
    identity = verify_binary(binary)
    output = Path(output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    audit = Audit(path=output / "trace.jsonl")
    budget = RequestBudget(limit=0)
    # Public data/owner declarations only; no private labels enter this caller.
    public = public_episode(_bridge_identity(build_scenarios(seed=20261001, connector_profile=True)[0]))
    clock = datetime.now(timezone.utc)
    # Fixture measurement cutoffs are Monday 00:00 UTC, independently of reads.
    period = public["period"]
    original = datetime.fromisoformat(period["as_of"])
    offset, _ = calendar_measurement_rebase([period], clock)
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
    adapter.set_period(period, clock, measurement_offset=offset)
    spec = retail_setup_spec(public, clock)
    (output / "public-input.json").write_text(json.dumps({"public": public, "setup": spec}, indent=2) + "\n")
    report = {
        "protocol": "public-context-preflight-v1", "build": identity,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "setup_sha256": hashlib.sha256(Path(__file__).with_name("public_context_setup.py").read_bytes()).hexdigest(),
        "public_input_sha256": hashlib.sha256((output / "public-input.json").read_bytes()).hexdigest(),
        "scope": "Scripted owner; two briefs share one metric and the same source anchors. Native MCP/storage/bridge only; no frontier agent, live vendor query, Jev decision or business-value comparison.",
        "clock": {"read_at": clock.isoformat(), "measurement_cutoff": (original + offset).isoformat()},
    }
    try:
        async with asyncio.timeout(180):
            with tempfile.TemporaryDirectory(prefix="public-context-", dir=output) as private:
                root = Path(private)
                key = root / "synthetic-startup-key"
                key.write_text("synthetic-public-preflight-no-provider-requests")
                key.chmod(0o600)
                async with native_context(binary, key, public, adapter, audit, root, request_budget=budget) as (native, skill):
                    report["installed_skill_sha256"] = hashlib.sha256(skill.encode()).hexdigest()
                    setup = await create_public_context_setup(native, spec)
                    report["setup"] = setup
                    entry = setup["context"]
                    _, retrieved = await native.call_tool("retrieve_domain_context", {
                        "query": "net sales", "domain": "commerce",
                    })
                    entries = retrieved["entries"]
                    if (len(entries) != 1 or entries[0]["id"] != entry["id"]
                            or entries[0]["revision"] != entry["revision"]
                            or entries[0]["status"] != "reviewed"
                            or entries[0]["content"] != KnowledgeContent.model_validate(spec["context"]).model_dump(mode="json")):
                        raise RuntimeError("Shared reviewed definition was not retrievable")
                    report["retrieved_context"] = retrieved
                    # A new DRAFT meaning must not silently reuse an old approval.
                    changed_content = {**spec["context"], "body": spec["context"]["body"] + " The owner is reviewing whether partner sales should enter this definition; this change is not approved."}
                    _, changed = await native.call_tool("save_domain_context", {
                        "entry_id": entry["id"], "expected_revision": entry["revision"],
                        "content": changed_content,
                    })
                    report["changed_context"] = changed
                    if (changed["id"] != entry["id"] or changed["revision"] != entry["revision"] + 1
                            or changed["status"] != "draft"
                            or changed["content"] != KnowledgeContent.model_validate(changed_content).model_dump(mode="json")):
                        raise RuntimeError("Meaning edit did not create the next draft revision")
                    report["deferred_runs"] = []
                    for card, draft in zip(setup["cards"], spec["cards"], strict=True):
                        _, packet = await native.call_tool("evaluate_insight_card", {
                            "card_id": card["id"], "idempotency_key": "public-preflight:changed-meaning:" + card["id"],
                            "response_mode": "full",
                        })
                        report["deferred_runs"].append(packet)
                        result = packet["result"]
                        if (result["outcome"] is not None or result["delivery_methods"]
                                or result["judgment"]["reason"] != "context_review_required"
                                or packet["receipt"]["delivery_enabled"]
                                or packet["receipt"]["card_id"] != card["id"]
                                or packet["receipt"]["card_version"] != card["version"]
                                or result["card_id"] != card["id"]):
                            raise RuntimeError("Changed required meaning did not defer policy without delivery")
                        if result["judgment_state"]["source_errors"]:
                            raise RuntimeError("Required fixture source errors invalidate this preflight")
                        for anchor in draft["selected_sources"]:
                            if not anchor["required"]:
                                continue
                            source = result["source_by_key"][anchor["key"]]
                            if (source["adapter"] + "|" + source["resource"] != anchor["ref"]
                                    or source["error"] is not None or not source["evidence"]
                                    or not any(item["values"] and anchor["ref"] in item["provenance"] for item in source["evidence"])):
                                raise RuntimeError("Changed meaning suppressed usable required-source evidence")
                    if budget.used or budget.exhausted:
                        raise RuntimeError("Inference-free preflight attempted a provider call")
                    report["completed"] = True
    except Exception as error:  # noqa: BLE001 - retain partial native evidence without retries
        report["failure"] = failure_detail(error)
    finally:
        report["provider_attempts"] = budget.used
        report["source_reads"] = sum(event["kind"] == "source.read" for event in audit.events)
        (output / "report.json").write_text(json.dumps(audit.redact(report), indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--output", required=True, help="New exclusive ignored output directory")
    args = parser.parse_args()
    report = asyncio.run(run(args.binary, args.output))
    print(json.dumps({key: report.get(key) for key in ("completed", "failure", "provider_attempts", "source_reads")}))
    if not report.get("completed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
