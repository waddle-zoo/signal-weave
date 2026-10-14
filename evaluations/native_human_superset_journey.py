"""Opt-in downloaded-native wizard and first-report trial against real Superset.

Uses an isolated home and the actual Codex registration CLI. The candidate
archive must already have been downloaded from CI; this is NOT proof that the
candidate is published, nor a curl-installer test. Business rows may be synthetic,
but Superset HTTP, native MCP, and Codex inference are real. No private labels are
available to agents. Report quality requires independent review, not a tool label.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import pty
import select
import subprocess
import tarfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations.bootstrap_agent_trial import Audit, RequestBudget, function
from evaluations.codex_trial_transport import codex_episode
from evaluations.installed_trial_transport import InstalledServer, _initialize_mcp_session
from scripts.binary_provenance import verify_binary
from signalweave.models import SourceRef
from signalweave.superset_adapter import SupersetAdapter
from signalweave.superset_client import SupersetClient


def terminal_setup(binary: Path, env: dict, key: str, url: str) -> dict:
    master, slave = pty.openpty()
    process = subprocess.Popen([str(binary), "setup"], env=env, stdin=slave,
                               stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    pending = [
        ("Decision provider [1]:", "1\n"),
        ("TypeSafe / Jev API key (hidden):", key + "\n"),
        ("Source [skip]:", "1\n"),
        ("Source URL:", url + "\n"),
        ("Superset username:", "admin\n"),
        ("Superset password (hidden):", "admin\n"),
        ("Agent [codex]:", "1\n"),
        ("Add another source?", "n\n"),
        ("Connect SignalWeave to Codex now?", "y\n"),
        ("Install the bundled SignalWeave skill for Codex", "y\n"),
    ]
    text = ""
    started = time.monotonic()
    try:
        while time.monotonic() - started < 90:
            if select.select([master], [], [], .1)[0]:
                try:
                    part = os.read(master, 8192)
                except OSError:
                    break
                text += part.decode(errors="replace")
                if pending and pending[0][0] in text:
                    _, answer = pending.pop(0)
                    os.write(master, answer.encode())
            if process.poll() is not None:
                break
        if process.poll() is None:
            process.kill()
        code = process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
    return {"returncode": code, "seconds": time.monotonic() - started,
            "pending_prompts": [prompt for prompt, _ in pending],
            "transcript": text.replace(key, "[REDACTED]")}


class ReportSession:
    """Same live source helpers for both arms; treatment adds native tools."""

    phase = "analysis"
    setup_complete = False

    def __init__(self, adapter, native=None):
        self.adapter, self.native = adapter, native
        self.treatment = native is not None
        self.submission = None

    async def specs(self):
        specs = [
            function("find_dashboards", "Search saved dashboard titles; an empty query browses the catalog.",
                     {"query": {"type": "string"}}, ("query",)),
            function("read_dashboard", "Read saved chart definitions and rows, with provenance.",
                     {"id": {"type": "string"}}, ("id",)),
            function("read_chart_rows", "Read actual saved chart query rows (not normalized observations). "
                     "Pages are partial evidence; follow next_offset for more rows.",
                     {"id": {"type": "string"}, "offset": {"type": "integer", "minimum": 0},
                      "limit": {"type": "integer", "minimum": 1, "maximum": 250}}, ("id",)),
            function("submit_report", "Save your final human-facing report locally; no real notification.",
                     {"report": {"type": "string"}, "evidence_refs": {"type": "array", "items": {"type": "string"}},
                      "missing_context": {"type": "array", "items": {"type": "string"}}},
                     ("report", "evidence_refs", "missing_context")),
        ]
        if self.native:
            specs.extend({"name": tool.name, "description": tool.description or "",
                          "parameters": tool.inputSchema} for tool in await self.native.list_tools())
        return specs

    async def call(self, name, arguments):
        if name == "find_dashboards":
            result = await self.adapter.search_resources(arguments["query"], limit=10)
            return result.model_dump(mode="json")
        if name == "read_dashboard":
            resource = "dashboard:" + str(int(arguments["id"].removeprefix("dashboard:")))
            result = await self.adapter.inspect(SourceRef(
                key="primary", adapter="superset", resource=resource, label=resource))
            return result.model_dump(mode="json")
        if name == "read_chart_rows":
            chart_id = str(int(arguments["id"].removeprefix("chart:")))
            chart = await self.adapter.client.get_chart_metadata(chart_id)
            envelopes = await self.adapter.client.chart_data(chart)
            rows = [row for envelope in envelopes
                    for row in self.adapter.client._rows_from_result_item(envelope)]
            offset, limit = arguments.get("offset", 0), arguments.get("limit", 100)
            if offset < 0 or not 1 <= limit <= 250:
                raise ValueError("Invalid source row page")
            end = min(len(rows), offset + limit)
            return {"chart_id": chart_id, "title": chart.get("slice_name"),
                    "saved_query_definition": chart.get("params"), "rows": rows[offset:end],
                    "returned_query_row_count": len(rows), "offset": offset,
                    "next_offset": end if end < len(rows) else None,
                    "scope": "standalone saved chart query, not dashboard filter context",
                    "coverage": "partial_query_rows" if offset or end < len(rows) else "all_returned_query_rows"}
        if name == "submit_report":
            self.submission = arguments
            return {"saved": True, "delivery": "local_trial_report_only"}
        if self.native:
            _, result = await self.native.call_tool(name, arguments)
            return result
        raise ValueError("Tool unavailable")


async def run(args):
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    home = output / "human-home"
    install = home / ".local" / "bin"
    install.mkdir(mode=0o700, parents=True)
    archive = args.archive.resolve()
    expected = archive.with_name(archive.name + ".sha256").read_text().split()[0]
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise ValueError("Downloaded archive checksum does not match")
    with tarfile.open(archive) as package:
        entry = package.getmember("signalweave")
        if not entry.isfile():
            raise ValueError("Expected regular native binary")
        stream = package.extractfile(entry)
        assert stream is not None
        binary = install / "signalweave"
        binary.write_bytes(stream.read())
        binary.chmod(0o700)
    identity = verify_binary(binary)
    key = args.key_file.read_text().strip()
    audit = Audit(path=output / "audit.jsonl", secrets=(key,))
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "TMPDIR", "LANG", "LC_ALL"}}
    env.update(HOME=str(home), CODEX_HOME=str(home / ".codex"),
               PATH=str(install) + os.pathsep + env.get("PATH", ""))
    # An explicit CODEX_HOME must exist. This models an installed agent without
    # borrowing or overwriting the real user's agent configuration.
    (home / ".codex").mkdir(mode=0o700)
    result = {"binary": identity, "archive_sha256": expected,
              "archive_origin": args.archive_origin,
              "scope": "Native archive extraction, real PTY wizard, real isolated Codex registration, real Superset, two cold first-report agents",
              "limitations": ["Candidate is not a published release or curl-install test",
                              "Scripted human answers, not a human usability panel",
                              "Synthetic company on actual local Superset",
                              "First report is not proof of recurring card efficacy or external delivery"],
              "wizard": terminal_setup(binary, env, key, args.url)}
    def checkpoint():
        (output / "results.json").write_text(json.dumps(audit.redact(result), indent=2))
    checkpoint()
    if result["wizard"]["returncode"] or result["wizard"]["pending_prompts"]:
        raise RuntimeError("Native human wizard did not finish; see redacted results")
    inventory = subprocess.run(["codex", "mcp", "list", "--json"], env=env,
                               capture_output=True, text=True, timeout=30)
    result["agent_inventory"] = {"returncode": inventory.returncode,
                                 "entries": json.loads(inventory.stdout) if inventory.returncode == 0 else []}
    checkpoint()
    if inventory.returncode or not any(item.get("name") == "signalweave" and item.get("enabled")
                                      for item in result["agent_inventory"]["entries"]):
        raise RuntimeError("Codex registration not verified; no complete-onboarding claim")
    for command in (("status", "--json"), ("health", "--live", "--json")):
        proc = subprocess.run(["signalweave", *command], env=env, cwd=home,
                              capture_output=True, text=True, timeout=120)
        result[command[0]] = {"returncode": proc.returncode, "output": json.loads(proc.stdout)}
        checkpoint()
        if command[0] == "health" and (proc.returncode or not result["health"]["output"].get("healthy")):
            raise RuntimeError("Live source health failed; do not claim completed onboarding")
    instructions = (
        "You are helping a retail business owner using their BI tools. Produce a concise useful "
        "first report, not an onboarding checklist. Read definitions and rows rather than trusting titles. "
        "The business data is historical: report its actual dates, do not assert current freshness. "
        "Separate measured changes from hypotheses. Missing business thresholds should not prevent "
        "a factual report; list what the owner must clarify before unattended alerts. Use only available "
        "trial MCP tools; no shell, MCP resource-listing, or other tools. If searches fail, browse "
        "with an empty query rather than repeating synonyms. Finish after at most eight source reads, "
        "even if the sources cannot support every requested conclusion. Do not approve a recurring "
        "card without explicit owner review. "
        "If SignalWeave is available start with its guide; otherwise use company source tools. "
        "Finish by calling submit_report, then stop."
    )
    prompt = {"request": "Help me understand online sales and their contribution to net sales. "
              "I normally look at Executive Command Center and Digital Commerce Funnel. "
              "Find these saved Northstar dashboards, show the largest supported changes "
              "and what to investigate next. I want a short report for the digital commerce lead, "
              "not a wall of alerts. What context would you need from me to repeat this daily?"}
    for arm in ("baseline", "signalweave"):
        audit.episode = arm
        adapter = SupersetAdapter(SupersetClient(args.url, "admin", "admin"), tenant_id="local")
        async with stdio_client(StdioServerParameters(command=str(binary), args=["serve"], env=env)) as streams:
            async with ClientSession(*streams) as client:
                initialized = await _initialize_mcp_session(client)
                native = InstalledServer(client, initialized.instructions, audit) if arm == "signalweave" else None
                session = ReportSession(adapter, native)
                report = await codex_episode(session, key="", effort="xhigh", model="gpt-6-luna",
                    budget=RequestBudget(4), audit=audit, max_turns=12, max_tool_calls=30,
                    max_output_tokens=6000, timeout_seconds=480,
                    instructions_override=instructions, prompt_override=prompt)
                result[arm] = {"episode": report, "submission": session.submission,
                               "shared_source_helper_http_attempts": adapter.client.requests_made,
                               "http_accounting": "excludes native MCP HTTP; not a total cost comparison"}
                checkpoint()
    result["binary_after"] = verify_binary(binary)
    checkpoint()
    print(json.dumps({"output": str(output), "wizard_returncode": result["wizard"]["returncode"],
                      "arms": {arm: result[arm]["episode"]["status"] for arm in ("baseline", "signalweave")}}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-origin", choices=["github-actions", "local-build"], required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:18089")
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
