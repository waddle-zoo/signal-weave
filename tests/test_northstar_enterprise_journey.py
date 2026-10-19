"""Offline contracts for the opt-in Northstar whole-company journey."""
from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mcp import types

from evaluations import northstar_enterprise_journey as journey
from evaluations.bootstrap_agent_trial import Audit
from signalweave.mcp_server import AGENT_PROFILE_TOOLS


def _source():
    source = Mock(instructions="Northstar company source")
    names = set(journey.setup.SOURCE_TOOLS) | {f"private_unexposed_tool_{index:03}" for index in range(110)}
    source.list_tools = AsyncMock(return_value=[
        types.Tool(name=name, description="Read-only company tool", inputSchema={"type": "object"})
        for name in sorted(names)
    ])
    source.call_tool = AsyncMock(return_value=([], {"data": []}))
    return source


def _native(*names):
    native = Mock(instructions="SignalWeave native")
    native.list_tools = AsyncMock(return_value=[
        types.Tool(name=name, description="Native tool", inputSchema={"type": "object"})
        for name in names
    ])
    native.call_tool = AsyncMock(side_effect=lambda name, args: ([], {
        "card_id": args.get("card_id", "card-1"), "card": {"id": args.get("card_id", "card-1"), "status": "draft"},
    }))
    return native


def _workspace(root, arm="baseline"):
    folder = root / arm / "workspace"
    folder.mkdir(parents=True, mode=0o700)
    return folder


def test_periods_are_exact_half_open_retrospective_selectors_and_prompt_hides_future_ends():
    assert [journey.period_window(index) for index in range(7)] == [
        ("2026-07-27", "2026-08-03"), ("2026-08-03", "2026-08-10"),
        ("2026-08-10", "2026-08-17"), ("2026-08-17", "2026-08-24"),
        ("2026-08-24", "2026-08-31"), ("2026-08-31", "2026-09-07"),
        ("2026-09-07", "2026-09-14"),
    ]
    for arm in journey.ORDER:
        instructions, prompt = journey.task(arm)
        encoded = instructions + json.dumps(prompt)
        assert "not as-known-at-the-time" in instructions.lower()
        assert "not row-filtered" in instructions
        assert "native retrieval time is the actual current retrieval time" in instructions.lower()
        assert prompt["current_reporting_period"]["period_end_exclusive"] == journey.PERIOD_ENDS[0]
        assert all(later not in encoded for later in journey.PERIOD_ENDS[1:])


def test_known_incomplete_baseline_is_not_a_treatment_censor_and_artifact_names_are_open():
    baseline = {
        "process_complete": False,
        "inputs_unchanged": True,
        "usage": {"known": True, "usage": {"input_tokens": 100, "uncached_input_tokens": 80}},
    }
    journey._check_prior_baseline(baseline)
    assert journey._human_readable_artifacts({"operator-procedure.md": {}, "notes.txt": {}, "data.csv": {}}) == [
        "operator-procedure.md", "notes.txt",
    ]
    with pytest.raises(ValueError, match="usage is unknown"):
        journey._check_prior_baseline({**baseline, "usage": {"known": False}})
    with pytest.raises(ValueError, match="changed frozen source"):
        journey._check_prior_baseline({**baseline, "inputs_unchanged": False})


async def test_both_arms_have_same_company_owner_and_inbox_contract_but_only_treatment_has_import(tmp_path):
    baseline_workspace = _workspace(tmp_path, "baseline")
    treatment_workspace = _workspace(tmp_path, "signalweave")
    baseline = journey.NorthstarWorld(_source(), tmp_path, "baseline")
    treatment_native = _native(*sorted(AGENT_PROFILE_TOOLS))
    treatment = journey.NorthstarWorld(_source(), tmp_path, "signalweave", treatment_native)
    baseline.database_id = treatment.database_id = 1
    b_specs = await journey.NorthstarJourneyBridge(baseline.source, Audit(), baseline).specs()
    t_specs = await journey.NorthstarJourneyBridge(treatment.source, Audit(), treatment,
                                                    native=treatment_native).specs()
    b = {spec["name"]: spec for spec in b_specs}
    t = {spec["name"]: spec for spec in t_specs}
    assert {name for name in b if name.startswith("company_")} == {
        "company_" + name for name in journey.setup.SOURCE_TOOLS
    }
    assert {name for name in t if name.startswith("company_")} == {
        "company_" + name for name in journey.setup.SOURCE_TOOLS
    }
    assert len(await baseline.source.list_tools()) == 137
    assert not any("private_unexposed_tool" in name for name in b | t)
    assert journey.IMPORT_TOOL not in b
    assert journey.IMPORT_TOOL in t
    assert set(journey.LOCAL_TOOLS) <= set(b) & set(t)
    for specs in (b, t):
        description = specs["send_message"]["description"]
        assert "relative paths inside your workspace" in description
        assert "copied into recipient-accessible" in description
        assert "source_refs are retained as locators" in description
    assert baseline_workspace.exists() and treatment_workspace.exists()


