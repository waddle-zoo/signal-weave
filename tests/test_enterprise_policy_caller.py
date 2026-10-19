import asyncio
import json

import pytest
import tomllib

from evaluations import enterprise_policy_caller as caller
from evaluations.codex_workspace import PROFILE


def private_workspace(path):
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


class FakeFacade:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        result = self.results.pop(0)
        return [], result


class FinishedProcess:
    pid = 32101

    async def wait(self):
        return 0


class HangingProcess:
    pid = 32102

    def __init__(self):
        self.stopped = asyncio.Event()

    async def wait(self):
        await self.stopped.wait()
        return -9


def install_fake_sandbox(monkeypatch, outputs, commands):
    pending = list(outputs)

    async def create_subprocess_exec(*command, **kwargs):
        commands.append((command, kwargs))
        assert command[0:2] == ("/opt/codex", "sandbox")
        separator = command.index("--")
        helper_argv = command[separator + 1 :]
        assert helper_argv[0] == "/usr/bin/python3"
        assert "--input" in helper_argv and "--output" in helper_argv
        output_path = helper_argv[helper_argv.index("--output") + 1]
        with open(output_path, "wb") as stream:
            stream.write(pending.pop(0))
        return FinishedProcess()

    monkeypatch.setattr(caller.asyncio, "create_subprocess_exec", create_subprocess_exec)


