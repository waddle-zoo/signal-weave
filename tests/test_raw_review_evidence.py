"""Contracts for indexed, lossless raw workflow review evidence."""

import copy
import hashlib
import inspect
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError

from evaluations.raw_review_evidence import IndexedWorkflowReviewSession


def captures(row_count=250):
    rows = [
        {
            "row_id": f"row-{index}",
            "value": index,
            "reference": f"chart://weekly/{index}",
            "source_text": f"source row {index}: " + ("x" * 450),
        }
        for index in range(row_count)
    ]
    full_card = {"id": "card-7", "version": 3, "policy": {"quiet": True}}
    return [
        {
            "tool": "read_chart_rows",
            "arguments": {"ref": "sales.weekly", "id": "42"},
            "result": {"rows": rows, "reference": "chart://sales/weekly"},
        },
        {"tool": "saved_native_card", "arguments": {"card_id": "card-7"}, "result": full_card},
    ]


def make_session(source_excerpts=None, byte_limit=180_000, saved_card=None):
    return IndexedWorkflowReviewSession(
        {"metric": "net sales"},
        "Explain the weekly change.",
        {"notes": "quiet means no alert"},
        {"id": "card-7", "policy": {"quiet": True}} if saved_card is None else saved_card,
        captures() if source_excerpts is None else source_excerpts,
        byte_limit=byte_limit,
    )


def review():
    return {"ready_for_shadow": True, "issues": [], "owner_message": "Ready for one shadow report."}


def index_for(session):
    return session.review_materials["source_excerpts"]["source_evidence_index"]


async def test_constructor_index_and_tools_keep_large_capture_out_of_inline_materials():
    assert list(inspect.signature(IndexedWorkflowReviewSession).parameters) == [
        "owner_declarations",
        "original_brief",
        "saved_arm_notes",
        "saved_card",
        "source_excerpts",
        "byte_limit",
    ]
    assert (
        inspect.signature(IndexedWorkflowReviewSession).parameters["byte_limit"].default == 180_000
    )
    assert (
        inspect.signature(IndexedWorkflowReviewSession).parameters["byte_limit"].kind
        is inspect.Parameter.KEYWORD_ONLY
    )
    source = captures()
    original = copy.deepcopy(source)
    session = make_session(source)
    source[0]["result"]["rows"][0]["value"] = -1

    materials = session.review_materials
    serialized_materials = json.dumps(materials)
    assert len(original[0]["result"]["rows"]) == 250
    assert "source row 0:" not in serialized_materials
    assert "private_label" not in serialized_materials
    assert "source_evidence_index" in materials["source_excerpts"]
    entries = index_for(session)
    assert entries[0]["capture_index"] == 0
    assert entries[0]["tool"] == "read_chart_rows"
    assert entries[0]["arguments"] == {"ref": "sales.weekly", "id": "42"}
    raw = json.dumps(original[0]["result"], ensure_ascii=False, separators=(",", ":")).encode()
    assert entries[0]["serialized_result_bytes"] == len(raw)
    assert entries[0]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert entries[0]["result_top_level"] == {
        "type": "object",
        "keys": [
            {"key": "rows", "shape": {"type": "array", "item_count": 250}},
            {"key": "reference", "shape": {"type": "string"}},
        ],
    }
    assert entries[1]["tool"] == "saved_native_card"
    materials["source_excerpts"]["source_evidence_index"].clear()
    assert len(index_for(session)) == 2
    recovered = await session.call(
        "read_review_evidence",
        {
            "capture_index": 0,
            "result_path": ["rows", "0"],
        },
    )
    assert {item["key"]: item["value"] for item in recovered["result_page"]["items"]}["value"] == 0
    tools = await session.specs()
    assert [tool["name"] for tool in tools] == [
        "read_review_evidence",
        "calculate",
        "record_review",
    ]
    for tool in tools:
        Draft202012Validator.check_schema(tool["parameters"])
    description = tools[0]["description"]
    assert "['capture']" in description
    assert "untrusted" in description and "never" in description and "execute" in description
    assert "verification artifact" in description