async def test_native_failure_is_observed_but_does_not_block_consented_human_report(tmp_path):
    workspace = _workspace(tmp_path, "signalweave")
    source = _source()
    native = _native("onboard_insight_card", "review_insight_card", "get_insight_card",
                     "approve_insight_card", "evaluate_insight_card", "list_insight_cards")
    world = journey.NorthstarWorld(source, tmp_path, "signalweave", native)
    world.database_id = 1
    bridge = journey.NorthstarJourneyBridge(source, Audit(), world, native=native)
    native.restart = AsyncMock()
    native.select_period = Mock()
    original_call = native.call_tool

    async def fail_only_evaluation(name, args):
        if name == "evaluate_insight_card":
            raise RuntimeError("native evaluator unavailable")
        return await original_call(name, args)

    native.call_tool = AsyncMock(side_effect=fail_only_evaluation)

    await bridge.call("ask_dispatch_owner", {"question": "What is the business rule?"})
    await bridge.call("onboard_insight_card", {"what_to_watch": "Damage rate"})
    await bridge.call("review_insight_card", {"card_id": "card-1"})
    consent = await bridge.call("confirm_workflow", {"summary": "Weekly plan", "card_id": "card-1"})
    assert "fictional consent only" in consent["consent"]
    await bridge.call("approve_insight_card", {"card_id": "card-1"})
    with pytest.raises(RuntimeError, match="native evaluator unavailable"):
        await bridge.call("evaluate_insight_card", {
            "card_id": "card-1", "idempotency_key": "northstar-2026-08-03",
        })
    report = await bridge.call("send_message", {
        "to": "dispatch", "body": "Supported report with native evaluation deferred.",
        "source_refs": [], "workspace_files": [],
    })
    assert report["delivered"] and world.messages[0]["body"].startswith("Supported report")
    assert world.native_observations[-1]["tool"] == "evaluate_insight_card"
    assert world.native_observations[-1]["succeeded"] is False
    next_period = await bridge.call("finish_period", {})
    assert next_period["period_end_exclusive"] == "2026-08-10"
    assert world.feedback_reads == []
    assert world.evaluations[0] == ["northstar-2026-08-03"]
    assert (workspace / "tool-responses").is_dir()


async def test_owner_authorizes_native_approval_only_for_exact_displayed_card_without_approving_it(tmp_path):
    source_ref = "superset_sql|query:dispatch-weekly-delivery:abc123"
    card = {
        "id": "card-dispatch-v2", "title": "Dispatch weekly delivery damage review", "version": 2,
        "sources": [{"key": "dispatch", "adapter": "superset_sql", "resource": "query:dispatch-weekly-delivery:abc123"}],
        "onboarding_review": {"source_selection_fingerprint": "review-fingerprint-v2"},
    }
    calls = []

    class CardReader:
        async def call(self, name, arguments):
            calls.append((name, arguments))
            return {"result": {"card": card}}

    world = journey.NorthstarWorld(_source(), tmp_path, "signalweave", native=Mock())
    consent = await world.call("confirm_workflow", {
        "summary": "Present the saved card for review.", "card_id": card["id"],
    }, CardReader())
    assert consent["saved_card"] == card
    assert "explicitly authorize you to call the real native approve_insight_card" in consent["consent"]
    assert "version 2" in consent["consent"] and source_ref in consent["consent"]
    assert consent["approval_authorization"] == {
        "action": "call_native_approve_insight_card",
        "card_id": card["id"], "title": card["title"], "version": 2,
        "source_refs": [source_ref],
        "source_scope": card["sources"],
        "source_selection_fingerprint": "review-fingerprint-v2",
    }
    assert "does not itself change approval status" in consent["consent"]
    assert world.approved_card_id is None
    assert [name for name, _ in calls] == ["get_insight_card"]
    answer = await world.call("ask_dispatch_owner", {"question": "What should the weekly policy be?"})
    assert answer["answer"] == journey.OWNER_POLICY and answer["consent"] is False
    assert world.approved_card_id is None


