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
from signalweave.knowledge_mcp import KNOWLEDGE_TOOLS

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_CONTEXT_CARD_INTEGRATION") != "1",
    reason=(
        "requires an explicitly verified native binary "
        "and local synthetic Superset fixture on port 18089"
    ),
)

MAX_TOOL_CALLS = 18
MAX_PROVIDER_POSTS = 0
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

    credential = isolated_workspace / "synthetic-startup-key"
    credential.write_text("synthetic-context-card-no-inference")
    credential.chmod(0o600)

    # Only pass process basics to the native CLI. Provider and Superset secrets
    # are referenced by private files, never copied into arguments or logs.
    env = {
        name: value
        for name, value in os.environ.items()
        if name in {"PATH", "TMPDIR", "LANG", "LC_ALL"}
    }
    env["SIGNALWEAVE_KNOWLEDGE_ENABLED"] = "1"
    # No process can listen on TCP port zero: a bind to zero receives a different
    # assigned port. Accidental inference must fail locally, never reach TypeSafe.
    env["TYPESAFE_BASE_URL"] = "http://127.0.0.1:0"
    env["TYPESAFE_MAX_RETRIES"] = "0"

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
            plain_params = StdioServerParameters(
                command=str(binary), args=["serve", "--home", str(private_home)],
                env={**env, "SIGNALWEAVE_KNOWLEDGE_ENABLED": "0"}, cwd=str(isolated_workspace),
            )
            async with stdio_client(plain_params, errlog=log) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    plain_tools = {tool.name for tool in (await session.list_tools()).tools}
                    assert "get_signalweave_guide" in plain_tools
                    assert not KNOWLEDGE_TOOLS & plain_tools
                    plain_start = _payload(await call(session, "get_signalweave_guide", {"task": "start"}), "get_signalweave_guide")
                    plain_monitor = _payload(await call(session, "get_signalweave_guide", {"task": "monitor"}), "get_signalweave_guide")
                    assert isinstance(plain_start["first_readout"], str) and plain_start["first_readout"].strip()
                    assert "first_readout" not in plain_monitor
                    assert plain_start["inference_performed"] is plain_monitor["inference_performed"] is False

            async with stdio_client(server_params, errlog=log) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    tool_names = {tool.name for tool in (await session.list_tools()).tools}
                    expected_tools = {
                        "onboard_insight_card",
                        "revise_insight_card",
                        "save_domain_context",
                        "review_domain_context",
                        "bind_insight_context",
                        "inspect_insight_context",
                        "evaluate_insight_card",
                    }
                    assert expected_tools <= tool_names
                    approval_tool = next(tool for tool in (await session.list_tools()).tools
                                         if tool.name == "approve_insight_card")
                    assert "does not expose draft simulation" in approval_tool.description

                    start_guide = _payload(await call(session, "get_signalweave_guide", {"task": "start"}), "get_signalweave_guide")
                    monitor_guide = _payload(await call(session, "get_signalweave_guide", {"task": "monitor"}), "get_signalweave_guide")
                    assert isinstance(start_guide["first_readout"], str) and start_guide["first_readout"].strip()
                    assert "first_readout" not in monitor_guide
                    assert start_guide["inference_performed"] is monitor_guide["inference_performed"] is False

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
                    assert onboarded["next_action"] != "simulate_then_approve"
                    assert onboarded["card"]["status"] == "draft"
                    card_id = onboarded["card"]["id"]
                    approval = onboarded["approval_handoff"]
                    assert approval["arguments_after_owner_confirmation"]["card_id"] == card_id
                    assert "source_selection_reason" not in approval["arguments_after_owner_confirmation"]
                    assert "confirm_saved_policy_and_source_scopes" in approval["owner_input_required"]
                    assert "source_selection_reason" not in approval["owner_input_required"]
                    assert "source_selection_reason" in approval["agent_input_after_confirmation"]
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

                    revised = _payload(await call(session, "revise_insight_card", {
                        "card_id": card_id, "expected_card_version": bound["version"],
                        "changes": {"decision_guidance": "Report only supported fixture observations; policy remains under owner review.",
                                    "questions": []},
                        "reason": "Apply a synthetic owner clarification to the same card.",
                    }), "revise_insight_card")
                    assert revised["card"]["id"] == card_id
                    assert revised["card"]["version"] == bound["version"] + 1
                    assert revised["card"]["status"] == "draft"
                    assert revised["card"]["context_bindings"] == bound["context_bindings"]
                    assert revised["card"]["sources"][0]["resource"] == "chart:1"

                    fresh_review = _payload(await call(session, "review_insight_card", {
                        "card_id": card_id,
                    }), "review_insight_card")
                    old_args = approval["arguments_after_owner_confirmation"]
                    new_args = fresh_review["approval_handoff"]["arguments_after_owner_confirmation"]
                    assert old_args["source_selection_fingerprint"] != new_args["source_selection_fingerprint"]
                    stale_approval = await call(session, "approve_insight_card", {
                        **old_args,
                        "source_selection_reason": "Confirm only the original displayed fixture policy.",
                    })
                    assert stale_approval.isError
                    assert "stale" in " ".join(
                        item.text for item in (stale_approval.content or [])
                        if getattr(item, "text", None)
                    ).lower()
                    still_draft = _payload(await call(session, "get_insight_card", {
                        "card_id": card_id,
                    }), "get_insight_card")
                    assert still_draft["status"] == "draft"
                    assert still_draft["version"] == revised["card"]["version"]

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