@pytest.mark.asyncio
async def test_baseline_queries_actual_source_then_runs_retained_helper_in_os_sandbox(
    tmp_path, monkeypatch
):
    workspace = private_workspace(tmp_path / "workspace")
    helper = workspace / "weekly_helper.py"
    helper.write_text("# authored by the study agent\n", encoding="utf-8")
    public_dependency = tmp_path / "public-dependency"
    public_dependency.mkdir()
    private_source = tmp_path / "company.sqlite"
    private_source.write_bytes(b"private company source")
    source_result = {
        "rows": [{"week": "2026-10-12", "tickets": 17}],
        "source_refs": ["harbor://snapshot/2026-10-19/tickets"],
        "source_bytes": 92,
    }
    source = FakeFacade([source_result])
    commands = []
    monkeypatch.setenv("TYPESAFE_API_KEY", "must-not-cross-process-boundary")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-cross-process-boundary")
    decision_bytes = json.dumps(
        {
            "outcome": "investigate",
            "source_refs": ["harbor://snapshot/2026-10-19/tickets"],
            "result_refs": ["weekly-review.md#summary"],
            "summary": "One observed week needs review.",
        },
        separators=(",", ":"),
    ).encode()
    install_fake_sandbox(monkeypatch, [decision_bytes], commands)

    result = await caller.check_once(
        "B",
        [
            caller.Monitor(
                "weekly-support",
                "2026-10-19T00:00:00Z",
                sql="SELECT week, tickets FROM support_weekly",
                helper_path="weekly_helper.py",
            )
        ],
        workspace=workspace,
        source=source,
        run_id="frozen-study-run",
        codex_executable="/opt/codex",
        python_executable="/usr/bin/python3",
        public_dependency_paths=[public_dependency],
    )

    row = result["ledger"][0]
    assert result["known_errors"] == [] and result["business_grade"] is None
    assert row["status"] == "completed" and row["outcome"] == "investigate"
    assert source.calls == [("query_readonly", {"sql": "SELECT week, tickets FROM support_weekly"})]
    actual_input = json.loads((workspace / row["source_ref"]).read_text())
    assert actual_input == {
        "monitor_id": "weekly-support",
        "cutoff": "2026-10-19T00:00:00Z",
        "sql": "SELECT week, tickets FROM support_weekly",
        "source_result": source_result,
    }
    assert row["source_result_bytes"] == len(
        json.dumps(
            source_result,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    assert row["result_bytes"] == len(decision_bytes)
    assert (workspace / row["result_ref"]).read_bytes() == decision_bytes

    command, kwargs = commands[0]
    assert kwargs["stdout"] == asyncio.subprocess.DEVNULL
    assert kwargs["stderr"] == asyncio.subprocess.DEVNULL
    assert kwargs["cwd"] == str(workspace.resolve())
    assert set(kwargs["env"]) == {"HOME", "TMPDIR", "PATH", "LANG", "LC_ALL"}
    assert kwargs["env"]["HOME"] == str(workspace / result["run_directory"] / "sandbox-home")
    assert kwargs["env"]["TMPDIR"] == str(workspace / result["run_directory"] / "sandbox-tmp")
    assert "TYPESAFE_API_KEY" not in kwargs["env"] and "OPENAI_API_KEY" not in kwargs["env"]
    assert (workspace / kwargs["env"]["HOME"]).is_relative_to(workspace)
    assert command[command.index("--") + 1 :] == (
        "/usr/bin/python3",
        str(helper),
        "--input",
        str(workspace / result["run_directory"] / "000-actual.json"),
        "--output",
        str(workspace / result["run_directory"] / "000-decision.json"),
    )
    settings = [command[i + 1] for i, arg in enumerate(command) if arg == "-c"]
    merged = tomllib.loads("\n".join(settings))
    profile = merged["permissions"][PROFILE]
    assert merged["default_permissions"] == PROFILE
    assert profile["network"] == {"enabled": False}
    assert profile["filesystem"][str(workspace.resolve())] == "write"
    assert profile["filesystem"][str(public_dependency.resolve())] == "read"
    assert str(private_source) not in str(profile["filesystem"])
    assert "sh" not in command and "-c" not in command[command.index("--") + 1 :]


@pytest.mark.asyncio
async def test_treatment_calls_each_native_card_with_distinct_run_key_and_retains_full_results(
    tmp_path,
):
    workspace = private_workspace(tmp_path / "workspace")
    native = FakeFacade(
        [
            {
                "result": {"outcome": "ignore", "evidence": [{"source_ref": "harbor://a"}]},
                "receipt": {"receipt_id": "receipt-a"},
            },
            {
                "result": {"outcome": "notify", "evidence": [{"source_ref": "harbor://b"}]},
                "receipt": {"receipt_id": "receipt-b"},
            },
        ]
    )

    result = await caller.check_once(
        "T",
        [
            caller.Monitor("support", "2026-10-19", card_id="approved-card-a"),
            caller.Monitor("priority", "2026-10-19", card_id="approved-card-b"),
        ],
        workspace=workspace,
        native=native,
        run_id="same-observation",
    )

    assert [row["sequence"] for row in result["ledger"]] == [0, 1]
    assert [call[0] for call in native.calls] == ["evaluate_insight_card", "evaluate_insight_card"]
    args = [call[1] for call in native.calls]
    assert [item["card_id"] for item in args] == ["approved-card-a", "approved-card-b"]
    assert len({item["idempotency_key"] for item in args}) == 2
    assert all(item["response_mode"] == "full" for item in args)
    for row in result["ledger"]:
        saved = json.loads((workspace / row["result_ref"]).read_text())
        assert saved == row["native_result"]
        assert row["result_bytes"] == (workspace / row["result_ref"]).stat().st_size
    assert result["known_errors"] == []


@pytest.mark.asyncio
async def test_explicit_same_request_retries_keep_the_key_but_new_runs_do_not(tmp_path):
    workspace = private_workspace(tmp_path / "workspace")
    native = FakeFacade([{"result": {"outcome": "notify"}} for _ in range(3)])
    monitors = [caller.Monitor("support", "same-cutoff", card_id="approved-card")]
    for identity in ("immutable-request", "immutable-request", "new-approved-version-run"):
        await caller.check_once(
            "T", monitors, workspace=workspace, native=native, run_id=identity
        )
    keys = [arguments["idempotency_key"] for _name, arguments in native.calls]
    assert keys[0] == keys[1]
    assert keys[2] != keys[0]


@pytest.mark.asyncio
async def test_unsupported_helper_outcome_is_an_error_and_later_monitors_still_run(
    tmp_path, monkeypatch
):
    workspace = private_workspace(tmp_path / "workspace")
    helper = workspace / "helper.py"
    helper.write_text("# retained agent helper\n", encoding="utf-8")
    source = FakeFacade([{"rows": [1]}, {"rows": [2]}])
    commands = []
    install_fake_sandbox(
        monkeypatch,
        [
            b'{"outcome":"all_clear","source_refs":["source:a"]}',
            b'{"outcome":"ignore","result_refs":["result:b"]}',
        ],
        commands,
    )

    result = await caller.check_once(
        "B",
        [
            caller.Monitor("first", "day-1", sql="SELECT 1", helper_path=helper),
            caller.Monitor("second", "day-1", sql="SELECT 2", helper_path=helper),
        ],
        workspace=workspace,
        source=source,
        codex_executable="/opt/codex",
        python_executable="/usr/bin/python3",
    )

    assert [row["sequence"] for row in result["ledger"]] == [0, 1]
    assert result["ledger"][0]["status"] == "error"
    assert "unsupported helper outcome 'all_clear'" in result["ledger"][0]["error"]
    assert "no all-clear is inferred" in result["ledger"][0]["error"]
    assert result["ledger"][1]["status"] == "completed"
    assert [error["monitor_id"] for error in result["known_errors"]] == ["first"]
    assert len(commands) == 2 and len(source.calls) == 2


@pytest.mark.asyncio
async def test_malformed_helper_output_keeps_actual_input_and_output_refs(tmp_path, monkeypatch):
    workspace = private_workspace(tmp_path / "workspace")
    helper = workspace / "helper.py"
    helper.write_text("# retained agent helper\n", encoding="utf-8")
    source_result = {"rows": [{"id": "actual-row"}], "source_refs": ["company://row/1"]}
    source = FakeFacade([source_result])
    commands = []
    malformed = b'{"outcome":'
    install_fake_sandbox(monkeypatch, [malformed], commands)

    result = await caller.check_once(
        "B",
        [caller.Monitor("bad-json", "day", sql="SELECT id FROM table_x", helper_path=helper)],
        workspace=workspace,
        source=source,
        codex_executable="/opt/codex",
        python_executable="/usr/bin/python3",
    )

    row = result["ledger"][0]
    assert row["status"] == "error"
    assert "valid UTF-8 JSON" in row["error"]
    assert json.loads((workspace / row["source_ref"]).read_text())["source_result"] == source_result
    assert (workspace / row["result_ref"]).read_bytes() == malformed
    assert row["result_bytes"] == len(malformed)


@pytest.mark.asyncio
async def test_helper_output_cap_is_enforced_and_sandbox_timeout_is_reported(tmp_path, monkeypatch):
    workspace = private_workspace(tmp_path / "workspace")
    helper = workspace / "helper.py"
    helper.write_text("# retained agent helper\n", encoding="utf-8")
    source = FakeFacade([{"rows": [1]}, {"rows": [2]}])
    commands = []
    monkeypatch.setattr(caller, "HELPER_OUTPUT_LIMIT_BYTES", 4)
    monkeypatch.setattr(caller.os, "killpg", lambda *_args: None)
    install_fake_sandbox(monkeypatch, [b"12345"], commands)

    too_large = await caller.check_once(
        "B",
        [caller.Monitor("large", "day", sql="SELECT 1", helper_path=helper)],
        workspace=workspace,
        source=source,
        codex_executable="/opt/codex",
        python_executable="/usr/bin/python3",
    )
    assert "output exceeded 4 bytes" in too_large["ledger"][0]["error"]

    monkeypatch.setattr(caller, "HELPER_OUTPUT_LIMIT_BYTES", 256 * 1024)
    monkeypatch.setattr(caller, "HELPER_TIMEOUT_SECONDS", 0.02)
    hanging = HangingProcess()

    async def wait_forever(*_command, **_kwargs):
        return hanging

    def kill_group(_pid, _signal):
        hanging.stopped.set()

    monkeypatch.setattr(caller.asyncio, "create_subprocess_exec", wait_forever)
    monkeypatch.setattr(caller.os, "killpg", kill_group)
    timed_out = await caller.check_once(
        "B",
        [caller.Monitor("slow", "day", sql="SELECT 2", helper_path=helper)],
        workspace=workspace,
        source=source,
        codex_executable="/opt/codex",
        python_executable="/usr/bin/python3",
    )
    assert "exceeded 0.02 seconds" in timed_out["ledger"][0]["error"]


def test_contract_rejects_ambiguous_monitor_configuration(tmp_path):
    workspace = private_workspace(tmp_path / "workspace")
    with pytest.raises(ValueError, match="unique"):
        asyncio.run(
            caller.check_once(
                "T",
                [
                    caller.Monitor("same", "day", card_id="card-a"),
                    caller.Monitor("same", "day", card_id="card-b"),
                ],
                workspace=workspace,
                native=FakeFacade([]),
            )
        )

    with pytest.raises(ValueError, match="B monitors cannot contain"):
        asyncio.run(
            caller.check_once(
                "B",
                [caller.Monitor("bad", "day", card_id="card")],
                workspace=workspace,
                source=FakeFacade([]),
            )
        )
