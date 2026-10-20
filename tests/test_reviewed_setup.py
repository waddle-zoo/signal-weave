"""Offline integrity tests for the report-only reviewed setup fixture."""

from __future__ import annotations

import hashlib
import json

import pytest

from evaluations import reviewed_setup
from signalweave.models import InsightCard, InsightCardStatus, InsightPlan, SourceRef
from signalweave.store import SQLiteInsightCardStore


def fixture_card() -> InsightCard:
    card_id = reviewed_setup.REVIEWED_CARD_ID
    return InsightCard(
        id=card_id,
        title="Pine Courier promised delivery window attainment",
        what_to_watch="Track delivery attainment across all parcels due.",
        why_watch="Dispatch needs a repeatable SLA signal.",
        decision_guidance="Notify on a material decline; missing evidence is insufficient data.",
        sources=[SourceRef(**reviewed_setup.REVIEWED_SOURCE)],
        comparison_windows=["previous_period"],
        principal_id=reviewed_setup.REVIEWED_OWNER,
        principal_tenant="tenant-fixture",
        version=reviewed_setup.REVIEWED_CARD_VERSION,
        compiled_plan=InsightPlan(
            card_id=card_id,
            card_version=reviewed_setup.REVIEWED_CARD_VERSION,
            selected_source_keys=["delivery_service"],
            comparison_windows=["previous_period"],
            capabilities=["baseline_comparison"],
            card_scope="Weekly delivery attainment.",
        ),
        status=InsightCardStatus.APPROVED,
        approved_by=reviewed_setup.REVIEWED_OWNER,
        approved_at="2026-10-15T07:42:36.139783Z",
    )


def fixture_report() -> dict:
    card = fixture_card().model_dump(mode="json")
    return {
        "protocol": "owner-handoff-v4",
        "usage_known": True,
        "provider_usage_known": True,
        "usage": {"responses": 6},
        "agent_invocations_started": 6,
        "provider_attempts": 0,
        "pair_status": "setups_reviewed",
        "episodes": [
            {
                "arm": "signalweave",
                "stage": "first_author",
                "first_card": {"id": reviewed_setup.REVIEWED_CARD_ID, "version": 2},
            },
            {
                "arm": "baseline",
                "stage": "second_author",
                "setup": {"unresolved": [], "card_ids": []},
                "independent_review": {"approved": True},
            },
            {
                "arm": "signalweave",
                "stage": "second_author",
                "setup": {"unresolved": [], "card_ids": [card["id"]]},
                "independent_review": {"approved": True},
                "card": card,
            },
        ],
    }


def write_fixture_inputs(tmp_path, monkeypatch, report=None):
    report_path = tmp_path / "report.json"
    trace_path = tmp_path / "trace.jsonl"
    report_bytes = json.dumps(report if report is not None else fixture_report()).encode()
    trace_bytes = b'{"fixture":"verified trace bytes"}\n'
    report_path.write_bytes(report_bytes)
    trace_path.write_bytes(trace_bytes)
    monkeypatch.setattr(reviewed_setup, "REPORT_SHA256", hashlib.sha256(report_bytes).hexdigest())
    monkeypatch.setattr(reviewed_setup, "TRACE_SHA256", hashlib.sha256(trace_bytes).hexdigest())
    return report_path, trace_path


def test_default_hash_constants_match_retained_v4_artifacts():
    assert reviewed_setup.REPORT_SHA256 == "e4f4cef42971fefb466ba0eb9df0c6d267dce05fc13544dae9fcb397354b5048"
    assert reviewed_setup.TRACE_SHA256 == "e534505dfc0eb8a6072d47de408be3308489ab18619db4a681c810208975a13b"


def test_load_returns_original_report_and_exact_validated_card(tmp_path, monkeypatch):
    report = fixture_report()
    report_path, trace_path = write_fixture_inputs(tmp_path, monkeypatch, report)

    loaded_report, card = reviewed_setup.load_reviewed_setup(report_path, trace_path)

    assert loaded_report == report
    assert card.model_dump(mode="json") == report["episodes"][2]["card"]
    assert card.context_bindings == []


@pytest.mark.parametrize("tampered", ["report", "trace"])
def test_load_rejects_artifact_tampering(tmp_path, monkeypatch, tampered):
    report_path, trace_path = write_fixture_inputs(tmp_path, monkeypatch)
    path = report_path if tampered == "report" else trace_path
    path.write_bytes(path.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="SHA-256"):
        reviewed_setup.load_reviewed_setup(report_path, trace_path)


def test_load_rejects_unknown_usage(tmp_path, monkeypatch):
    report = fixture_report()
    report["usage_known"] = False
    paths = write_fixture_inputs(tmp_path, monkeypatch, report)

    with pytest.raises(ValueError, match="known provider usage"):
        reviewed_setup.load_reviewed_setup(*paths)


def test_load_rejects_failed_independent_review(tmp_path, monkeypatch):
    report = fixture_report()
    report["episodes"][1]["independent_review"]["approved"] = False
    paths = write_fixture_inputs(tmp_path, monkeypatch, report)

    with pytest.raises(ValueError, match="independent review must be approved"):
        reviewed_setup.load_reviewed_setup(*paths)


@pytest.mark.parametrize("wrong_version", [1, 4])
def test_load_rejects_wrong_card_revision(tmp_path, monkeypatch, wrong_version):
    report = fixture_report()
    if wrong_version < 3:
        report["episodes"][0]["first_card"]["version"] = wrong_version
    else:
        report["episodes"][2]["card"]["version"] = wrong_version
        report["episodes"][2]["card"]["compiled_plan"]["card_version"] = wrong_version
    paths = write_fixture_inputs(tmp_path, monkeypatch, report)

    with pytest.raises(ValueError, match="version|revision"):
        reviewed_setup.load_reviewed_setup(*paths)


def test_load_rejects_nonempty_context_bindings(tmp_path, monkeypatch):
    report = fixture_report()
    report["episodes"][2]["card"]["context_bindings"] = [
        {
            "entry_id": "reviewed-note",
            "revision": 2,
            "content_digest": "a" * 64,
            "source_digest": "b" * 64,
            "required_for_action": False,
        }
    ]
    paths = write_fixture_inputs(tmp_path, monkeypatch, report)

    with pytest.raises(ValueError, match="no context bindings"):
        reviewed_setup.load_reviewed_setup(*paths)


def test_restore_is_exact_and_refuses_to_overwrite(tmp_path):
    card = fixture_card()
    database = tmp_path / "fresh" / "state" / "signalweave.db"

    reviewed_setup.restore_reviewed_card(database, card)

    store = SQLiteInsightCardStore(database)
    assert store.get_card(card.id).model_dump(mode="json") == card.model_dump(mode="json")

    existing = card.model_copy(update={"title": "Do not replace"})
    store.save_card(existing)
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        reviewed_setup.restore_reviewed_card(database, card)
    assert store.get_card(card.id).title == "Do not replace"
