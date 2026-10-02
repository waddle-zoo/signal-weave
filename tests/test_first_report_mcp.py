"""First report and repeated reports use the same production execution boundary."""

import pytest

from signalweave.mcp_server import create_mcp
from tests.test_local_investigation import make_runtime
from tests.test_onboarding_windows import dispatch


async def test_preview_reports_without_approving_or_delivering(tmp_path):
    runtime, source, judger = make_runtime(tmp_path, approved=False)
    server = create_mcp(runtime)
    preview = await dispatch(server, "preview_investigation_report", {"card_id": "repeat"})
    assert preview["status"] == "preview"
    assert preview["delivery_enabled"] is False
    assert preview["report"]["status"] == "complete"
    assert preview["report_markdown"]
    assert runtime.card_store.get_card("repeat").status.value == "draft"
    assert source.calls == 1 and len(judger.states) == 1
    with pytest.raises(Exception, match="approve"):
        await dispatch(server, "evaluate_insight_card", {"card_id": "repeat"})


async def test_recurring_report_replays_without_new_fetch_or_judgment(tmp_path):
    runtime, source, judger = make_runtime(tmp_path)
    server = create_mcp(runtime)
    args = {"card_id": "repeat", "idempotency_key": "daily:one"}
    first = await dispatch(server, "evaluate_insight_card", args)
    replay = await dispatch(server, "evaluate_insight_card", args)
    assert first["report"] == replay["report"]
    assert first["report_markdown"] == replay["report_markdown"]
    assert replay["replayed"] is True
    assert source.calls == 1 and len(judger.states) == 1
    assert first["receipt"]["delivery_enabled"] is False


async def test_report_is_saved_in_receipt_not_rebuilt_on_replay(tmp_path, monkeypatch):
    runtime, source, _ = make_runtime(tmp_path)
    server = create_mcp(runtime)
    args = {"card_id": "repeat", "idempotency_key": "frozen-report"}
    first = await dispatch(server, "evaluate_insight_card", args)

    def forbidden(*args, **kwargs):
        raise AssertionError("A receipt replay must not rebuild its archived report")

    monkeypatch.setattr("signalweave.mcp_server.build_investigation_report", forbidden)
    replay = await dispatch(server, "evaluate_insight_card", args)
    assert replay["report"] == first["report"]
    assert replay["report_markdown"] == first["report_markdown"]
    stored = runtime.decision_receipts.get_by_idempotency_key("frozen-report")
    assert stored.result["report"] == first["report"]
    assert source.calls == 1


async def test_local_run_writes_private_report_artifacts(tmp_path):
    import json
    from pathlib import Path

    from signalweave.local_run import run_card

    runtime, _, _ = make_runtime(tmp_path)
    response = await run_card("repeat", "report-files", tmp_path / "reports", runtime=runtime)
    report = Path(response["artifacts"]["report"])
    assert json.loads(report.read_text()) == response["report"]
    assert report.stat().st_mode & 0o777 == 0o600
    assert Path(response["artifacts"]["report_markdown"]).read_text() == response["report_markdown"]


async def test_older_receipt_never_invents_a_historical_report(tmp_path, monkeypatch):
    runtime, source, judger = make_runtime(tmp_path)
    server = create_mcp(runtime)
    args = {"card_id": "repeat", "idempotency_key": "before-reports"}
    await dispatch(server, "evaluate_insight_card", args)
    receipt = runtime.decision_receipts.get_by_idempotency_key("before-reports")
    original = {k: v for k, v in receipt.result.items() if k not in {"report", "report_markdown"}}
    runtime.decision_receipts.save(receipt.model_copy(update={"result": original}))

    def forbidden(*args, **kwargs):
        raise AssertionError("Historical report must not be reconstructed")

    monkeypatch.setattr("signalweave.mcp_server.build_investigation_report", forbidden)
    replay = await dispatch(server, "evaluate_insight_card", args)
    assert replay["replayed"] and replay["result"] == original
    assert "report" not in replay and "report_markdown" not in replay
    assert "no archived" in replay["report_unavailable_reason"]
    assert source.calls == 1 and len(judger.states) == 1


async def test_incomplete_comparison_does_not_become_successful_first_report(tmp_path):
    from tests.test_diagnostics import comparison

    runtime, _, _ = make_runtime(tmp_path, comparison(coverage="partial"), approved=False)
    server = create_mcp(runtime)
    result = await dispatch(server, "preview_investigation_report", {"card_id": "repeat"})
    assert result["report"]["status"] == "blocked"
    assert result["result"]["outcome"] == "insufficient_data"


async def test_report_tool_cannot_read_other_tenants_card(tmp_path):
    from signalweave.models import PrincipalContext

    runtime, source, _ = make_runtime(tmp_path, approved=False)
    card = runtime.card_store.get_card("repeat")
    runtime.card_store.save_card(card.model_copy(update={"principal_tenant": "private"}))
    runtime.principal = PrincipalContext(principal_id="reader", tenant_id="different")
    server = create_mcp(runtime)
    with pytest.raises(Exception, match="scope|tenant|access"):
        await dispatch(server, "preview_investigation_report", {"card_id": "repeat"})
    assert source.calls == 0
