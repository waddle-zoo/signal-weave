import json
from types import SimpleNamespace

import httpx
import pytest

from evaluations.cube_native_continuation import (
    PublishedCubeCompany,
    native_checks,
    revision_checks,
    tracked_reader,
)
from signalweave.models import SourceRef
from tests.test_cube_source import fixture


@pytest.mark.parametrize("treatment", [False, True])
def test_changed_meaning_allows_attributed_current_amounts_but_not_old_business_approval(treatment):
    frozen = {"resource": "metric:net-revenue", "observations": [{"unit": "USD"}],
              "metadata": {"metric_revision": "r4", "data_snapshot_id": "new-cube-result"}}
    expected = {"metric_id": "net", "current": 88.8, "previous": 100, "change_pct": -11.2}
    submitted = {"metric_id": "net", "current": 88.8, "previous": 100, "unit": "USD",
                 "definition_revision": "r4", "data_snapshot_id": "new-cube-result",
                 "source_refs": ["company|metric:net-revenue"], "current_period": "2026-09",
                 "previous_period": "2026-08", "outcome": "investigate", "recipients": ["agent://finance"],
                 "resolution_status": "unresolved"}
    assert all(revision_checks(submitted, frozen, expected, treatment=treatment).values())
    submitted["outcome"] = "notify"
    assert not revision_checks(submitted, frozen, expected, treatment=treatment)["policy"]
    submitted.update(outcome="investigate", definition_revision="r3", current=89)
    checks = revision_checks(submitted, frozen, expected, treatment=treatment)
    assert not checks["revision"] and not checks["current"]
    submitted.update(outcome="deferred", current=88.8, definition_revision="r4")
    assert all(revision_checks(submitted, frozen, expected, treatment=treatment).values())


def test_native_deferred_gate_cannot_hide_a_policy_call_or_wrong_card_behind_good_prose():
    card = {"id": "original", "version": 2}
    packet = {"policy_action_available": False}
    stored = {"receipt": {"card_id": "original", "card_version": 2, "delivery_enabled": False},
              "result": {"card_id": "original", "outcome": None, "delivery_methods": [],
                         "judgment": {"reason": "context_review_required", "provider_call_attempted": False, "provider_call_attempts": 0}}}
    assert all(native_checks(packet, stored, card, {}, {}, revision=True).values())
    stored["result"]["judgment"]["provider_call_attempts"] = 1
    stored["receipt"]["card_id"] = "other"
    checks = native_checks(packet, stored, card, {}, {}, revision=True)
    assert not checks["native_no_provider"] and not checks["exact_card"]


def test_native_cohort_result_requires_matching_correct_measurements_not_only_a_good_agent_answer():
    card = {"id": "original", "version": 4}
    frozen = {"resource": "net", "contract": {"scope": "r4"}, "metadata": {"data_snapshot_id": "corrected", "metric_revision": "r4"},
              "observations": [{"unit": "USD"}]}
    expected = {"current": 102.01, "previous": 100, "change_pct": 2.01}
    stored = {"receipt": {"card_id": "original", "card_version": 4, "delivery_enabled": False},
              "current_context_dependencies": {"required_current": True},
              "result": {"card_id": "original", "outcome": "ignore", "delivery_methods": [],
                         "source_contracts": [{"resource": "net", "contract": {"scope": "r4"}}],
                         "evidence": [{"values": {"data_snapshot_id": "corrected", "metric_revision": "r4", "unit": "USD",
                                                   "current_period": "2026-09", "previous_period": "2026-08", "current": 102.01, "previous": 100}}]}}
    assert all(native_checks({}, stored, card, frozen, expected, revision=False).values())
    stored["result"]["evidence"][0]["values"]["data_snapshot_id"] = "old"
    stored["result"]["outcome"] = "notify"
    checks = native_checks({}, stored, card, frozen, expected, revision=False)
    assert not checks["native_measurements"] and not checks["native_outcome"]


@pytest.mark.asyncio
async def test_declared_owner_publication_is_common_context_not_cube_native_history():
    catalog, result = fixture()

    def handler(request):
        return httpx.Response(200, json=catalog if request.url.path == "/meta" else
                              {"sql": ["SQL", []]} if request.url.path == "/sql" else result)
    async with httpx.AsyncClient(base_url="http://test/", transport=httpx.MockTransport(handler)) as client:
        source = PublishedCubeCompany(client, SimpleNamespace(company="retail", profile={"domain": "commerce"}))
        initial = await source.inspect(SourceRef(key="net", adapter="company", resource="metric:net-revenue", label="Revenue"))
        source.publication = {"body": "Fictional owner correction, not Cube history", "identities": {
                              "current_result": initial.metadata["data_snapshot_id"], "definition_revision": "r7"},
                              "provenance": ["fictional-owner:correction"]}
        await source.refresh_catalog()
        snapshot = await source.inspect(SourceRef(key="net", adapter="company", resource="metric:net-revenue", label="Revenue"))
        assert source.notes()[-1] == source.publication
    assert snapshot.evidence[-1].statement == source.publication["body"]
    assert snapshot.evidence[-1].provenance == ["fictional-owner:correction"]
    assert snapshot.evidence[-1].values == source.publication["identities"]
    assert snapshot.observations[0].current == 88.8


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_field", ["current_result", "definition_revision"])
async def test_correction_cannot_authorize_a_different_result_or_meaning(wrong_field):
    catalog, result = fixture()
    def handler(request):
        return httpx.Response(200, json=catalog if request.url.path == "/meta" else
                              {"sql": ["SQL", []]} if request.url.path == "/sql" else result)
    async with httpx.AsyncClient(base_url="http://test/", transport=httpx.MockTransport(handler)) as client:
        source = PublishedCubeCompany(client, SimpleNamespace(company="retail", profile={"domain": "commerce"}))
        ref = SourceRef(key="net", adapter="company", resource="metric:net-revenue", label="Revenue")
        initial = await source.inspect(ref)
        source.publication = {"body": "Historical correction only", "identities": {
            "current_result": initial.metadata["data_snapshot_id"], "definition_revision": "r7"}, "provenance": ["owner:old"]}
        source.publication["identities"][wrong_field] = "other"
        snapshot = await source.inspect(ref)
        assert len(snapshot.evidence) == 1
        assert snapshot.observations[0].current == 88.8


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_reader_admission_and_raised_failure_are_persisted(tmp_path, fails):
    report, path = {}, tmp_path / "report.json"
    async def action():
        assert json.loads(path.read_text())["attempts"][0]["status"] == "started"
        if fails:
            raise RuntimeError("private-key")
        return "finished"
    audit = SimpleNamespace(redact=lambda value: value.replace("private-key", "[redacted]"))
    if fails:
        with pytest.raises(RuntimeError):
            await tracked_reader(action, report, path, {"arm": "ordinary_context", "case": 0}, audit)
    else:
        assert await tracked_reader(action, report, path, {"arm": "ordinary_context", "case": 0}, audit) == "finished"
    attempt = json.loads(path.read_text())["attempts"][0]
    assert attempt["status"] == ("failed" if fails else "completed")
    if fails:
        assert attempt["error"] == "[redacted]" and attempt["error_type"] == "RuntimeError"
