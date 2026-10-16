"""Read an actual retained trial receipt with a current native build, no inference.

Reconnect only the existing research home; never import cards or reconstruct
receipts. This checks serialization/persistence, not a new analytical outcome.
"""

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter, RequestBudget
from evaluations.domain_context_onboarding_trial import failure_detail, native_context
from evaluations.explicit_owner_conversation import AuditedNative
from scripts.binary_provenance import verify_binary
from signalweave.models import InsightCard


async def run(args):
    root, binary = Path(args.prior).resolve(), Path(args.binary).resolve()
    identity = verify_binary(binary)
    prior = json.loads((root / "report.json").read_text())
    events = [json.loads(line) for line in (root / "trace.jsonl").read_text().splitlines()]
    if prior.get("protocol") != "public-explicit-owner-v5" or prior.get("completed") is not True:
        raise ValueError("Requires a completed explicit-owner cohort, not an interrupted trial")
    expected = next(e["card"] for e in prior["episodes"] if e["arm"] == "signalweave" and e["stage"] == "author")
    old = next(e["result"] for e in events if e["kind"] == "tool.result"
               and e.get("episode") == "signalweave:report" and e.get("name") == "get_decision_receipt")
    owned = root / "private-native-state"
    if not (owned / "native-home/config.toml").is_file():
        raise ValueError("Original home is missing; no reconstruction is permitted")
    if any(path.is_symlink() for path in (owned, owned / "native-home", owned / "native-home/config.toml", owned / "company-mcp.json")):
        raise ValueError("Retained paths must not redirect writes")
    output = Path(args.output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    key = output / "dummy-key"
    key.write_text("synthetic-receipt-replay-no-inference")
    key.chmod(0o600)
    audit = Audit(path=output / "trace.jsonl", secrets=(key.read_text(),))
    public = json.loads((root / "public-onboarding-input.json").read_text())
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
    adapter.set_period(public["period"], datetime.fromisoformat(prior["read_clock"]),
                       measurement_offset=timedelta(seconds=prior["measurement_offset_seconds"]))
    budget = RequestBudget(limit=0)
    report = {"protocol": "native-receipt-dedup-replay-v1", "build": identity,
              "prior_report_sha256": hashlib.sha256((root / "report.json").read_bytes()).hexdigest(),
              "scope": __doc__}
    try:
        # The live credential was deliberately removed after the paid trial.
        # Use the supported CLI to install a dummy instead of bypassing setup's
        # existing-key protection or restoring a real credential.
        process = await asyncio.create_subprocess_exec(
            str(binary), "credentials", "set", "jev", "--home", str(owned / "native-home"),
            "--file", str(key), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(process.wait(), 60)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        if process.returncode != 0:
            raise RuntimeError("Native dummy-credential installation failed")
        report["credential_mode"] = "dummy installed through native credentials set; no real key"
        async with native_context(binary, key, public, adapter, audit, owned, request_budget=budget) as (native, _skill):
            native = AuditedNative(native, audit)
            _, before = await native.call_tool("get_insight_card", {"card_id": expected["id"], "response_mode": "full"})
            assert InsightCard.model_validate(before).execution_payload() == InsightCard.model_validate(expected).execution_payload()
            assert before["version"] == expected["version"] and before["status"] == "approved"
            _, result = await native.call_tool("get_decision_receipt", {"receipt_id": old["receipt"]["receipt_id"]})
            assert "result" not in result["receipt"]
            assert result["result"] == old["result"]
            assert result["receipt"] == {k: v for k, v in old["receipt"].items() if k != "result"}
            _, after = await native.call_tool("get_insight_card", {"card_id": expected["id"], "response_mode": "full"})
            assert after == before
            assert budget.used == 0 and adapter.inspections == 0
            report.update(completed=True, unchanged_result=True, unchanged_card=True,
                          old_bytes=len(json.dumps(old).encode()), new_bytes=len(json.dumps(result).encode()))
    except Exception as error:  # noqa: BLE001 - retain the failed probe
        report["failure"] = failure_detail(error)
    finally:
        report.update(provider_attempts=budget.used, source_reads=adapter.inspections,
                      native_calls=sum(e["kind"] == "native.operation.start" for e in audit.events))
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "prior", "output"):
        parser.add_argument("--" + name, required=True)
    result = asyncio.run(run(parser.parse_args()))
    print(json.dumps(result))
    if not result.get("completed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
