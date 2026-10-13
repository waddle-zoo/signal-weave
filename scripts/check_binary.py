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

if __package__:
    from .binary_provenance import verify_binary
else:
    from binary_provenance import verify_binary

ROOT = Path(__file__).resolve().parents[1]
_SMOKE_ENVIRONMENT_PREFIXES = (
    "SIGNALWEAVE_", "TYPESAFE_", "SUPERSET_", "PRESET_", "TRINO_", "OPENAI_",
    "PYTHON", "DYLD_", "LD_",
)


def _smoke_environment(user_home: Path) -> dict[str, str]:
    """Keep host credentials and interpreter/loader settings out of the binary."""
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(_SMOKE_ENVIRONMENT_PREFIXES)
    }
    environment.pop("VIRTUAL_ENV", None)
    environment["HOME"] = str(user_home)
    return environment


def _check_stderr(stderr: str) -> None:
    if "Traceback" in stderr:
        raise RuntimeError("Binary emitted a traceback on stderr; diagnostic contents withheld")


async def check(binary: Path, key_file: Path | None, live: bool):
    identity = verify_binary(binary)
    with tempfile.TemporaryDirectory(prefix="signalweave-binary-check-") as temporary:
        # macOS aliases /var to /private/var; the setup contract rejects symlink
        # ancestors. Canonicalize only this newly created temporary test directory.
        folder = Path(temporary).resolve()
        user_home = folder / "isolated-user"
        user_home.mkdir(mode=0o700)
        home = user_home / ".signalweave"
        environment = _smoke_environment(user_home)

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
            target.write(key_file.read_text() if key_file else "offline-packaging-check-not-a-real-key")
        source_secret = folder / "source.key"
        descriptor = os.open(source_secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as target:
            target.write("offline-source-check-not-a-real-password")
        command(
            "setup", "--non-interactive", "--home", str(home),
            "--key-file", str(private_key), "--source", "superset",
            "--url", "http://127.0.0.1:8080", "--username", "packaging-user",
            "--secret-file", str(source_secret), "--tenant", "local",
            "--principal", "packaging-agent", "--agent", "codex",
        )
        # Assert persisted identity/source configuration, without exposing secrets.
        import tomllib

        settings = tomllib.loads((home / "config.toml").read_text())["environment"]
        expected_version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
        binary_version = command("--version").strip()
        if binary_version != f"SignalWeave {expected_version}":
            raise RuntimeError("Binary version does not match the source release candidate")
        assert settings["SIGNALWEAVE_TENANT_ID"] == settings["SUPERSET_TENANT_ID"] == "local"
        assert settings["SIGNALWEAVE_PRINCIPAL_ID"] == "packaging-agent"
        assert settings["SUPERSET_URL"] == "http://127.0.0.1:8080"
        assert "SUPERSET_PASSWORD_FILE" in settings and "SUPERSET_PASSWORD" not in settings
        assert "TYPESAFE_API_KEY_FILE" in settings and "TYPESAFE_API_KEY" not in settings
        # The original credential inputs can disappear; setup must have copied them.
        private_key.unlink()
        source_secret.unlink()
        assert "Offline configuration check" in command("health", "--home", str(home))
        assert "Offline configuration check" in command("doctor", "--home", str(home))
        snippet = json.loads(command("agent-config", "--agent", "claude", "--home", str(home)))
        assert str(binary) in json.dumps(snippet)
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as stderr:
            try:
                async with stdio_client(StdioServerParameters(
                    # Exercise the real local-install command: setup saves the
                    # default profile and a bare `serve` must discover it.
                    command=str(binary), args=["serve"],
                    cwd=str(folder), env=environment,
                ), errlog=stderr) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        names = [tool.name for tool in (await session.list_tools()).tools]
                        assert "onboard_insight_card" in names and "evaluate_insight_card" in names
                        assert "get_signalweave_guide" in names
                        # The default agent profile intentionally exposes the
                        # minimal guide set; query/report guides require full.
                        for task in ("start", "monitor"):
                            guide = await session.call_tool("get_signalweave_guide", {"task": task})
                            assert not guide.isError
                            assert guide.structuredContent["task"] == task
            except Exception:
                raise RuntimeError("Binary stdio check failed; diagnostic contents withheld") from None
            # Check after transport teardown: frozen shutdown tracebacks arrive after
            # initialize/list_tools succeed and can accompany a zero process exit.
            stderr.seek(0)
            for line in stderr:
                _check_stderr(line)
        result = {"standalone_startup": True, "private_setup": True, "default_home_serve": True,
                  "persisted_source_config": True,
                  "offline_doctor": True, "health_alias": True, "agent_config": True,
                  "stdio_tools": len(names), "different_cwd": True, "live": live,
                  "version": binary_version}
        result["build"] = identity
        result["orientation_paths"] = ["start", "monitor"]
        # Exercise the no-Jev install variants in the actual frozen binary.
        openai_key = folder / "openai-input.key"
        openai_key.write_text("offline-openai-packaging-check-not-a-real-key")
        openai_key.chmod(0o600)
        openai_home = user_home / "openai-profile"
        command(
            "setup", "--non-interactive", "--home", str(openai_home),
            "--decision-provider", "openai-decisions", "--openai-key-file", str(openai_key),
            "--source", "skip", "--no-register-agent",
        )
        openai_settings = tomllib.loads((openai_home / "config.toml").read_text())["environment"]
        assert openai_settings["SIGNALWEAVE_DECISION_PROVIDER"] == "openai-decisions"
        assert "TYPESAFE_API_KEY_FILE" not in openai_settings
        assert "OPENAI_API_KEY: configured" in command("status", "--home", str(openai_home))

        chatgpt_home = user_home / "chatgpt-profile"
        command(
            "setup", "--non-interactive", "--home", str(chatgpt_home),
            "--decision-provider", "chatgpt-plan", "--source", "skip", "--no-register-agent",
        )
        chatgpt_settings = tomllib.loads((chatgpt_home / "config.toml").read_text())["environment"]
        assert chatgpt_settings["SIGNALWEAVE_DECISION_PROVIDER"] == "chatgpt-plan"
        assert "TYPESAFE_API_KEY_FILE" not in chatgpt_settings
        assert "OPENAI_API_KEY_FILE" not in chatgpt_settings
        assert "ChatGPT plan: not_connected" in command("auth", "status", "--home", str(chatgpt_home))
        result["decision_provider_setup"] = ["jev", "openai-decisions", "chatgpt-plan"]
        if live:
            # Test-only imports; neither trial fixtures nor this checker are bundled.
            sys.path.insert(0, str(ROOT))
            from evaluations.local_investigation_trial import cases, seed
            from signalweave.models import (
                DeliveryMethod,
                InsightCard,
                InsightCardStatus,
                Outcome,
                SourceRef,
            )
            from signalweave.store import SQLiteInsightCardStore

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
                principal_tenant="local",
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
    parser.add_argument("--key-file", type=Path, help="Required only for --live; offline smoke uses a dummy key")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.live and not args.key_file:
        parser.error("--live requires --key-file")
    os.umask(0o077)
    asyncio.run(check(args.binary.resolve(), args.key_file.resolve() if args.key_file else None, args.live))


if __name__ == "__main__":
    main()