async def test_owner_without_displayed_card_only_returns_business_policy_not_card_authority(tmp_path):
    world = journey.NorthstarWorld(_source(), tmp_path, "signalweave", native=Mock())
    procedure = await world.call("confirm_workflow", {"summary": "Weekly retrospective report."})
    assert "procedure-only consent" in procedure["consent"]
    assert "approval_authorization" not in procedure
    answer = await world.call("ask_dispatch_owner", {
        "question": "Do you explicitly approve a saved policy and source scope? Please answer yes or no."
    })
    assert answer["answer"] == journey.OWNER_POLICY
    assert answer["consent"] is False
    assert "authorization" not in answer
    assert world.approved_card_id is None


async def test_local_inbox_keeps_source_ids_as_locators_and_hashes_actual_workspace_copies(tmp_path):
    workspace = _workspace(tmp_path)
    evidence = workspace / "evidence.csv"
    evidence.write_text("period,shipments,damaged\n2026-07-27/2026-08-03,511,5\n")
    expected = hashlib.sha256(evidence.read_bytes()).hexdigest()
    world = journey.NorthstarWorld(_source(), tmp_path, "baseline")
    await world.call("ask_dispatch_owner", {"question": "What should repeat?"})
    assert not any(str(value) in journey.OWNER_POLICY for value in (511, 5, 0.98))
    await world.call("confirm_workflow", {"summary": "Weekly retrospective review"})
    sent = await world.call("send_message", {
        "to": "dispatch", "body": "A qualified weekly update.",
        "source_refs": ["superset|table:silver.fct_delivery"],
        "workspace_files": ["evidence.csv"],
    })
    assert sent["source_refs_retained_as_locators"] == ["superset|table:silver.fct_delivery"]
    attachment = sent["attachments"][0]
    assert attachment["sha256"] == expected
    assert hashlib.sha256(Path(attachment["recipient_path"]).read_bytes()).hexdigest() == expected
    assert world.messages[0]["source_refs"] == ["superset|table:silver.fct_delivery"]
    next_period = await world.call("finish_period", {})
    assert next_period["period_end_exclusive"] == "2026-08-10"
    feedback = await world.call("read_inbox", {})
    assert feedback["replies"] and "not evidence" not in feedback["replies"][0]["body"]
    repeated = await world.call("read_inbox", {})
    assert repeated["replies"] == [] and len(world.feedback_reads) == 2
    assert world.day == 1


async def test_period_finish_advances_after_digest_without_forcing_feedback_or_native_evaluation(tmp_path):
    _workspace(tmp_path, "signalweave")
    native = Mock()
    native.restart = AsyncMock()
    native.select_period = Mock()
    world = journey.NorthstarWorld(_source(), tmp_path, "signalweave", native)
    world.owner_confirmations.append({"card_id": "retained-card"})
    world.confirmed_card_id = world.approved_card_id = "retained-card"
    world.evaluations[0].append("northstar-2026-08-03")
    world.messages.append({"id": "dispatch-1", "period_end_exclusive": journey.PERIOD_ENDS[0], "to": "dispatch"})
    result = await world.call("finish_period", {})
    assert result["period_end_exclusive"] == "2026-08-10"
    native.select_period.assert_called_once_with("2026-08-10")
    native.restart.assert_awaited_once()
    assert world.day == 1 and world.approved_card_id == "retained-card"
    assert world.feedback_reads == [] and world.evaluations[1] == []


