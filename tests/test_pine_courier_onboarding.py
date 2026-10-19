"""Offline prompt, declaration and frozen-admission checks, not efficacy proof."""

import hashlib
import json
from unittest.mock import AsyncMock, Mock

import pytest
from mcp import types

from evaluations import pine_courier_onboarding as trial


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def completed():
    return {"process_complete": True, "provider_clean": True, "usage": {"known": True, "usage": {"input_tokens": 20, "uncached_input_tokens": 10}}}


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(trial, "method", Mock(return_value={"runner": "frozen"}))
    monkeypatch.setattr(trial, "verify_binary", Mock(return_value={"source": "frozen"}))
    for name in ("native", "codex", "config"):
        (tmp_path/name).write_text("Offline identity, never executable")
    for name in ("sessions", "codex_episode", "pinned_codex"):
        monkeypatch.setattr(trial, name, AsyncMock(side_effect=AssertionError("Unexpected execution")))
    study = {"protocol": trial.PROTOCOL, "limits": dict(trial.LIMITS), "method": trial.method(),
             "binary_path": str(tmp_path/"native"), "binary": {"source": "frozen"},
             "codex": {"path": str(tmp_path/"codex"), "sha256": trial._sha(tmp_path/"codex")},
             "private_files": {str(tmp_path/"config"): trial._sha(tmp_path/"config")}, "arms": {}}
    for arm in trial.ORDER:
        workspace = tmp_path/arm/"workspace"
        workspace.mkdir(parents=True, mode=0o700)
        (tmp_path/arm/"active.sqlite3").write_bytes(b"Offline frozen source; no SQLite generation")
        write(tmp_path/f"{arm}-task.json", trial.task(arm))
        study["arms"][arm] = {"task_sha256": trial._sha(tmp_path/f"{arm}-task.json"),
                              "initial_inventory": trial.workspace_inventory(workspace)}
    study["source_sha256"] = trial._sha(tmp_path/"baseline/active.sqlite3")
    (tmp_path/"source.sqlite3").write_bytes((tmp_path/"baseline/active.sqlite3").read_bytes())
    write(tmp_path/"study.json", study)
    write(tmp_path/"preflight.json", {"passed": True, "study_sha256": trial._sha(tmp_path/"study.json")})
    review = tmp_path/"review.json"
    write(review, {"approved": True, "reviewer": "independent-offline-reviewer",
                   "study_sha256": trial._sha(tmp_path/"study.json"),
                   "preflight_sha256": trial._sha(tmp_path/"preflight.json")})
    return tmp_path, study, review


def test_shared_business_prompt_has_only_current_request_and_clock():
    baseline, treatment = (trial.task(arm) for arm in trial.ORDER)
    assert baseline["prompt"] == treatment["prompt"]
    assert set(baseline["prompt"]) == {"request", "source_cutoff", "assessment_mode"}
    assert baseline["prompt"]["source_cutoff"] == trial.company.CUTOFFS[0]
    assert baseline["instructions"] == trial.COMMON and treatment["instructions"].startswith(trial.COMMON)
    for future in trial.company.CUTOFFS[1:]:
        assert future not in json.dumps((baseline, treatment))
    for hidden in ("pine-courier-history-contract.md", "reference.stdout", "SELECT ", "expected_outcome"):
        assert hidden not in json.dumps((baseline, treatment))


@pytest.mark.parametrize("question", ["What does Dispatch need?", "Approve everything now."])
async def test_owner_notes_preserve_exact_declarations_without_answer_or_approval(question):
    source = Mock(instructions="Original source instructions")
    source.list_tools = AsyncMock(return_value=[types.Tool(name="query_readonly", inputSchema={"type": "object"})])
    source.call_tool = AsyncMock(return_value=([], {"value": None}))
    facade = trial.OwnerSource(source)
    assert {t.name for t in await facade.list_tools()} == {"query_readonly", "read_owner_notes"}
    content, result = await facade.call_tool("read_owner_notes", {"question": question})
    assert content == [] and result["question"] == question and result["answer"] is None and result["known"] is False
    assert "approval" not in result and "approved" not in result
    assert result["reference"]["declarations"] == [
        {"citation": k, "policy_statement": v, "statement_sha256": hashlib.sha256(v.encode()).hexdigest()}
        for k, v in trial.OWNER.items()]
    source.call_tool.assert_not_awaited()


def test_manifest_reads_existing_cache_without_supplied_analysis(tmp_path):
    connection, = trial.manifest(tmp_path/"source.sqlite3")["connections"]
    resource, = connection["resources"]
    assert resource["arguments"]["sql"] == "SELECT * FROM cached_sla_exports"
    assert resource["tool"] == "export_query" and resource["snapshot_pointer"] == "" and set(resource["arguments"]) == {"sql", "resource", "source_key", "title"}
    assert not {"outcome", "expected_outcome", "numeric_conditions"} & resource.keys()


def test_admission_allows_only_one_baseline_then_one_treatment(frozen):
    root, study, review = frozen
    trial.verify(root, study)
    trial.admit(root, study, "baseline", review)
    with pytest.raises(ValueError):
        trial.admit(root, study, "signalweave", review)
    for arm in trial.ORDER:
        (root/f"{arm}.claimed").touch()
        write(root/f"{arm}.json", completed())
        with pytest.raises(ValueError):
            trial.admit(root, study, arm, review)
        if arm == "baseline":
            trial.admit(root, study, "signalweave", review)


