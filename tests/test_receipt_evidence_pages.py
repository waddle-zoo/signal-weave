"""Large agent handoffs stay bounded; receipt evidence remains lossless."""

import copy
import json

import pytest

from signalweave.mcp_server import (
    AGENT_HANDOFF_BYTES,
    RECEIPT_PAGE_BYTES,
    _compact_evaluation_response,
    _receipt_result_page,
    create_mcp,
)
from signalweave.models import PrincipalContext
from signalweave.store import InMemoryDecisionReceiptStore
from tests.test_onboarding import make_server, tool


def wide_result():
    return {
        "outcome": "investigate", "source_keys": ["warehouse"],
        "rationale": "Read the relevant evidence before delivery.",
        "evidence": [
            {"source_key": "warehouse", "subject_id": str(i),
             "statement": "source-provided context " * 30, "values": {"value": i}}
            for i in range(400)
        ],
        "observations": [{"current": i, "metric": "events"} for i in range(400)],
        "report": {"status": "partial", "issues": [{"code": "missing_baseline"}]},
    }


def test_large_compact_handoff_discloses_omitted_evidence_and_keeps_decision():
    result = wide_result()
    before = copy.deepcopy(result)
    compact = _compact_evaluation_response({
        "result": result, "receipt": {"receipt_id": "r1", "delivery_enabled": False},
    })
    assert len(json.dumps(compact).encode()) < AGENT_HANDOFF_BYTES
    assert compact["result"]["outcome"] == "investigate"
    assert "evidence" not in compact["result"]
    assert compact["evidence_access"]["complete"] is False
    assert compact["evidence_access"]["receipt_id"] == "r1"
    assert {tuple(s["path"]): s["count"] for s in compact["evidence_access"]["available_sections"]}[("evidence",)] == 400
    assert result == before


def test_all_pages_recover_exact_evidence_including_tail_not_a_summary():
    result = wide_result()
    items, offset = [], 0
    while True:
        page = _receipt_result_page(result, ["evidence"], offset, 100)
        assert len(json.dumps(page).encode()) < RECEIPT_PAGE_BYTES
        assert page["items"]
        items.extend(page["items"])
        if not page["has_more"]:
            break
        assert page["coverage"] == "partial_section"
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert items == result["evidence"]
    assert items[-1]["values"]["value"] == 399


def test_nested_object_pages_and_indexes_keep_provenance_fields():
    result = wide_result()
    page = _receipt_result_page(result, ["report"], 0, 25)
    assert {v["key"]: v["value"] for v in page["items"]} == result["report"]
    item = _receipt_result_page(result, ["evidence", "399", "values"], 0, 25)
    assert item["items"] == [{"key": "value", "value": 399}]


def test_oversized_item_is_not_silently_truncated_or_skipped():
    result = {"evidence": [{"statement": "x" * 100_000, "values": {"value": 42}}]}
    page = _receipt_result_page(result, ["evidence"], 0, 25)
    assert page["items"] == [] and page["has_more"]
    assert page["next_offset"] == 0
    assert page["oversized_item"]["path"] == ["evidence", "0"]
    scalar = _receipt_result_page(result, ["evidence", "0", "statement"], 0, 25)
    assert scalar["items"] == [] and scalar["oversized_item"]
    assert result["evidence"][0]["statement"] == "x" * 100_000
    assert page["section_complete"] is False


def test_large_section_directory_is_bounded_and_explicitly_incomplete():
    result = {"outcome": "ignore", **{("field-" + str(i) + "界" * 50): [] for i in range(2000)}}
    compact = _compact_evaluation_response({"result": result, "receipt": {"receipt_id": "r1"}})
    assert len(json.dumps(compact).encode()) < AGENT_HANDOFF_BYTES
    assert compact["evidence_access"]["section_directory_total"] == 2001
    assert compact["evidence_access"]["section_directory_complete"] is False
    assert compact["result"]["outcome"] == "ignore"


@pytest.mark.parametrize("path,offset,limit", [([], 0, 25), (["absent"], 0, 25),
    (["evidence", "-1"], 0, 25), (["evidence"], -1, 25),
    (["evidence"], 0, 0), (["evidence"], 0, 101)])
def test_invalid_page_requests_fail(path, offset, limit):
    with pytest.raises(ValueError):
        _receipt_result_page(wide_result(), path, offset, limit)


@pytest.mark.parametrize("sqlite", [False, True])
async def test_mcp_pages_read_durable_receipt_without_new_sources_or_models(tmp_path, monkeypatch, sqlite):
    server = make_server(tmp_path, sqlite=sqlite)
    runtime = server._test_runtime
    if runtime.decision_receipts is None:
        runtime.decision_receipts = InMemoryDecisionReceiptStore()
        server = create_mcp(runtime, profile="full")
    draft = await tool(server, "draft_insight_card")(
        title="Daily evidence", what_to_watch="Checkout conversion", why_watch="Growth review",
        questions=["What changed?"], decision_guidance="Report only; investigate missing evidence. No external delivery.",
        sources=[{"key": "growth", "adapter": "superset", "resource": "dashboard:7", "label": "Growth"}],
    )
    await tool(server, "approve_insight_card")(draft["card"]["id"])
    evaluated = await tool(server, "evaluate_insight_card")(
        draft["card"]["id"], idempotency_key="pages", response_mode="full",
    )
    receipt = runtime.decision_receipts.get_by_idempotency_key("pages")
    runtime.decision_receipts.save(receipt.model_copy(update={"result": wide_result()}))
    async def forbidden(*args, **kwargs):
        raise AssertionError("Receipt paging must not reevaluate sources or models")
    monkeypatch.setattr(runtime.engine, "evaluate", forbidden)
    _, page = await server.call_tool("get_decision_receipt", {
        "receipt_id": evaluated["receipt"]["receipt_id"], "result_path": ["evidence"], "offset": 390, "limit": 10,
    })
    assert page["result_page"]["items"][-1]["values"]["value"] == 399
    assert "result" not in page["receipt"]
    assert "result" not in page
    full = await tool(server, "get_decision_receipt")(idempotency_key="pages")
    assert full["result"] == wide_result()
    card = runtime.card_store.get_card(draft["card"]["id"])
    runtime.card_store.save_card(card.model_copy(update={"principal_tenant": "owner-a"}))
    runtime.principal = PrincipalContext(tenant_id="owner-b", principal_id="other-reader")
    unauthorized = create_mcp(runtime, profile="full")
    with pytest.raises(ValueError):
        await tool(unauthorized, "get_decision_receipt")(
            receipt_id=receipt.receipt_id, result_path=["evidence"],
        )