async def test_native_owner_rpc_restarts_with_each_trusted_explicit_clock(monkeypatch, tmp_path):
    params_seen, context_tasks, operation_tasks = [], [], []

    @asynccontextmanager
    async def fake_stdio(params):
        params_seen.append(params)
        context_tasks.append(asyncio.current_task())
        yield object(), object()

    class FakeSessionContext:
        async def __aenter__(self):
            context_tasks.append(asyncio.current_task())
            return self

        async def __aexit__(self, *_):
            context_tasks.append(asyncio.current_task())

        async def list_tools(self):
            operation_tasks.append(asyncio.current_task())
            return SimpleNamespace(tools=[
                types.Tool(name=name, inputSchema={"type": "object"})
                for name in AGENT_PROFILE_TOOLS
            ])

        async def call_tool(self, name, args):
            operation_tasks.append(asyncio.current_task())
            return SimpleNamespace(content=[], structuredContent={"cards": []}, isError=False)

    monkeypatch.setattr(journey, "stdio_client", fake_stdio)
    monkeypatch.setattr(journey, "ClientSession", lambda *_: FakeSessionContext())
    monkeypatch.setattr(journey, "_initialize_mcp_session", AsyncMock(return_value=SimpleNamespace(instructions="")))

    connection = journey.ClockedNativeConnection("/private/signalweave", tmp_path, Mock(), "http://127.0.0.1:9", journey.PERIOD_ENDS[0])
    await asyncio.create_task(connection.restart())
    owner_task = connection._worker
    assert owner_task is not None
    assert await asyncio.create_task(connection.list_tools())
    connection.select_period(journey.PERIOD_ENDS[1])
    await asyncio.create_task(connection.restart())
    await asyncio.create_task(connection.call_tool("list_insight_cards", {}))
    await connection.close()

    assert [params.env["SIGNALWEAVE_QUERY_AS_OF_DATE"] for params in params_seen] == [
        "2026-08-03", "2026-08-10",
    ]
    assert all(params.env["TYPESAFE_BASE_URL"] == "http://127.0.0.1:9" for params in params_seen)
    assert all(params.env["PINE_SOURCE_PYTHONPATH"] == str(journey.ROOT) for params in params_seen)
    assert set(context_tasks + operation_tasks) == {owner_task}


