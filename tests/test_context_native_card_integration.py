"""Opt-in native lifecycle proof for source-bound card context."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from scripts.binary_provenance import verify_binary

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_CONTEXT_CARD_INTEGRATION") != "1",
    reason=(
        "requires an explicitly verified native binary, provider startup key file, "
        "and local synthetic Superset fixture on port 18089"
    ),
)

MAX_TOOL_CALLS = 15
MAX_PROVIDER_POSTS = 1
PROVIDER_ENDPOINT = re.compile(
    r"POST https://api\.typesafe\.ai/v1/systemone(?:\s|$)"
)


def _payload(result, tool_name: str) -> dict:
    assert not result.isError, f"native MCP tool failed: {tool_name}"
    structured = result.structuredContent
    if structured is not None:
        return structured
    return json.loads(result.content[0].text)


@pytest.fixture
def isolated_workspace(tmp_path):
    with tempfile.TemporaryDirectory(
        prefix="context-card-native-", dir=tmp_path.resolve()
    ) as directory:
        yield Path(directory).resolve()


@pytest.mark.asyncio
async def test_native_agent_context_binding_lifecycle(
    isolated_workspace, record_property
):
    binary_input = Path(os.environ["SIGNALWEAVE_BINARY"]).expanduser()
    provenance = verify_binary(binary_input)
    assert provenance["frozen"] is True
    binary = binary_input.resolve()

    credential = Path(os.environ["TYPESAFE_API_KEY_FILE"]).expanduser().resolve()
    assert credential.is_file(), "configured private provider key file is unavailable"

    # Only pass process basics to the native CLI. Provider and Superset secrets
    # are referenced by private files, never copied into arguments or logs.
    env = {
        name: value
        for name, value in os.environ.items()
        if name in {"PATH", "TMPDIR", "LANG", "LC_ALL"}
    }
    env["SIGNALWEAVE_KNOWLEDGE_ENABLED"] = "1"

    private_home = isolated_workspace / "native-home"
    password_file = isolated_workspace / "superset-password"
    password_file.write_text(os.getenv("SUPERSET_PASSWORD", "admin"), encoding="utf-8")
    password_file.chmod(0o600)
    superset_url = "http://127.0.0.1:18089"

    setup_args = [
        str(binary),
        "setup",
        "--home",
        str(private_home),
        "--profile",
        "agent",
        "--non-interactive",
        "--key-file",
        str(credential),
        "--source",
        "superset",
        "--url",
        superset_url,
        "--username",
        os.getenv("SUPERSET_USERNAME", "admin"),
        "--secret-file",
        str(password_file),
        "--tenant",
        "context-card-integration",
        "--principal",
        "context-card-curator",
        "--agent",
        "codex",
        "--no-register-agent",
    ]
    server_params = StdioServerParameters(
        command=str(binary),
        args=["serve", "--home", str(private_home)],
        env=env,
        cwd=str(isolated_workspace),
    )

    call_names: list[str] = []

    async def call(session, name: str, arguments: dict):
        if len(call_names) >= MAX_TOOL_CALLS:
            raise AssertionError("native lifecycle exceeded its bounded MCP tool-call budget")
        call_names.append(name)
        return await session.call_tool(name, arguments)

    entry_id = None
    card_id = None
    log_path = isolated_workspace / "native-context-card.log"

    async with asyncio.timeout(180):
        setup = await asyncio.create_subprocess_exec(
            *setup_args,
            env=env,
            cwd=str(isolated_workspace),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(setup.wait(), timeout=60)
        except TimeoutError:
            setup.kill()
            await setup.wait()
            raise AssertionError("isolated native setup exceeded its time limit") from None
        assert setup.returncode == 0, "isolated native setup failed"

        with log_path.open("w", encoding="utf-8") as log:
            log_path.chmod(0o600)
            async with stdio_client(server_params, errlog=log) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    tool_names = {tool.name for tool in (await session.list_tools()).tools}
                    expected_tools = {
                        "onboard_insight_card",
                        "save_domain_context",
                        "review_domain_context",
                        "bind_insight_context",
                        "inspect_insight_context",
                        "evaluate_insight_card",
                    }
                    assert expected_tools <= tool_names

                    onboarded = _payload(
                        await call(
                            session,
                            "onboard_insight_card",
                            {
                                "title": "Native context binding smoke",
                                "what_to_watch": "Inspect this selected chart.",
                                "why_watch": (
                                    "Exercise the source-linked context lifecycle against "
                                    "the local synthetic Superset fixture."
                                ),
                                "questions": [
                                    "What observations are present in this chart?"
                                ],
                                "selected_sources": [
                                    {
                                        "ref": "superset|chart:1",
                                        "key": "selected-chart",
                                        "label": "Selected chart 1",
                                        "required": True,
                                    }
                                ],
                                "response_mode": "compact",
                            },
                        ),
                        "onboard_insight_card",
                    )
                    assert onboarded["approval_required"] is True
                    assert onboarded["delivery_enabled"] is False
                    assert onboarded["card"]["status"] == "draft"
                    card_id = onboarded["card"]["id"]
                    assert any(
                        source["adapter"] == "superset"
                        and source["resource"] == "chart:1"
                        for source in onboarded["card"]["sources"]
                    )

                    source_link = {
                        "key": "selected-chart",
                        "adapter": "superset",
                        "resource": "chart:1",
                        "label": "Selected chart 1",
                        "required": True,
                    }
                    note = {
                        "domain": "native-context-integration",
                        "title": "Synthetic selected-chart context",
                        "body": (
                            "This synthetic note is linked to the selected chart for "
                            "lifecycle verification; it adds no metric definition or threshold."
                        ),
                        "kind": "observation",
                        "sources": [source_link],
                        "provenance": ["Local synthetic integration fixture"],
                        "review_after": (
                            datetime.now(timezone.utc) + timedelta(days=14)
                        ).isoformat(),
                    }
                    saved = _payload(
                        await call(
                            session,
                            "save_domain_context",
                            {"content": note},
                        ),
                        "save_domain_context",
                    )
                    assert saved["status"] == "draft"
                    entry_id = saved["id"]

                    reviewed = _payload(
                        await call(
                            session,
                            "review_domain_context",
                            {
                                "entry_id": entry_id,
                                "expected_revision": saved["revision"],
                                "action": "approve",
                                "reason": "Approve the synthetic lifecycle fixture note.",
                            },
                        ),
                        "review_domain_context",
                    )
                    assert reviewed["status"] == "reviewed"

                    bound = _payload(
                        await call(
                            session,
                            "bind_insight_context",
                            {
                                "card_id": card_id,
                                "expected_card_version": onboarded["card"]["version"],
                                "pins": [
                                    {
                                        "entry_id": entry_id,
                                        "revision": reviewed["revision"],
                                        "required_for_action": True,
                                    }
                                ],
                                "reason": "Pin the reviewed fixture context to this draft card.",
                            },
                        ),
                        "bind_insight_context",
                    )
                    assert bound["status"] == "draft"
                    assert bound["context_bindings"][0]["revision"] == reviewed["revision"]

                    inspected = _payload(
                        await call(
                            session,
                            "inspect_insight_context",
                            {"card_id": card_id},
                        ),
                        "inspect_insight_context",
                    )
                    assert inspected["required_current"] is True
                    assert inspected["entries"][0]["status"] == "current"
                    inspected_json = json.dumps(inspected)
                    assert note["title"] not in inspected_json
                    assert note["body"] not in inspected_json

            # The same private home is reopened by a new native server process.
            async with stdio_client(server_params, errlog=log) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    after_restart = _payload(
                        await call(
                            session,
                            "inspect_insight_context",
                            {"card_id": card_id},
                        ),
                        "inspect_insight_context",
                    )
                    assert after_restart["required_current"] is True
                    assert after_restart["entries"][0]["status"] == "current"

                    revised_note = dict(note)
                    revised_note["body"] = (
                        "A new draft revision exists for this synthetic lifecycle test."
                    )
                    edited = _payload(
                        await call(
                            session,
                            "save_domain_context",
                            {
                                "entry_id": entry_id,
                                "expected_revision": reviewed["revision"],
                                "content": revised_note,
                            },
                        ),
                        "save_domain_context",
                    )
                    assert edited["status"] == "draft"
                    assert edited["revision"] == reviewed["revision"] + 1

                    superseded = _payload(
                        await call(
                            session,
                            "inspect_insight_context",
                            {"card_id": card_id},
                        ),
                        "inspect_insight_context",
                    )
                    assert superseded["required_current"] is False
                    assert superseded["entries"][0]["status"] == "superseded"

                    rejected = await call(
                        session,
                        "evaluate_insight_card",
                        {"card_id": card_id, "idempotency_key": "draft-must-not-run"},
                    )
                    assert rejected.isError
                    error_text = " ".join(
                        item.text
                        for item in (rejected.content or [])
                        if getattr(item, "text", None)
                    )
                    assert "draft" in error_text.lower()

        logs = log_path.read_text(encoding="utf-8")
        provider_posts = len(PROVIDER_ENDPOINT.findall(logs))
        superset_metadata_reads = logs.count(f"GET {superset_url}/api/v1/")
        assert superset_metadata_reads > 0, "the selected chart was not authorized through live Superset metadata"
        assert provider_posts <= MAX_PROVIDER_POSTS, (
            f"bounded onboarding made {provider_posts} TypeSafe System One POSTs; "
            f"limit is {MAX_PROVIDER_POSTS}"
        )
        assert len(call_names) <= MAX_TOOL_CALLS

    record_property("native_mcp_tool_calls", len(call_names))
    record_property("native_binary_sha256", provenance["binary_sha256"])
    record_property("native_source_sha256", provenance["source_sha256"])
    record_property("native_git_commit", provenance["git_commit"])
    record_property("observed_typesafe_systemone_posts", provider_posts)
    record_property("observed_superset_metadata_reads", superset_metadata_reads)
