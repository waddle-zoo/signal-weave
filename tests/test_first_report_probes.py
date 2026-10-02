"""Offline contract tests for the two development counterexample probes."""

import asyncio
import json

import pytest

from evaluations import first_report_probes as probes
from evaluations.first_report_trial import PeriodAdapter, Session
from signalweave.models import InsightResult, Outcome


def test_probe_cases_are_new_p04_only_and_labels_are_parent_only():
    companies, expected = probes.build_probe_cases()

    assert {company["id"] for company in companies} == set(probes.PROBE_COMPANIES)
    assert all(
        [period["id"] for period in company["periods"]] == ["p04"]
        for company in companies
    )
    assert expected["harbor-help"]["status"] == "complete"
    assert expected["harbor-help"]["outcome"] == Outcome.NOTIFY.value
    assert expected["harbor-help"]["recipients"] == ["support-operations"]
    assert expected["northstar-cart"]["status"] == "complete"
    assert expected["northstar-cart"]["outcome"] == Outcome.IGNORE.value
    assert expected["northstar-cart"]["recipients"] == []

    public = probes._public_inputs(companies)
    serialized = json.dumps(public)
    assert "oracle" not in serialized
    assert "expected_outcome" not in serialized
    assert "p01" not in serialized and "p02" not in serialized and "p03" not in serialized


def test_stable_high_harbor_rate_uses_current_rate_branch_and_northstar_uses_delta_policy():
    companies, expected = probes.build_probe_cases()
    harbor = next(company for company in companies if company["id"] == "harbor-help")
    northstar = next(company for company in companies if company["id"] == "northstar-cart")

    harbor_comparison = harbor["periods"][0]["resources"][0]["analytical_comparisons"][0]
    assert harbor_comparison["baseline_total"] == {"value": None, "numerator": 26.0, "denominator": 200.0}
    assert harbor_comparison["current_total"] == {"value": None, "numerator": 26.0, "denominator": 200.0}
    assert expected["harbor-help"]["outcome"] == "notify"

    northstar_comparison = northstar["periods"][0]["resources"][0]["analytical_comparisons"][0]
    assert northstar_comparison["baseline_total"] == {"value": 1000.0, "numerator": None, "denominator": None}
    assert northstar_comparison["current_total"] == {"value": 1000.0, "numerator": None, "denominator": None}
    assert expected["northstar-cart"]["outcome"] == "ignore"


@pytest.mark.asyncio
@pytest.mark.parametrize("company_id", probes.PROBE_COMPANIES)
async def test_probe_tool_projection_hides_private_labels(company_id):
    companies, _ = probes.build_probe_cases()
    company = next(company for company in companies if company["id"] == company_id)
    from evaluations.bootstrap_agent_trial import Audit

    adapter = PeriodAdapter(company["descriptors"], Audit(), company["sources"])
    adapter.set_period(company["periods"][0])
    session = Session(company=company, adapter=adapter, server=None, phase="monitoring", audit=Audit())
    catalog = await session.call("catalog", {})
    assert "oracle" not in json.dumps(catalog)
    inspected = await session.call("inspect_source", {"source_key": company["sources"][0]["key"]})
    serialized = json.dumps(inspected)
    assert "oracle" not in serialized
    assert "expected_outcome" not in serialized
    assert "p01" not in serialized and "p02" not in serialized and "p03" not in serialized


def test_approved_cards_have_literal_policy_clarification():
    context = probes._load_approved_context(probes.DEFAULT_APPROVED_RUN)
    for company_id in probes.PROBE_COMPANIES:
        result = probes._check_card_policy_clarification(company_id, context["rows"][company_id])
        assert result["status"] == "present", result["message"]
    assert "orbit-subscriptions" not in probes.PROBE_COMPANIES