@pytest.mark.parametrize("fault", ["approved", "reviewer", "study_sha256", "preflight_sha256", "failed", "cross-study"])
def test_admission_requires_exact_reviewed_study_and_successful_matching_preflight(frozen, fault):
    root, study, review = frozen
    data = trial.shared.read(review)
    if fault in data:
        data[fault] = False if fault == "approved" else "" if fault == "reviewer" else "wrong"
    else:
        write(root/"preflight.json", {"passed": fault != "failed", "study_sha256": "another-study"})
        data["preflight_sha256"] = trial._sha(root/"preflight.json")
    write(review, data)
    with pytest.raises(ValueError):
        trial.admit(root, study, "baseline", review)


@pytest.mark.parametrize("fault", ["unreported", "incomplete", "unknown", "provider", "input", "uncached"])
def test_prior_failure_unknown_usage_and_exact_usage_caps_stop_next_actor(frozen, fault):
    root, study, review = frozen
    (root/"baseline.claimed").touch()
    report = completed()
    if fault == "incomplete":
        report["process_complete"] = False
    if fault == "unknown":
        report["usage"]["known"] = False
    if fault == "provider":
        report["provider_clean"] = False
    if fault == "input":
        report["usage"]["usage"]["input_tokens"] = trial.LIMITS["between_actor_input_stop"]
    if fault == "uncached":
        report["usage"]["usage"]["uncached_input_tokens"] = trial.LIMITS["between_actor_uncached_stop"]
    if fault != "unreported":
        write(root/"baseline.json", report)
    with pytest.raises(ValueError):
        trial.admit(root, study, "signalweave", review)


@pytest.mark.parametrize("target", ["config", "codex", "source.sqlite3", "baseline/active.sqlite3", "signalweave-task.json", "baseline/workspace/notes.md"])
def test_frozen_input_mutations_reject_before_execution(frozen, target):
    root, study, review = frozen
    (root/target).write_text("Unreviewed mutation")
    with pytest.raises(ValueError):
        trial.verify(root, study)
        trial.admit(root, study, "baseline", review)


def test_inventory_failure_saves_accounting_first_and_retains_terminal_report(frozen, monkeypatch):
    root, study, _ = frozen
    usage = completed()["usage"]
    monkeypatch.setattr(trial, "usage_snapshot", Mock(return_value=usage))
    monkeypatch.setattr(trial, "verify", Mock())
    def broken_inventory(_):
        assert trial.shared.read(root/"baseline-accounting.json")["usage"] == usage
        raise ValueError("inventory unavailable")
    monkeypatch.setattr(trial, "workspace_inventory", broken_inventory)
    result = completed() | {"frontier_invocations": 1, "errors": []}
    trial.collect_result(root, "baseline", study, result, trial.Audit(), trial.RequestBudget(0))
    saved = trial.shared.read(root/"baseline.json")
    assert saved["usage"] == usage and not saved["process_complete"] and saved["workspace_files"] is None
    assert saved["source_unchanged"] and saved["frozen_inputs_unchanged"] and "inventory unavailable" in json.dumps(saved["errors"])
    trial.verify.assert_called_once_with(root, study)


async def test_local_pinned_codex_records_alpha_17_2_without_running_a_cli(tmp_path, monkeypatch):
    executable = tmp_path/"codex"
    executable.write_bytes(b"offline executable fixture")
    version = "codex-cli 0.0.0-alpha.17.2"
    process = Mock(returncode=0)
    process.communicate = AsyncMock(return_value=(version.encode()+b"\n", b""))
    create_process = AsyncMock(return_value=process)
    monkeypatch.setattr(trial.asyncio, "create_subprocess_exec", create_process)

    identity = await trial.pinned_codex(str(executable))

    assert identity == {"path": str(executable.resolve()), "version": version,
                        "sha256": trial._sha(executable)}
    create_process.assert_awaited_once_with(str(executable.resolve()), "--version",
        stdout=trial.asyncio.subprocess.PIPE, stderr=trial.asyncio.subprocess.DEVNULL)
    process.communicate.assert_awaited_once()


@pytest.mark.parametrize(("version", "returncode"), [
    ("not a Codex version", 0),
    ("codex-cli 0.0.0-alpha.17.2", 1),
])
async def test_local_pinned_codex_rejects_invalid_version_result_without_running_a_cli(
        tmp_path, monkeypatch, version, returncode):
    executable = tmp_path/"codex"
    executable.write_bytes(b"offline executable fixture")
    process = Mock(returncode=returncode)
    process.communicate = AsyncMock(return_value=(version.encode(), b""))
    create_process = AsyncMock(return_value=process)
    monkeypatch.setattr(trial.asyncio, "create_subprocess_exec", create_process)

    with pytest.raises(ValueError, match="did not return a valid version"):
        await trial.pinned_codex(str(executable))

    create_process.assert_awaited_once()
    process.communicate.assert_awaited_once()


async def test_local_pinned_codex_rejects_hash_change_during_mocked_version_check(tmp_path, monkeypatch):
    executable = tmp_path/"codex"
    executable.write_bytes(b"original offline executable fixture")
    process = Mock(returncode=0)

    async def communicate_after_replacing_executable():
        executable.write_bytes(b"changed offline executable fixture")
        return b"codex-cli 0.0.0-alpha.17.2\n", b""

    process.communicate = AsyncMock(side_effect=communicate_after_replacing_executable)
    create_process = AsyncMock(return_value=process)
    monkeypatch.setattr(trial.asyncio, "create_subprocess_exec", create_process)

    with pytest.raises(ValueError, match="changed during identity verification"):
        await trial.pinned_codex(str(executable))

    create_process.assert_awaited_once()
    process.communicate.assert_awaited_once()
