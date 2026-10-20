"""Opt-in native context proof against an explicitly configured Superset fixture."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from scripts.binary_provenance import verify_binary

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_CONTEXT_SUPERSET_INTEGRATION") != "1",
    reason="requires explicit native binary, provider startup credential, and local Superset fixture",
)


@pytest.fixture
def isolated_state(tmp_path):
    with tempfile.TemporaryDirectory(prefix="context-native-", dir=tmp_path) as directory:
        yield Path(directory).resolve()


async def test_current_native_context_setup_review_reuse_and_restart(tmp_path, isolated_state):
    binary = Path(os.environ["SIGNALWEAVE_BINARY"]).resolve()
    provenance = verify_binary(binary)
    assert provenance["frozen"] is True
    credential = Path(os.environ["TYPESAFE_API_KEY_FILE"]).resolve()
    assert credential.is_file()
    # All generated state is canonical/private, never the contributor's local profile.
    private_home = isolated_state / "native-home"
    password = isolated_state / "superset-password"
    password.write_text(os.getenv("SUPERSET_PASSWORD", "admin"))
    password.chmod(0o600)
    env = {name: value for name, value in os.environ.items()
           if name in {"PATH", "TMPDIR", "LANG", "LC_ALL"}}
    env["SIGNALWEAVE_KNOWLEDGE_ENABLED"] = "1"
    superset_url = os.getenv("SUPERSET_URL", "http://127.0.0.1:18089").rstrip("/")
    setup = subprocess.run([
        str(binary), "setup", "--home", str(private_home), "--non-interactive",
        "--key-file", str(credential), "--source", "superset",
        "--url", superset_url,
        "--username", os.getenv("SUPERSET_USERNAME", "admin"), "--secret-file", str(password),
        "--tenant", "context-integration", "--principal", "context-curator",
        "--agent", "codex", "--no-register-agent",
    ], env=env, cwd=isolated_state, capture_output=True, timeout=90)
    assert setup.returncode == 0, "native setup failed; inspect private fixture configuration"
    params = StdioServerParameters(
        command=str(binary), args=["serve", "--home", str(private_home)], env=env, cwd=str(isolated_state),
    )

    async def call(session, name, arguments):
        result = await session.call_tool(name, arguments)
        assert not result.isError, f"context tool failed: {name}"
        return result.structuredContent or json.loads(result.content[0].text)

    entry_id = None
    log_path = tmp_path / "native-context.log"
    async with asyncio.timeout(180):
        with log_path.open("w") as log:
            for restarted in (False, True):
                async with stdio_client(params, errlog=log) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        tools = {tool.name for tool in (await session.list_tools()).tools}
                        assert "retrieve_domain_context" in tools
                        if not restarted:
                            resource = os.getenv("SUPERSET_CONTEXT_RESOURCE", "chart:1")
                            saved = await call(session, "save_domain_context", {"content": {
                                "domain": "integration-proof", "title": "Context source identity check",
                                "body": "Check current measurement periods separately; this is a synthetic protocol note.",
                                "kind": "definition", "provenance": ["Explicit integration fixture"],
                                "sources": [{"key": "fixture", "adapter": "superset",
                                             "resource": resource, "label": "Configured fixture asset"}],
                                "review_after": (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
                            }})
                            entry_id = saved["id"]
                            reviewed = await call(session, "review_domain_context", {
                                "entry_id": entry_id, "expected_revision": 1,
                                "action": "approve", "reason": "Synthetic fixture review, not an analytical certification.",
                            })
                            assert reviewed["revision"] == 2
                        packet = await call(session, "retrieve_domain_context", {"query": "source identity"})
                        assert [entry["id"] for entry in packet["entries"]] == [entry_id]
                        assert packet["entries"][0]["status"] == "reviewed"
                        assert packet["entries"][0]["revision"] == 2
    logs = log_path.read_text()
    assert "POST https://api.typesafe.ai/v1/systemone" not in logs
    assert f"GET {superset_url}/api/v1/" in logs  # actual metadata authorization, not a fixture adapter