def test_prepare_archives_inputs_expected_and_sqlite_backups_before_calls(tmp_path):
    output = tmp_path / "probe"
    bundle = probes.prepare_probe_bundle(output)
    manifest = json.loads((output / "manifest.json").read_text())
    inputs = json.loads((output / "inputs.json").read_text())
    expected = json.loads((output / "expected.json").read_text())

    assert bundle["manifest"]["probe_ids"] == ["harbor-help:p04", "northstar-cart:p04"]
    assert manifest["labels_exposed_to_agent"] is False
    assert manifest["budget"]["prior_jev"] + manifest["budget"]["jev_calls_max"] <= manifest["budget"]["jev_ceiling"]
    assert manifest["budget"]["prior_luna"] + manifest["budget"]["luna_episodes_max"] <= manifest["budget"]["luna_ceiling"]
    assert "oracle" not in json.dumps(inputs)
    assert set(expected["expected"]) == set(probes.PROBE_COMPANIES)
    for company_id in probes.PROBE_COMPANIES:
        backup = output / "approved_cards" / f"{company_id}.db"
        assert backup.exists()
        assert manifest["card_policy_clarification"][company_id]["present"] is True
        assert manifest["source_freeze"]["source_sha256"]


def test_expected_archive_contains_full_oracle_analysis_projection(tmp_path):
    probes.prepare_probe_bundle(tmp_path / "probe")
    expected = json.loads((tmp_path / "probe" / "expected.json").read_text())
    for label in expected["expected"].values():
        assert label["analyses"]
        assert label["analyses"][0]["query_refs"]
        assert label["analyses"][0]["comparison_key"]


@pytest.mark.asyncio
async def test_offline_fake_provider_runs_full_probe_path_without_approval_or_network(monkeypatch, tmp_path):
    class FakeJev:
        name = "offline-fake-jev"

        def __init__(self, key, budget, audit):
            self.budget = budget

        async def judge(self, state, card, plan, observations):
            outcome = Outcome.NOTIFY if card.id.startswith("card-weighted") else Outcome.IGNORE
            return InsightResult(
                card_id=card.id,
                outcome=outcome,
                confidence=0.99,
                summary="Offline fake provider",
                rationale="Offline fake provider",
                evidence=state["evidence"],
                observations=observations,
                source_keys=plan.selected_source_keys,
                evaluator=self.name,
            )

    async def fake_codex(session, **kwargs):
        catalog = await session.call("catalog", {})
        source_key = catalog["sources"][0]["key"]
        inspected = await session.call("inspect_source", {"source_key": source_key})
        analysis = inspected["analyses"][0]
        await session.call("submit_report", {
            "status": "complete",
            "outcome": "notify" if session.company["id"] == "harbor-help" else "ignore",
            "recipients": [session.company["destinations"][0]["key"]] if session.company["id"] == "harbor-help" else [],
            "analysis_refs": [{"source_key": source_key, "comparison_key": analysis["comparison_key"]}],
            "narrative": "Offline fake report.",
        })
        return {"status": "complete", "tool_calls": 3, "transport": "offline-fake"}

    monkeypatch.setattr(probes, "TrialJev", FakeJev)
    monkeypatch.setattr(probes, "load_api_key", lambda key_file: "offline-test-key")
    monkeypatch.setattr(probes, "codex_episode", fake_codex)
    result = await probes.run_probes(tmp_path / "probe", live=True, key_file="unused")

    assert len(result["results"]) == 2
    assert result["jev_calls"] == 0
    assert result["luna_episodes"] == 0
    assert all("native_score" in row and "baseline_score" in row for row in result["results"])
    assert all(
        "malformed_analysis" not in row["native_score"]["errors"]
        and "malformed_analysis" not in row["baseline_score"]["errors"]
        for row in result["results"]
    )
    assert (tmp_path / "probe" / "report.json").exists()
    inputs = json.loads((tmp_path / "probe" / "inputs.json").read_text())
    for reference in inputs["approved_card_refs"].values():
        assert probes._file_digest(probes.Path(reference["backup"])) == reference["backup_sha256"]


def test_dry_run_has_no_dispatch_or_key_load(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise AssertionError("offline preparation must not call a provider or MCP tool")

    monkeypatch.setattr(probes, "dispatch", fail)
    monkeypatch.setattr(probes, "load_api_key", fail)
    result = asyncio.run(probes.run_probes(tmp_path / "probe", live=False))
    assert result["status"] == "ready_for_review"
    assert result["paid_calls"] == 0


def test_runner_has_no_approval_call_and_retries_are_zero():
    source = probes.__file__
    text = open(source, encoding="utf-8").read()
    assert "approve_insight_card" not in text
    assert '"retries": 0' in text
