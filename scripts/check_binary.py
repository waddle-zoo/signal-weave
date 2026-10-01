"""Smoke-test a built binary in a private home, outside the checkout.

Offline by default. --live performs one approved synthetic investigation with
Jev, then proves replay across a separate binary process. No external delivery.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Test-only imports; this checker is never bundled into the executable.
from evaluations.local_investigation_trial import ROOT, cases, seed
from signalweave.models import DeliveryMethod, InsightCard, InsightCardStatus, Outcome, SourceRef
from signalweave.store import SQLiteInsightCardStore


def _check_stderr(stderr: str) -> None:
    if "Traceback" in stderr:
        raise RuntimeError("Binary emitted a traceback on stderr; diagnostic contents withheld")


async def check(binary: Path, key_file: Path, live: bool):
    with tempfile.TemporaryDirectory(prefix="signalweave-binary-check-") as temporary:
        folder = Path(temporary)
        home = folder / "home"
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("SIGNALWEAVE_", "TYPESAFE_", "SUPERSET_", "PRESET_", "TRINO_", "PYTHON"))}
        environment.pop("VIRTUAL_ENV", None)

        def command(*args):
            completed = subprocess.run([str(binary), *args], cwd=folder, env=environment,
                                       text=True, capture_output=True, timeout=90)
            _check_stderr(completed.stderr)
            if completed.returncode:
                raise RuntimeError(f"Binary command failed ({completed.returncode}); diagnostic contents withheld")
            return completed.stdout

        # Stage a private input without altering the user's original key file.
        private_key = folder / "input.key"
        descriptor = os.open(private_key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as target:
            target.write(key_file.read_text())
        command("init", "--home", str(home), "--key-file", str(private_key))
        assert "Offline configuration check" in command("doctor", "--home", str(home))
        snippet = json.loads(command("agent-config", "--agent", "claude", "--home", str(home)))
        assert str(binary) in json.dumps(snippet)
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as stderr:
            try:
                async with stdio_client(StdioServerParameters(
                    command=str(binary), args=["serve", "--home", str(home)],
                    cwd=str(folder), env=environment,
                ), errlog=stderr) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        names = [tool.name for tool in (await session.list_tools()).tools]
                        assert "onboard_insight_card" in names and "evaluate_insight_card" in names
            except Exception:
                raise RuntimeError("Binary stdio check failed; diagnostic contents withheld") from None
            # Check after transport teardown: frozen shutdown tracebacks arrive after
            # initialize/list_tools succeed and can accompany a zero process exit.
            stderr.seek(0)
            for line in stderr:
                _check_stderr(line)
        result = {"standalone_startup": True, "private_init": True, "offline_doctor": True,
                  "stdio_tools": len(names), "different_cwd": True, "live": live}
        if live:
            database = folder / "company.sqlite"
            _, kind, rows, coverage, *_ = next(cases())
            seed(database, kind, rows, coverage)
            manifest = {"version": 1, "connections": [{
                "name": "company_metrics", "tenant_id": "local", "read_only": True,
                "transport": {"type": "stdio", "command": [sys.executable, str(ROOT / "examples/local-investigation/company_mcp.py"), str(database)]},
                "resources": [{"descriptor": {"adapter": "company_metrics", "resource": "activity", "kind": "measurement", "title": "Activity", "contract": {"tenant_id": "local"}},
                               "source_key": "activity", "tool": "read_comparison"}],
            }]}
            source_file = folder / "sources.json"
            source_file.write_text(json.dumps(manifest))
            environment["SIGNALWEAVE_MCP_SOURCES_FILE"] = str(source_file)
            store = SQLiteInsightCardStore(home / "state/signalweave.db")
            store.save_card(InsightCard(
                id="binary-proof", title="Activity change", status=InsightCardStatus.APPROVED,
                what_to_watch="Activity change and segment contributions", why_watch="Notify the owner about changed activity",
                decision_guidance="Notify on a complete analysis with a nonzero delta. Insufficient data if required calculations fail. Decomposition is not causation.",
                comparison_windows=["previous_period"], sources=[SourceRef(key="activity", adapter="company_metrics", resource="activity", label="Activity", required_comparison_keys=["activity-breakdown"])],
                delivery_methods=[DeliveryMethod(key="owner", outcome=Outcome.NOTIFY, label="Owner", destination="agent://owner")],
            ))
            args = ("run", "binary-proof", "--run-key", "period:1", "--home", str(home), "--output", str(folder / "output"))
            first = json.loads(command(*args))
            assert first["result"]["analyses"][0]["delta"] == -20
            assert first["result"]["outcome"] == "notify"
            assert first["receipt"]["delivery_enabled"] is False
            replay = json.loads(command(*args))
            assert replay["replayed"] and first["result"] == replay["result"]
            result.update({"live_outcome": "notify", "measured_delta": -20, "process_restart_replay": True})
        print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "dist/signalweave")
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    asyncio.run(check(args.binary.resolve(), args.key_file.resolve(), args.live))


if __name__ == "__main__":
    main()
