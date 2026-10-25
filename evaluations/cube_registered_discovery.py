"""Real installed Codex user-registry discovery, requiring its normal prior login.

No research proxy, copied authentication, user-config suppression or MCP transport override.
The explicitly authorized evaluation has one per-tool approval override; the
original failed approval-policy attempt remains a separate artifact.
This is a narrow installed-entry integration check, not a comparative trial.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

import httpx
import jwt

from evaluations.bootstrap_agent_trial import Audit
from evaluations.codex_trial_transport import DISABLED_FEATURES
from evaluations.cube_revision_probe import connect, source_environment
from evaluations.cube_source import CubeCompany
from evaluations.decisions_semantic_trial import save
from evaluations.installed_trial_transport import _source_server, _SourceSession
from evaluations.semantic_company import SemanticCompany


async def run(args):
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    person = args.pilot / "person"
    env = source_environment(person)
    config = person / ".codex/config.toml"
    config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    key = (person / ".signalweave/openai.key").read_text().strip()
    audit = Audit(path=args.output / "audit.jsonl", secrets=(key,))
    info = json.loads((args.fixture / "fixture.json").read_text())
    pilot = json.loads((args.pilot / "report.json").read_text())
    endpoint = json.loads((args.pilot / "sources.json").read_text())["connections"][0]["transport"]["url"]
    values = dict(line.split("=", 1) for line in (args.fixture / "private.env").read_text().splitlines())
    token = jwt.encode({"sub": "finance-readonly", "exp": int(time.time()) + 1800}, values["SW_CUBE_API_SECRET"], algorithm="HS256")
    oracle = SemanticCompany(args.fixture / "ledger", info["company"], seed=info["seed"])
    run_key = args.output.name + ":registered-entry"
    card = pilot["onboarding"]["submission"]["card"]
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{info['port']}/cubejs-api/v1/", headers={"Authorization": token}, trust_env=False) as client:
        company = CubeCompany(client, oracle)
        await company.refresh_catalog()
        async with _source_server(_SourceSession(company, audit, company.tenant_id), stable_url=endpoint):
            command = [str(args.codex), "exec", "--ephemeral", "--json", "--skip-git-repo-check", "--cd", str(person),
                       "--model", "gpt-6-luna", "--sandbox", "read-only", "-c", 'model_reasoning_effort="xhigh"',
                       "-c", 'cli_auth_credentials_store="file"', "-c", 'approval_policy="never"',
                       "-c", 'mcp_servers.signalweave.tools.evaluate_insight_card.approval_mode="approve"',
                       "-c", 'web_search="disabled"', "-c", "project_doc_max_bytes=0",
                       "-c", "features.skip_host_skill_discovery=true", "-c", "memories.use_memories=false",
                       "-c", "memories.generate_memories=false"]
            for feature in DISABLED_FEATURES:
                command.extend(["--disable", feature])
            command.append("-")
            prompt = ("This is a fictional integration check. Use the installed SignalWeave MCP, not shell or external tools. "
                f"Evaluate existing card {card['id']} exactly once, compact mode, new idempotency key {run_key}. "
                "Do not edit cards or context, send or schedule. Give a brief supported Finance handoff; if the approved meaning is no longer current, "
                "explain the focused review needed rather than inventing a policy decision. Keep the September/August 2026 archival scope explicit.")
            save(args.output / "command.json", {"argv": command, "prompt": prompt, "config_sha256": config_hash,
                "auth": "Human completed the normal Codex browser login in this disposable CODEX_HOME; no tokens copied."})
            process = await asyncio.create_subprocess_exec(*command, env=env, cwd=person,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(prompt.encode()), 240)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            audit.emit("codex.complete", returncode=process.returncode, stdout=stdout.decode(), stderr=stderr.decode())
            async def receipt(server):
                return (await server.call_tool("get_decision_receipt", {"idempotency_key": run_key}))[1]
            try:
                stored = await connect(person / ".local/bin/signalweave", person, env, audit, receipt)
            except Exception as error:
                report = {"complete": False, "checks": {"receipt_available": False},
                          "reason": audit.redact(str(error))[:1000], "cube_requests": company.requests}
                save(args.output / "report.json", report)
                return report
            judgment = stored["result"].get("judgment", {})
            checks = {
                "codex_success": process.returncode == 0,
                "unchanged_registry": hashlib.sha256(config.read_bytes()).hexdigest() == config_hash,
                "exact_key": stored["receipt"]["idempotency_key"] == run_key,
                "exact_card": stored["receipt"]["card_id"] == card["id"] and stored["receipt"]["card_version"] == card["version"],
                "deferred_changed_meaning": stored["result"]["outcome"] is None and judgment.get("reason") == "context_review_required",
                "zero_policy_attempts": judgment.get("provider_call_attempted") is False and judgment.get("provider_call_attempts") == 0,
                "no_delivery": stored["receipt"]["delivery_enabled"] is False,
            }
            report = {"complete": all(checks.values()), "checks": checks, "stored_receipt": stored,
                      "cube_requests": company.requests, "scope": "One actual registered-entry discovery check. Human prose review remains separate."}
            save(args.output / "report.json", report)
            return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("fixture", "pilot", "output", "codex"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("Requires --live and a separately completed normal Codex login")
    for name in ("fixture", "pilot", "output", "codex"):
        setattr(args, name, getattr(args, name).resolve())
    report = asyncio.run(run(args))
    print(json.dumps({"complete": report["complete"], "checks": report["checks"]}))
    if not report["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