async def test_paging_returns_exact_tail_paths_and_isolated_references():
    source = captures()
    session = make_session(source)
    page = await session.call(
        "read_review_evidence",
        {
            "capture_index": 0,
            "result_path": ["rows"],
            "offset": 225,
            "limit": 25,
        },
    )
    raw_page = page["result_page"]
    assert raw_page["path"] == ["capture", "rows"]
    assert raw_page["items"] == source[0]["result"]["rows"][225:]
    assert raw_page["items"][-1]["reference"] == "chart://weekly/249"
    assert raw_page["has_more"] is False

    nested = await session.call(
        "read_review_evidence",
        {
            "capture_index": 0,
            "result_path": ["rows", "249"],
        },
    )
    assert nested["result_page"]["path"] == ["capture", "rows", "249"]
    assert {item["key"]: item["value"] for item in nested["result_page"]["items"]} == source[0][
        "result"
    ]["rows"][249]
    nested["result_page"]["items"][0]["value"] = "mutated return value"
    reread = await session.call(
        "read_review_evidence",
        {
            "capture_index": 0,
            "result_path": ["rows", "249"],
        },
    )
    assert {item["key"]: item["value"] for item in reread["result_page"]["items"]} == source[0][
        "result"
    ]["rows"][249]

    card = await session.call("read_review_evidence", {"capture_index": 1})
    assert card["result_page"]["path"] == ["capture"]
    assert {item["key"]: item["value"] for item in card["result_page"]["items"]} == source[1][
        "result"
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        {"capture_index": True},
        {"capture_index": -1},
        {"capture_index": 9},
        {"capture_index": 0, "offset": True},
        {"capture_index": 0, "offset": -1},
        {"capture_index": 0, "limit": True},
        {"capture_index": 0, "limit": 0},
        {"capture_index": 0, "limit": 101},
        {"capture_index": 0, "result_path": "rows"},
        {"capture_index": 0, "result_path": ["rows", 0]},
        {"capture_index": 0, "result_path": ["x"] * 8},
        {"capture_index": 0, "result_path": ["x" * 257]},
        {"capture_index": 0, "extra": True},
        {},
    ],
)
async def test_read_arguments_are_closed_and_strict(arguments):
    session = make_session()
    with pytest.raises((ValidationError, ValueError)):
        await session.call("read_review_evidence", arguments)


async def test_oversized_values_are_explicit_and_never_silently_trimmed():
    session = make_session(
        [
            {
                "tool": "read_chart_rows",
                "arguments": {"ref": "large"},
                "result": {"rows": [{"body": "z" * 100_000}], "scalar": "q" * 100_000},
            }
        ]
    )
    container = await session.call(
        "read_review_evidence",
        {
            "capture_index": 0,
            "result_path": ["rows"],
        },
    )
    assert container["result_page"]["items"] == []
    assert container["result_page"]["oversized_item"]["path"] == ["capture", "rows", "0"]
    assert container["availability"]["status"] == "read_child_path"

    scalar = await session.call(
        "read_review_evidence",
        {
            "capture_index": 0,
            "result_path": ["scalar"],
        },
    )
    assert scalar["result_page"]["items"] == []
    assert scalar["result_page"]["oversized_item"] is not None
    assert scalar["availability"]["status"] == "unavailable_oversized_scalar"
    assert "not truncated" in scalar["availability"]["message"]
    assert "unavailable" in scalar["result_page"]["oversized_item"]["instruction"]
    assert session.evidence_reads == []
    with pytest.raises(ValueError, match="actual source capture"):
        await session.call("record_review", review())


async def test_calculation_is_bounded_and_all_tools_stop_after_submission():
    session = make_session()
    assert await session.call("calculate", {"expression": "12 * (1 + 0.25)"}) == {"value": 15.0}
    with pytest.raises(ValidationError):
        await session.call("calculate", {"expression": "1 + 1", "extra": 3})
    with pytest.raises(ValidationError):
        await session.call("calculate", {"expression": "1" * 1001})
    await session.call(
        "read_review_evidence",
        {
            "capture_index": 0,
            "result_path": ["rows"],
            "limit": 1,
        },
    )
    assert await session.call("record_review", review()) == {
        "recorded": True,
        "ready_for_shadow": True,
    }
    for name, arguments in (
        ("read_review_evidence", {"capture_index": 0}),
        ("calculate", {"expression": "1 + 1"}),
    ):
        with pytest.raises(ValueError, match="already submitted"):
            await session.call(name, arguments)