@pytest.mark.parametrize("returncode", [0, 23])
async def test_operator_import_returns_bounded_cli_output_without_rewriting_actor_file(tmp_path, monkeypatch, returncode):
    _workspace(tmp_path, "signalweave")
    home = tmp_path / "private-home"
    home.mkdir(mode=0o700)
    binary = tmp_path / "native-bin" / "signalweave"
    binary.parent.mkdir()
    binary.write_text("test executable placeholder")
    native = Mock(binary=binary, home=home, proxy="http://127.0.0.1:9")
    native.restart = AsyncMock()
    native.select_period = Mock()
    world = journey.NorthstarWorld(_source(), tmp_path, "signalweave", native)
    world.database_id = 1
    query_path = tmp_path / "signalweave/workspace/query-catalog.json"
    query_path.write_text(json.dumps({
        "version": 2,
        "queries": [{
            "key": "weekly-damage", "title": "Weekly damage", "definition": "Retrospective promised-date cohort",
            "read_only": True, "database_id": 1, "dialect": "postgres",
            "clock": {"kind": "explicit"},
            "sql": "SELECT DATE '{{cutoff_date}}' AS period_end",
        }],
    }))
    original = query_path.read_bytes()
    seen = {}
    stdout = "Native import response\n" + "x" * 2400
    stderr = "Native import diagnostic\n" + "y" * 2400

    class FakeProcess:
        def __init__(self, result_code):
            self.returncode = result_code

        async def communicate(self):
            return stdout.encode(), stderr.encode()

    async def fake_exec(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return FakeProcess(returncode)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    result = await world.call(journey.IMPORT_TOOL, {"proposal_path": "query-catalog.json"})

    assert result["imported"] is (returncode == 0) and result["operator_action_count"] == 1
    assert result["returncode"] == returncode
    assert result["stdout"] == stdout[:2000] and len(result["stdout"]) == 2000
    assert result["stderr"] == stderr[:2000] and len(result["stderr"]) == 2000
    assert result["reconnected"] is (returncode == 0)
    assert query_path.read_bytes() == original
    assert journey._sha(query_path) == result["proposal_sha256"]
    assert seen["args"][:7] == (str(binary), "queries", "import", "--source", "superset", "--yes", "--file")
    assert seen["kwargs"]["env"]["SIGNALWEAVE_QUERY_AS_OF_DATE"] == "2026-08-03"
    assert seen["kwargs"]["env"]["PINE_SOURCE_PYTHONPATH"] == str(journey.ROOT)
    assert "--home" in seen["args"] and str(home) in seen["args"]
    if returncode == 0:
        native.restart.assert_awaited_once()
    else:
        native.restart.assert_not_awaited()


async def test_prepare_freezes_canonical_read_grants_and_preflights_each_arm(tmp_path, monkeypatch):
    root = tmp_path / "study"
    codex = tmp_path / "codex"
    key_file = tmp_path / "key"
    key_file.write_text("private-key")
    source_executable = tmp_path / "superset-mcp"
    source_checkout = tmp_path / "source-checkout"
    binary = tmp_path / "signalweave"
    sdk_root = tmp_path / "public-python-sdk"
    sdk_root.mkdir()
    grants_seen = []
    preflights = []
    identity_resolvers = []

    def actor_paths(workspace):
        paths = (sdk_root.resolve(), (Path(workspace) / "tool-responses").resolve())
        grants_seen.append((Path(workspace), paths))
        return paths

    async def bootstrap_setup(prepared_root, *_args, codex_identity_resolver=None):
        identity_resolvers.append(codex_identity_resolver)
        prepared_root.mkdir(mode=0o700)
        (prepared_root / "human-home/.signalweave").mkdir(parents=True)
        arms = {}
        for arm in journey.ORDER:
            workspace = prepared_root / arm / "workspace"
            workspace.mkdir(parents=True)
            if arm == "signalweave":
                (workspace / ".agents").mkdir()
            arms[arm] = {"sandbox": {"legacy_empty_profile": True}, "initial_inventory": {}}
        study = {
            "protocol": journey.setup.PROTOCOL,
            "method": {}, "limits": {}, "binary": {"candidate": "verified"},
            "installed_binary": str(binary), "source_executable": str(source_executable),
            "source_executable_sha256": "source-sha", "source_environment": {"python": "pinned"},
            "source_revision": "source-revision", "source_checkout": str(source_checkout),
            "url": "http://127.0.0.1:18089", "codex": {"path": str(codex)},
            "registry_sha256": "registry-sha", "warehouse": {"fingerprint": "warehouse"},
            "wizard": {"returncode": 0}, "registration_verified": True,
            "analytical_sql_preflight": {"passed": True}, "key_file": str(key_file),
            "arms": arms,
        }
        journey.setup.shared.write(prepared_root / "study.json", study)

    source = _source()
    source.call_tool.return_value = ([], {"result": [{
        "id": 7, "database_name": "Northstar Lakehouse", "allow_dml": False,
        "allow_ctas": False, "allow_cvas": False,
    }]})

    @asynccontextmanager
    async def fake_servers(*_args):
        yield source, None

    def sandbox_preflight(*_args, readonly_paths=()):
        paths = tuple(map(str, readonly_paths))
        preflights.append(paths)
        return {"workspace_read_write": True, "private_read_write_denied": True,
                "private_read_paths_denied": 1, "command_network_denied": True,
                "profile_tag": len(preflights)}

    monkeypatch.setattr(journey, "_require_source_docker_context", lambda: None)
    monkeypatch.setattr(journey.setup, "prepare", bootstrap_setup)
    monkeypatch.setattr(journey.setup, "servers", fake_servers)
    monkeypatch.setattr(journey.setup, "sandbox_preflight", sandbox_preflight)
    monkeypatch.setattr(journey.setup, "workspace_inventory", lambda _workspace: {})
    monkeypatch.setattr(journey, "public_paths", actor_paths)
    monkeypatch.setattr(journey, "_native_query_schema", lambda *_args: {
        "schema_sha256": "schema-sha", "reference_sha256": "reference-sha",
    })

    result = await journey.prepare(
        root, binary, codex, key_file, source_executable, source_checkout,
    )

    frozen = journey.setup.shared.read(root / "study.json")
    assert result["prepared"] and result["provider_requests"] == 0
    assert identity_resolvers == [journey.pine.first.pinned_codex]
    assert frozen["source_tool_server_count"] == 137
    assert "arms" not in frozen["bootstrap"]
    assert [workspace for workspace, _ in grants_seen] == [
        root / "baseline/workspace", root / "signalweave/workspace",
    ]
    assert len(preflights) == len(journey.ORDER) == 2
    for index, arm in enumerate(journey.ORDER):
        expected = [*map(str, grants_seen[index][1])]
        if arm == "signalweave":
            expected.append(str((root / arm / "workspace/.agents").resolve()))
        assert preflights[index] == tuple(expected)
        assert frozen["arms"][arm]["read_paths"] == expected
        assert frozen["arms"][arm]["sandbox"]["profile_tag"] == index + 1
        assert "legacy_empty_profile" not in frozen["arms"][arm]["sandbox"]
