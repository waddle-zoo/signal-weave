"""Offline certification compatibility, without changing thresholds or labels."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import typesafe_sdk
from pydantic import ValidationError
from test_evaluation import JevFixture, card, snapshot
from test_onboarding import OnboardingJevDouble, SupersetCatalogDouble, tool

from signalweave.engine import InsightEngine
from signalweave.evaluation import (
    EVIDENCE_ADMISSION_POLICY_VERSION,
    CardEvaluationCase,
    CardEvaluationReport,
    CardWorkflowEvaluator,
    has_current_evidence_admission_policy,
)
from signalweave.mcp_server import create_mcp
from signalweave.models import CertificationRecord, Outcome, PrincipalContext
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import (
    JsonCertificationReportStore,
    JsonInsightCardStore,
    SQLiteCertificationReportStore,
)


@pytest.fixture(autouse=True)
def forbid_live_jev(monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("Policy migration tests must not instantiate a live Jev client")

    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", unexpected_client)


def legacy_report():
    # An old approved report with no admission-policy marker must stay legacy.
    return {
        "card_ids": ["orders-good"], "card_versions": {"orders-good": 1},
        "case_count": 1, "successful_case_count": 1, "error_count": 0,
        "outcome_accuracy": 1.0, "evidence_recall": 1.0,
        "retrieval_precision": 1.0, "retrieval_recall": 1.0,
        "unsafe_action_rate": 0.0, "error_rate": 0.0, "median_latency_ms": 5.0,
        "status": "approved", "thresholds": {}, "evaluation_id": "legacy-audit",
        "input_digest": "old-input-digest", "label_digest": "old-label-digest",
    }


def test_missing_policy_version_loads_as_legacy_without_upgrading_old_approval():
    payload = legacy_report()
    serialized = json.dumps(payload)
    report = CardEvaluationReport.model_validate_json(serialized)

    assert EVIDENCE_ADMISSION_POLICY_VERSION == 2
    assert report.evidence_admission_policy_version == 0
    assert report.status == "approved"
    assert report.evaluation_id == payload["evaluation_id"]
    assert report.input_digest == payload["input_digest"]
    assert report.label_digest == payload["label_digest"]
    assert not has_current_evidence_admission_policy(payload)
    assert not has_current_evidence_admission_policy(report.model_dump(mode="json"))
    assert json.dumps(payload) == serialized
    assert CardEvaluationReport.model_validate_json(
        report.model_dump_json()
    ).evidence_admission_policy_version == 0


@pytest.mark.parametrize("version", [0, 1, 3, -1, True, False, 1.0, "1", None, []])
def test_stored_report_compatibility_fails_closed_for_noncurrent_or_malformed_version(version):
    payload = {**legacy_report(), "evidence_admission_policy_version": version}
    assert not has_current_evidence_admission_policy(payload)


@pytest.mark.parametrize("version", [-1, True, 1.0, "1", None])
def test_report_model_does_not_coerce_invalid_policy_versions(version):
    with pytest.raises(ValidationError):
        CardEvaluationReport.model_validate({
            **legacy_report(), "evidence_admission_policy_version": version,
        })


def test_future_version_remains_readable_but_is_not_current_certification():
    report = CardEvaluationReport.model_validate({
        **legacy_report(),
        "evidence_admission_policy_version": EVIDENCE_ADMISSION_POLICY_VERSION + 1,
    })
    assert report.status == "approved"
    assert not has_current_evidence_admission_policy(report.model_dump(mode="json"))


@pytest.mark.parametrize("path,status", [
    ("success", "approved"), ("wrong-outcome", "shadow"),
    ("preflight", "blocked"), ("runtime-error", "blocked"), ("empty", "blocked"),
])
async def test_evaluator_stamps_policy_version_on_every_report_path(path, status):
    reviewed_card = card("orders-wrong" if path == "wrong-outcome" else "orders-good")
    if path == "preflight":
        reviewed_card.decision_guidance = ""
    case = CardEvaluationCase(
        id="offline-policy-migration", card=reviewed_card, resources=[snapshot()],
        expected_outcome=Outcome.NOTIFY,
        expected_delivery_method_keys=["operations"],
        required_evidence_source_keys=["orders"],
        expected_retrieval_refs=["sql|query:orders"],
    )
    judger = JevFixture()
    if path == "runtime-error":
        judger.judge = AsyncMock(side_effect=RuntimeError("Offline deterministic failure"))
    report = await CardWorkflowEvaluator(InsightEngine(judger)).evaluate(
        [] if path == "empty" else [case]
    )

    assert report.status == status
    assert report.evidence_admission_policy_version == EVIDENCE_ADMISSION_POLICY_VERSION
    assert has_current_evidence_admission_policy(report.model_dump(mode="json"))
    restored = CardEvaluationReport.model_validate_json(report.model_dump_json())
    assert restored == report
    # Compatibility alone must not promote shadow/blocked reports.
    assert restored.status == status
    if path == "success":
        assert report.outcome_accuracy == report.evidence_recall == report.retrieval_recall == 1
        assert report.cases[0].delivery_exact is True
    elif path == "preflight":
        assert report.preflight_blockers
        assert report.cases == []
    elif path == "runtime-error":
        assert report.error_count == 1
        assert "Offline deterministic failure" in report.cases[0].error


@pytest.mark.parametrize("store_type,filename", [
    (JsonCertificationReportStore, "reports.json"),
    (SQLiteCertificationReportStore, "reports.db"),
])
def test_legacy_audit_retained_when_current_policy_report_is_appended(tmp_path, store_type, filename):
    old_body = legacy_report()
    old_record = CertificationRecord(
        report_id="legacy", kind="card_workflow", subject_id="orders-good",
        subject_version="1", status="approved", report=old_body,
    )
    path = tmp_path / filename
    store_type(path).save(old_record)
    new_body = {**old_body, "evidence_admission_policy_version": EVIDENCE_ADMISSION_POLICY_VERSION}
    store_type(path).save(CertificationRecord(
        report_id="current", kind="card_workflow", subject_id="orders-good",
        subject_version="1", status="approved", report=new_body,
    ))

    reopened = store_type(path)
    assert len(reopened.list()) == 2
    assert reopened.get("legacy") == old_record
    assert reopened.get("legacy").report == old_body
    assert not has_current_evidence_admission_policy(reopened.get("legacy").report)
    current = reopened.get("current").report
    assert has_current_evidence_admission_policy(current)
    assert CardEvaluationReport.model_validate(current).evidence_admission_policy_version == EVIDENCE_ADMISSION_POLICY_VERSION


@pytest.fixture(params=[JsonCertificationReportStore, SQLiteCertificationReportStore], ids=["json", "sqlite"])
async def readiness_case(tmp_path, request):
    reports = request.param(tmp_path / "certifications")
    registry = SourceRegistry([SupersetCatalogDouble()], authorized_tenants=["default"])
    runtime = Runtime(
        card_store=JsonInsightCardStore(tmp_path / "cards.json"),
        sources=registry,
        engine=InsightEngine(OnboardingJevDouble(), registry=registry),
        certification_reports=reports,
        principal=PrincipalContext(principal_id="test-principal", tenant_id="default"),
    )
    server = create_mcp(runtime)
    drafted = await tool(server, "draft_insight_card")(
        title="Policy migration readiness", what_to_watch="Checkout conversion",
        why_watch="Determine whether the operating owner needs to respond.",
        questions=["Is the conversion decline material enough for an owner response?"],
        decision_guidance="Notify the owner when conversion declines materially; otherwise ignore.",
        sources=[{"key": "growth", "adapter": "superset", "resource": "dashboard:7", "label": "Growth"}],
        delivery_methods=[{
            "key": "owner", "outcome": "notify", "label": "Operating owner",
            "destination": "slack://owner",
        }],
    )
    card_id = drafted["card"]["id"]
    await tool(server, "approve_insight_card")(card_id)
    for kind, subject in [("bootstrap", "default"), ("retrieval_quality", "retrieval-catalog")]:
        reports.save(CertificationRecord(
            report_id=kind, kind=kind, subject_id=subject, tenant_id="default",
            status="approved", report={"status": "approved"},
        ))
    return server, runtime, reports, card_id


async def mcp_readiness(server):
    response = await server.call_tool("get_enterprise_readiness", {})
    return response[1] if isinstance(response, tuple) else json.loads(
        next(item.text for item in response if getattr(item, "type", None) == "text")
    )


@pytest.mark.parametrize("policy,current", [
    ({}, False),
    ({"evidence_admission_policy_version": 0}, False),
    ({"evidence_admission_policy_version": 1}, False),
    ({"evidence_admission_policy_version": True}, False),
    ({"evidence_admission_policy_version": "1"}, False),
    ({"evidence_admission_policy_version": EVIDENCE_ADMISSION_POLICY_VERSION + 1}, False),
    ({"evidence_admission_policy_version": EVIDENCE_ADMISSION_POLICY_VERSION}, True),
], ids=["missing", "legacy-zero", "legacy-one", "bool", "string", "future", "current"])
async def test_actual_mcp_readiness_requires_current_policy_and_preserves_reports(readiness_case, policy, current):
    server, runtime, reports, card_id = readiness_case
    reports.save(CertificationRecord(
        report_id="workflow", kind="card_workflow", subject_id=card_id,
        tenant_id="default", subject_version="1", status="approved",
        report={**legacy_report(), "card_ids": [card_id], "card_versions": {card_id: 1}, **policy},
    ))
    before_reports = [record.model_dump(mode="json") for record in reports.list()]
    before_card = runtime.card_store.get_card(card_id).model_dump(mode="json")

    result = await mcp_readiness(server)

    assert result["status"] == ("ready_for_shadow" if current else "blocked")
    summary = result["cards"][0]["workflow_certification"]
    assert summary["evidence_admission_policy_current"] is current
    assert summary["stale"] is (not current)
    assert summary["status"] == "approved"  # Historical verdict is not rewritten.
    assert summary["subject_version"] == "1"
    assert {gate["code"] for gate in result["gates"]} == (
        set() if current else {"workflow-admission-policy-stale"}
    )
    if not current:
        assert result["gates"][0]["severity"] == "blocked"
    assert [record.model_dump(mode="json") for record in reports.list()] == before_reports
    assert runtime.card_store.get_card(card_id).model_dump(mode="json") == before_card


@pytest.mark.parametrize("card_version,workflow_status,gate,status", [
    (2, "approved", "workflow-certification-stale", "blocked"),
    (1, "shadow", "workflow-certification-needs-review", "needs_review"),
])
async def test_current_policy_does_not_bypass_existing_readiness_gates(
    readiness_case, card_version, workflow_status, gate, status,
):
    server, runtime, reports, card_id = readiness_case
    current_card = runtime.card_store.get_card(card_id)
    runtime.card_store.save_card(current_card.model_copy(update={
        "version": card_version, "compiled_plan": None,
    }))
    reports.save(CertificationRecord(
        report_id="workflow", kind="card_workflow", subject_id=card_id,
        tenant_id="default", subject_version="1", status=workflow_status,
        report={"evidence_admission_policy_version": EVIDENCE_ADMISSION_POLICY_VERSION},
    ))

    result = await mcp_readiness(server)

    assert result["status"] == status
    assert {item["code"] for item in result["gates"]} == {gate}
    summary = result["cards"][0]["workflow_certification"]
    assert summary["evidence_admission_policy_current"] is True
    assert summary["stale"] is (card_version != 1)


async def test_readiness_does_not_fall_back_to_older_current_policy_report(readiness_case):
    server, _, reports, card_id = readiness_case
    earlier = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for report_id, created_at, body in [
        ("older-current", earlier, {"evidence_admission_policy_version": EVIDENCE_ADMISSION_POLICY_VERSION}),
        ("latest-legacy", earlier + timedelta(seconds=1), {}),
    ]:
        reports.save(CertificationRecord(
            report_id=report_id, kind="card_workflow", subject_id=card_id,
            tenant_id="default", subject_version="1", status="approved",
            report=body, created_at=created_at,
        ))
    before = [record.model_dump(mode="json") for record in reports.list()]

    result = await mcp_readiness(server)

    assert result["status"] == "blocked"
    assert result["cards"][0]["workflow_certification"]["report_id"] == "latest-legacy"
    assert {gate["code"] for gate in result["gates"]} == {"workflow-admission-policy-stale"}
    assert [record.model_dump(mode="json") for record in reports.list()] == before