async def test_ready_gate_allows_source_reads_then_requires_each_saved_card_ref():
    source = captures()
    source.append(
        {
            "tool": "inspect_resource",
            "arguments": {"adapter": "company_mcp", "resource": "quality:1"},
            "result": {"status": "available", "reference": "quality://1"},
        }
    )
    card = {
        "sources": [
            {"key": "sales", "adapter": "superset", "resource": "chart:42"},
            {"key": "quality", "adapter": "company_mcp", "resource": "quality:1"},
        ]
    }
    session = make_session(source, saved_card=card)
    tools = await session.specs()
    record = next(tool for tool in tools if tool["name"] == "record_review")
    assert "nonempty page" in record["description"] and "saved card" in record["description"]
    assert set(record["parameters"]["properties"]) == {
        "ready_for_shadow",
        "issues",
        "owner_message",
    }
    assert set(record["parameters"]["required"]) == {
        "ready_for_shadow",
        "issues",
        "owner_message",
    }
    with pytest.raises(ValueError, match="actual source capture"):
        await session.call("record_review", review())
    assert session.submission is None

    await session.call(
        "read_review_evidence",
        {
            "capture_index": 0,
            "result_path": ["rows"],
            "limit": 1,
        },
    )
    expected = [{"index": 0, "path": ["rows"], "source_ref": "superset|chart:42"}]
    assert session.evidence_reads == expected
    exposed = session.evidence_reads
    exposed[0]["path"].clear()
    exposed.append({"index": 2, "path": [], "source_ref": "forged"})
    assert session.evidence_reads == expected
    with pytest.raises(ValueError, match="1 remain"):
        await session.call("record_review", review())
    assert session.submission is None

    await session.call("read_review_evidence", {"capture_index": 2})
    assert session.evidence_reads[-1] == {
        "index": 2,
        "path": [],
        "source_ref": "company_mcp|quality:1",
    }
    assert await session.call("record_review", review()) == {
        "recorded": True,
        "ready_for_shadow": True,
    }


async def test_rejection_needs_no_reads_and_card_artifact_does_not_count_as_source():
    session = make_session()
    assert await session.call(
        "record_review",
        {
            **review(),
            "ready_for_shadow": False,
        },
    ) == {"recorded": True, "ready_for_shadow": False}
    assert session.evidence_reads == []
    with pytest.raises(ValueError, match="already submitted"):
        await session.call("read_review_evidence", {"capture_index": 0})

    card = {"sources": [{"key": "sales", "adapter": "superset", "resource": "chart:42"}]}
    artifact = make_session(
        [{"tool": "saved_native_card", "arguments": {"card_id": "c1"}, "result": card}],
        saved_card=card,
    )
    await artifact.call("read_review_evidence", {"capture_index": 0})
    assert artifact.evidence_reads == [{"index": 0, "path": [], "source_ref": None}]
    with pytest.raises(ValueError, match="actual source capture"):
        await artifact.call("record_review", review())
    assert artifact.submission is None


async def test_record_schema_is_validated_before_ready_gate():
    session = make_session()
    with pytest.raises(ValidationError):
        await session.call("record_review", {"ready_for_shadow": True})
    with pytest.raises(ValidationError):
        await session.call("record_review", {**review(), "extra": "closed"})
    assert session.submission is None


async def test_out_of_range_empty_and_oversized_pages_do_not_satisfy_gate():
    session = make_session(
        [
            {
                "tool": "profile_saved_chart",
                "arguments": {"id": 42},
                "result": {"rows": []},
            }
        ]
    )
    with pytest.raises(ValueError, match="capture_index"):
        await session.call("read_review_evidence", {"capture_index": 1})
    empty = await session.call(
        "read_review_evidence",
        {
            "capture_index": 0,
            "result_path": ["rows"],
        },
    )
    assert empty["result_page"]["items"] == []
    assert session.evidence_reads == []
    with pytest.raises(ValueError, match="actual source capture"):
        await session.call("record_review", review())


def test_index_byte_limit_fails_instead_of_truncating_and_rejects_bool():
    with pytest.raises(ValueError, match="exceeds byte_limit"):
        make_session(byte_limit=20)
    with pytest.raises(ValueError, match="positive integer"):
        make_session(byte_limit=True)


async def test_optional_missing_context_is_not_an_expert_review_access_prerequisite():
    session = IndexedWorkflowReviewSession({}, "Review the supported primary source", {}, {
        "sources": [{"adapter": "superset", "resource": "chart:42", "required": True},
                    {"adapter": "superset", "resource": "chart:99", "required": False}],
    }, [{"tool": "profile_saved_chart", "arguments": {"id": "42"}, "result": {"count": 12}}])
    await session.call("read_review_evidence", {"capture_index": 0})
    assert await session.call("record_review", review()) == {"recorded": True, "ready_for_shadow": True}
