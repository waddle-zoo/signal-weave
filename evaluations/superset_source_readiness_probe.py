"""Zero-inference native/source diagnostic, not an agent or onboarding benchmark.

Uses a fresh private CLI home against the existing local Northstar Superset.
No real decision credential, approval, evaluation, schedule or send is permitted.
The operator supplies source IDs and, optionally, a card proposal to review.
"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.native_superset_card_journey import verify_capture_imports
from evaluations.raw_superset_onboarding import native_connection
from scripts.binary_provenance import verify_binary


def validate_proposal(proposal):
    if not isinstance(proposal, dict) or not proposal.get("selected_sources"):
        raise ValueError("Supply an explicit fixed-source onboarding proposal")
    if proposal.get("retrieval_mode", "fixed") != "fixed" or proposal.get("investigation_mode", "none") != "none":
        raise ValueError("This zero-inference probe permits only fixed, non-expanding cards")
    return proposal


async def run(args):
    if args.superset_url != "http://127.0.0.1:18089":
        raise ValueError("This probe authorizes only the existing loopback Northstar source")
    proposal = validate_proposal(json.loads(Path(args.proposal).read_text())) if args.proposal else None
    verify_capture_imports()
    binary = Path(args.binary).resolve()
    build = verify_binary(binary)
    root = Path(args.output).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    dummy = root / "dummy.key"
    dummy.write_text("not-a-live-provider-key\n")
    dummy.chmod(0o600)
    audit, budget = Audit(path=root / "trace.jsonl"), RequestBudget(0)
    report = {
        "protocol": "superset-source-readiness-probe-v1",
        "scope": "Operator-selected source inspection and optional draft review, not an autonomous onboarding or human installation trial.",
        "build": build,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "proposal": proposal,
        "snapshots": [],
        "completed": False,
    }
    try:
        async with native_connection(binary, dummy, root, args.superset_url, audit, budget) as (native, skill):
            report["installed_skill_sha256"] = hashlib.sha256(skill.encode()).hexdigest()
            _, cards = await native.call_tool("list_insight_cards", {})
            report["initial_card_count"] = len(cards["cards"])
            if cards["cards"]:
                raise ValueError("Probe home must start empty")
            for resource in args.resource:
                _, snapshot = await native.call_tool("inspect_resource", {
                    "adapter": "superset", "resource": resource,
                })
                report["snapshots"].append(snapshot)
            if proposal:
                _, drafted = await native.call_tool("onboard_insight_card", proposal)
                report["draft_response"] = drafted
                _, review = await native.call_tool("review_insight_card", {
                    "card_id": drafted["card"]["id"], "response_mode": "full",
                })
                report["review_response"] = review
                _, card = await native.call_tool("get_insight_card", {
                    "card_id": drafted["card"]["id"], "response_mode": "full",
                })
                report["saved_card"] = card
            if budget.used or budget.exhausted:
                raise ValueError("Fixed source probe unexpectedly attempted inference")
            report["completed"] = True
    finally:
        report["upstream_jev_requests"] = budget.used
        report["inference_attempt_blocked"] = budget.exhausted
        report["binary_unchanged"] = verify_binary(binary) == build
        copied = root / "native-home/typesafe.key"
        report["dummy_credential_only"] = copied.is_file() and copied.read_text().strip() == "not-a-live-provider-key"
        (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "completed": report["completed"], "source_count": len(report["snapshots"]),
        "upstream_jev_requests": budget.used, "report": str(root / "report.json"),
    }))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--resource", action="append", required=True)
    parser.add_argument("--proposal", help="JSON arguments for onboard_insight_card; no approval occurs")
    parser.add_argument("--superset-url", default="http://127.0.0.1:18089")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
