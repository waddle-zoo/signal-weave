"""Paid, opt-in published-install + real Cube onboarding pilot; no product imports this module.

Later revision/refresh/cohort stages remain required by the preregistered protocol.
This pilot never labels the larger study complete.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import shlex
import subprocess
import termios
import time
from pathlib import Path

import httpx
import jwt
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations.bootstrap_agent_trial import Audit
from evaluations.cube_source import CubeCompany
from evaluations.decisions_semantic_trial import Episode, actor, reader_instructions, save
from evaluations.enterprise_native_setup import (
    _codex_inventory,
    _run_json,
    _skill_check,
    isolated_environment,
    setup_prompt_plan,
    terminal_setup,
)
from evaluations.installed_trial_transport import (
    InstalledServer,
    _initialize_mcp_session,
    _manifest,
    _source_server,
    _SourceSession,
)
from evaluations.semantic_company import SemanticCompany
from scripts.binary_provenance import verify_binary
from scripts.check_ca_bundle import check_bundle
from signalweave.models import SourceRef

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "evaluations/protocols/cube-native-2026-10-25.json"


class CubeEpisode(Episode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.native_packets = []

    async def call(self, name, arguments):
        result = await super().call(name, arguments)
        if name == "evaluate_insight_card":
            self.native_packets.append(result)
        return result

    async def specs(self):
        tools = await super().specs()
        for tool in tools:
            if tool["name"] == "read_company_asset":
                tool["description"] = "Read an actual governed Cube measure, source definition, compiled SQL and completed-month result."
            if tool["name"] == "submit_report":
                schema = tool["parameters"]
                schema["properties"]["definition_revision"] = {
                    "type": "string", "description": "Exact revision ID returned by the governing source, not the SignalWeave context revision."}
                schema["properties"]["data_snapshot_id"] = {
                    "type": "string", "description": "Exact source result-snapshot ID supporting these figures, not a definition or query hash."}
                schema["required"].append("data_snapshot_id")
        return tools


def grade(submission, frozen, oracle, *, alternate=False):
    submission = submission or {}
    source = frozen["observations"][0]
    resource = frozen["resource"]
    revision = frozen["metadata"]["metric_revision"]
    expected = oracle.expected(resource)
    notify = expected["change_pct"] is not None and expected["change_pct"] < -10
    checks = {
        "submitted": bool(submission), "metric": submission.get("metric_id") == expected["metric_id"],
        "revision": submission.get("definition_revision") == revision,
        "snapshot": submission.get("data_snapshot_id") == frozen["metadata"]["data_snapshot_id"],
        "source": "company|" + resource in submission.get("source_refs", []),
        "unit": submission.get("unit") == source["unit"],
        "periods": (submission.get("current_period"), submission.get("previous_period")) == ("2026-09", "2026-08"),
        "policy": submission.get("outcome") == ("not_applicable" if alternate else "notify" if notify else "ignore"),
        "recipients": submission.get("recipients") == ([] if alternate or not notify else ["agent://finance"]),
    }
    for key in ("current", "previous"):
        value = submission.get(key)
        checks[key] = type(value) in (int, float) and abs(value - float(expected[key])) <= 0.005
    return checks


def public_installer_process(_command, **options):
    def controlling_terminal():
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        os.tcsetpgrp(0, os.getpgrp())
    command = (
        "set -o pipefail; curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' "
        "https://github.com/waddle-zoo/signal-weave/releases/download/v0.2.1/install.sh "
        "| sh -s -- --version v0.2.1 --setup"
    )
    return subprocess.Popen(["/bin/zsh", "-c", command], preexec_fn=controlling_terminal, **options)


async def run(args):
    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    key = args.key_file.read_text().strip()
    audit = Audit(path=root / "setup-trace.jsonl", secrets=(key,))
    fixture = json.loads((args.fixture / "fixture.json").read_text())
    control = json.loads(args.control_report.read_text())
    if (control.get("complete") is not True
            or control["restored"]["raw_rows_sha256"] != fixture["raw_seed_sha256"]
            or control["restored"]["model_sha256"] != fixture["model_sha256"]):
        raise ValueError("Require completed hand control and exact restored source/model identity before paying for agents")
    environment = dict(line.split("=", 1) for line in (args.fixture / "private.env").read_text().splitlines())
    token = jwt.encode({"sub": "finance-readonly", "exp": int(time.time()) + 7200},
                       environment["SW_CUBE_API_SECRET"], algorithm="HS256")
    oracle = SemanticCompany(args.fixture / "ledger", fixture["company"], seed=fixture["seed"])
    report = {"complete": False, "pilot_complete": False, "readers": [],
              "scope": "One continuous public-install/registered-Codex/real-Cube pilot; not the ten-pair cohort.",
              "pending": ["actual upstream model revision pilot", "owner reapproval and source correction", "ten fresh reader pairs", "independent prose review"],
              "provider_usage_instrumented": False}
    helpers = [Path(__file__), PROTOCOL, ROOT / "evaluations/cube_source.py", ROOT / "evaluations/cube_fixture.py",
               ROOT / "evaluations/cube_fixture_control.py", ROOT / "evaluations/cube_reconcile.py",
               ROOT / "evaluations/semantic_company.py", ROOT / "evaluations/cube/compose.yml",
               ROOT / "evaluations/codex_trial_transport.py", ROOT / "evaluations/decisions_semantic_trial.py",
               ROOT / "evaluations/installed_trial_transport.py", ROOT / "evaluations/bootstrap_agent_trial.py",
               ROOT / "evaluations/enterprise_native_setup.py", ROOT / "evaluations/native_runtime_identity.py"]
    save(root / "protocol.json", {"protocol": json.loads(PROTOCOL.read_text()), "fixture": fixture,
                                  "hand_control_sha256": hashlib.sha256(args.control_report.read_bytes()).hexdigest(),
                                  "postgres_phase": control["restored"],
                                  "source_hashes": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in helpers}})
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{fixture['port']}/cubejs-api/v1/",
                                headers={"Authorization": token}, trust_env=False) as client:
        company = CubeCompany(client, oracle)
        await company.refresh_catalog()
        async with _source_server(_SourceSession(company, audit, company.tenant_id)) as url:
            manifest = root / "sources.json"
            bindings = _manifest({"scenario_id": company.tenant_id, "catalog": company.descriptors()}, url)
            bindings["connections"][0]["context_namespace"] = "cube-semantic/" + fixture["company"]
            save(manifest, bindings)
            person = root / "person"
            person.mkdir(mode=0o700)
            binary = person / ".local/bin/signalweave"
            env = isolated_environment(person, args.codex)
            prompts = setup_prompt_plan(key, manifest)
            prompts[0].update(answer="2\n", label="OpenAI Decisions")
            prompts[1].update(id="openai_key", needle="OpenAI API key (hidden):")
            try:
                wizard = await asyncio.to_thread(terminal_setup, binary, person / ".signalweave", env, key, manifest,
                                                prompt_plan=prompts, popen_factory=public_installer_process, timeout_seconds=240)
                report["wizard"] = wizard
                if wizard["returncode"] or wizard["pending_prompts"]:
                    raise ValueError("Public installation/setup did not complete")
                lines = binary.read_text().splitlines()
                if lines[:2] != ["#!/bin/sh", "# SignalWeave managed runtime v1"] or len(lines) != 3:
                    raise ValueError("Unexpected installed launcher")
                runtime = Path(shlex.split(lines[2])[1])
                if not runtime.is_relative_to(person / ".local/bin/.signalweave-runtime"):
                    raise ValueError("Installed runtime escaped disposable home")
                report["build"] = verify_binary(runtime)
                report["ca_check"] = check_bundle(runtime.parent / "_internal/certifi/cacert.pem",
                                                  expected_sha256=report["build"]["tls_trust"]["bundle_sha256"])
                report["registration"] = await asyncio.to_thread(_codex_inventory, args.codex, person, env, binary, (key,))
                report["skill"] = await asyncio.to_thread(_skill_check, binary, person, env, (key,))
                enabled = await asyncio.to_thread(subprocess.run,
                    [str(binary), "context", "enable", "--home", str(person / ".signalweave")],
                    cwd=person, env=env, capture_output=True, text=True, timeout=30)
                report["context_enable"] = {"returncode": enabled.returncode,
                                            "stdout": audit.redact(enabled.stdout), "stderr": audit.redact(enabled.stderr)}
                report["health"] = await asyncio.to_thread(_run_json, binary, ("health", "--live"), person / ".signalweave", env, (key,))
                if (not report["registration"]["only_expected_signalweave_entry"]
                        or not report["skill"]["matches_native_bundle"] or report["context_enable"]["returncode"]
                        or report["health"]["returncode"]):
                    raise ValueError("Agent registration/skill/context setup did not complete")
                params = StdioServerParameters(command=str(binary), args=["serve", "--home", str(person / ".signalweave")], cwd=str(person), env=env)
                with (root / "native-stderr.txt").open("w") as errors:
                    async with stdio_client(params, errlog=errors) as streams, ClientSession(*streams) as session:
                        initialized = await _initialize_mcp_session(session)
                        installed = InstalledServer(session, initialized.instructions, audit)
                        onboarding = CubeEpisode(company, installed, onboarding=True)
                        instructions = ((ROOT / "skills/signalweave/SKILL.md").read_text()
                            + "\nThis is an isolated fictional company over a real Cube semantic layer. Use only the exposed tools. "
                            "The fictional Finance owner delegates technical validation, shared-definition review and card approval within the source-owned policy. "
                            "Discover and inspect the semantic metric before choosing. Give a useful first answer, save one shared reviewed Finance revenue definition, "
                            "pin its exact revision as required for action, and author/review/approve the retrospective monthly card. "
                            "For the explicitly archival comparison, max_source_age_hours=null is permitted; keep the source's exact periods and quality checks. "
                            "Read the owner policy in company notes. Never send or schedule. Call finish_onboarding when complete.")
                        response = await actor(onboarding, audit, args.codex, instructions,
                                               {"task": "Help Finance compare September with August revenue, and preserve the useful check for our other agents."}, onboarding=True)
                        report["onboarding"] = {"agent": response, "submission": onboarding.submission, "calls": onboarding.calls}
                        save(root / "report.json", report)
                        if response["status"] != "complete" or not onboarding.submission:
                            raise ValueError("Agent onboarding did not complete")
                        for index, (resource, question) in enumerate([
                            ("metric:net-revenue", "Give Finance a concise September versus August revenue update on its agreed reporting basis."),
                            ("metric:gross-revenue", "What were September and August gross ledger billings, including tax and before refunds? Is this the same measure as our Finance net-revenue check?"),
                        ]):
                            frozen = (await company.inspect(SourceRef(key="frozen", adapter=company.name, resource=resource, label="Revenue"))).model_dump(mode="json")
                            for arm in (["ordinary_context", "signalweave"] if index % 2 == 0 else ["signalweave", "ordinary_context"]):
                                reader = CubeEpisode(company, installed if arm == "signalweave" else None, notes=onboarding.submission)
                                reader_audit = Audit(path=root / f"pilot-{index}-{arm}.jsonl", secrets=(key,))
                                run_key = f"cube-native-pilot:{index}:{arm}"
                                result = await actor(reader, reader_audit, args.codex, reader_instructions(arm == "signalweave"),
                                                     {"question": question, "run_key": run_key, "as_of": "2026-10-25"})
                                checks = grade(reader.submission, frozen, oracle, alternate=index == 1)
                                checks["agent_complete"] = result["status"] == "complete"
                                if arm == "signalweave" and index == 0:
                                    calls = [call for call in reader.calls if call["name"] == "evaluate_insight_card"]
                                    checks["native_called_once"] = len(calls) == 1 and calls[0]["arguments"].get("idempotency_key") == run_key
                                    checks["native_fresh"] = len(reader.native_packets) == 1 and reader.native_packets[0].get("replayed") is False
                                    checks["native_provider"] = len(reader.native_packets) == 1 and reader.native_packets[0].get("result", {}).get("evaluator") == "openai-decisions"
                                    checks["native_receipt_key"] = len(reader.native_packets) == 1 and reader.native_packets[0].get("receipt", {}).get("idempotency_key") == run_key
                                report["readers"].append({"case": index, "arm": arm, "agent": result,
                                                         "submission": reader.submission, "calls": reader.calls,
                                                         "native_packets": reader.native_packets,
                                                         "checks": checks, "frozen_source": frozen,
                                                         "human_review": "pending independent review"})
                                save(root / "report.json", report)
                                if not all(checks.values()):
                                    raise ValueError("Pilot structured gate failed; preserve this attempt")
                        report["pilot_complete"] = True
            finally:
                report["cube_requests"] = company.requests
                save(root / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--control-report", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("Requires explicit --live; this makes paid Codex and Decisions calls")
    report = asyncio.run(run(args))
    print(json.dumps({"pilot_complete": report["pilot_complete"], "readers": len(report["readers"]), "complete": report["complete"]}))
    if not report["pilot_complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
