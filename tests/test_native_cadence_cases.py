from __future__ import annotations

import copy
from datetime import date

import pytest

from evaluations import native_cadence_trial as cadence_trial
from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter
from evaluations.installed_northstar_cases import NORTHSTAR_POLICY_INTERVENTION
from evaluations.native_cadence_cases import (
    MONTHS,
    PILOT_INDICES,
    SIMULATED_SCOPE,
    _outcome,
    _validate,
    build_cadence_scenario,
)
from signalweave.models import ResourceSnapshot


@pytest.fixture(scope="module")
def built():
    return build_cadence_scenario()


def _ref(scenario, title):
    item = next(x for x in scenario["public"]["catalog"] if x["title"] == title)
    return f"{item['adapter']}|{item['resource']}"


def _sales(scenario, index):
    return scenario["public"]["periods"][index]["snapshots"][
        _ref(scenario, "Northstar Executive Pulse")
    ]


class _NoToolsServer:
    async def list_tools(self):
        return []


@pytest.mark.asyncio
async def test_real_cadence_session_constructor_and_specs_accept_fixture_context(built):
    scenario, _ = built
    public = {"scenario_id": scenario["scenario_id"], **scenario["public"]}
    assert public["numeric_vocabulary"] == []
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())

    for treatment, arm in ((False, "baseline"), (True, "treatment")):
        session = cadence_trial.CadenceSession(
            public, adapter, _NoToolsServer(), treatment, arm=arm
        )
        specs = await session.specs()
        assert isinstance(specs, list)
        assert session.public["numeric_vocabulary"] == []


def test_twelve_months_stage_gate_and_owner_policy_are_frozen(built):
    scenario, registration = built
    public = scenario["public"]
    assert registration["reporting_months"] == list(MONTHS)
    closes = []
    for p in public["periods"]:
        d = date.fromisoformat(p["as_of"][:10])
        closes.append(date(d.year - (d.month == 1), d.month - 1 or 12, 1).strftime("%Y-%m"))
    assert closes == list(MONTHS)
    assert registration["pilot_indices"] == PILOT_INDICES == [0, 3, 6, 9]
    assert registration["pilot_outcomes"] == [
        "ignore",
        "investigate",
        "notify",
        "insufficient_data",
    ]
    assert [x["expected_outcome"] for x in registration["case_schedule"]] == [
        "ignore",
        "ignore",
        "investigate",
        "investigate",
        "investigate",
        "investigate",
        "notify",
        "investigate",
        "notify",
        "insufficient_data",
        "insufficient_data",
        "insufficient_data",
    ]
    expected_answers = copy.deepcopy(NORTHSTAR_POLICY_INTERVENTION["owner_answers"])
    expected_answers["metric_scope"] = SIMULATED_SCOPE
    assert public["owner_answers"] == expected_answers
    assert (
        scenario["policy_intervention"]["owner_answers"]
        == registration["owner_answers"]
        == expected_answers
    )
    assert "not actual order-line records" in public["owner_answers"]["metric_scope"]
    directory = {x["key"]: x["destination"] for x in public["destinations"]}
    assert {
        r for label in scenario["private"]["periods"].values() for r in label["recipients"]
    } <= set(directory)
    for outcome, recipient in (
        ("notify", "leadership"),
        ("investigate", "analytics"),
        ("insufficient_data", "data-trust"),
    ):
        assert f"{outcome} -> {recipient}" in public["owner_answers"]["routing"]
        assert directory[recipient] == f"slack://simulation-{recipient}"
    assert (
        "retrospectively" in public["brief"]
        and "do not report a current business incident" in public["decision_guidance"]
    )
    assert not {"case_family", "expected_outcome", "scorer"} & set(public)
    assert registration["holdout_scope"].startswith(
        "Remaining windows are the same fictional company"
    )


def test_nested_generated_evidence_has_exact_row_lineage_and_no_live_source_claims(built):
    scenario, _ = built
    public = scenario["public"]
    for period in [public["onboarding"], *public["periods"]]:
        assert set(period["snapshots"]) == {_ref(scenario, x["title"]) for x in public["catalog"]}
        for _ref_key, raw in period["snapshots"].items():
            snap = ResourceSnapshot.model_validate(raw)
            assert (
                snap.source_key == raw["resource"]
                and snap.metadata["data_origin"] == "simulation_coordinator_authored"
            )
            assert snap.metadata["source_transport"] == "generated_fictional_monthly_close"
            assert snap.metadata["archived_measurement"] is True
            assert (
                "historical measurement window" in snap.observations[0].freshness.lower()
                if snap.observations
                else True
            )
            assert snap.source_url.startswith("simulation-ledger://")
            assert all(not obs.source_url.startswith("http") for obs in snap.observations)
            rows = [
                *snap.metadata.get("ledger_rows", snap.metadata.get("generated_records", [])),
                *snap.metadata.get("aggregate_capture_rows", []),
            ]
            by_id = {r["record_id"]: r for r in rows}
            assert len(by_id) == len(rows)
            assert all(r["data_origin"] == "simulation_coordinator_authored" for r in rows)
            assert len({r["population_id"] for r in rows}) <= 1
            for observation in snap.observations:
                used = [by_id[x] for x in observation.attributes["record_ids"]]
                assert observation.attributes["capture_ids"] == sorted(
                    {r["capture_id"] for r in used}
                )
                assert observation.attributes["revision_ids"] == sorted(
                    {r["revision_id"] for r in used}
                )
            for evidence in snap.evidence:
                used = [by_id[x] for x in evidence.provenance]
                assert evidence.provenance == evidence.values["record_ids"]
                assert evidence.values["capture_ids"] == sorted({r["capture_id"] for r in used})
                assert evidence.values["revision_ids"] == sorted({r["revision_id"] for r in used})
    assert public["source_transport"]["actual_superset"] is False


def test_complete_sales_windows_reconcile_from_the_same_rows(built):
    scenario, _ = built
    for index in range(9):
        snap = ResourceSnapshot.model_validate(_sales(scenario, index))
        total = next(x for x in snap.observations if x.subject_id == "revenue-total")
        channels = [x for x in snap.observations if x.subject_id.startswith("channel-")]
        assert len(channels) == 4
        assert abs(total.current - sum(x.current for x in channels)) < 1e-6
        assert abs(total.baseline - sum(x.baseline for x in channels)) < 1e-6
        assert set(total.attributes["record_ids"]) == set().union(
            *(set(x.attributes["record_ids"]) for x in channels)
        )
        assert all(r["currency"] == "USD" for r in snap.metadata["ledger_rows"])


def test_mismatch_uses_truthful_prior_revision_capture_and_reconciles_to_insufficient_data(built):
    scenario, registration = built
    snap = ResourceSnapshot.model_validate(_sales(scenario, 10))
    total = next(x for x in snap.observations if x.subject_id == "revenue-total")
    channels = [x for x in snap.observations if x.subject_id.startswith("channel-")]
    assert abs((total.current - sum(x.current for x in channels)) - 10) < 1e-6
    assert abs(total.baseline - sum(x.baseline for x in channels)) < 1e-6
    assert total.attributes["revision_ids"] == ["aggregate-r0"]
    assert all(x.attributes["revision_ids"] == ["r1"] for x in channels)
    assert not set(total.attributes["capture_ids"]) & set(channels[0].attributes["capture_ids"])
    assert "different captures" in snap.metadata["source_capture"]
    assert "not one consistent snapshot" in snap.contract.comparison_contracts[0].detail
    assert {x["query"] for x in snap.metadata["capture_history"]} == {
        "controlling-total",
        "channel-ledger",
    }
    assert registration["case_schedule"][10]["expected_outcome"] == "insufficient_data"


def test_partial_case_has_only_twenty_days_of_current_rows(built):
    scenario, registration = built
    snap = ResourceSnapshot.model_validate(_sales(scenario, 11))
    current = [r for r in snap.metadata["ledger_rows"] if r["reporting_month"] == "2026-01"]
    assert len(current) == 4
    assert {(r["coverage_days"], r["period_days"], r["covered_through"]) for r in current} == {
        (20, 31, "2026-01-20")
    }
    assert snap.contract.comparison_contracts[0].coverage == "partial"
    assert snap.contract.comparison_contracts[0].comparable is False
    assert "20 of 31 days" in snap.contract.comparison_contracts[0].detail
    assert registration["case_schedule"][11]["expected_outcome"] == "insufficient_data"


def test_private_scoring_reads_raw_rows_and_preflight_rejects_tampered_producer_values(built):
    scenario, _ = built
    period = copy.deepcopy(scenario["public"]["periods"][6])
    for snapshot in period["snapshots"].values():
        for observation in snapshot["observations"]:
            observation["change_pct"] = 0
    assert _outcome(period, scenario["public"]["owner_answers"]) == "notify"
    corrupted = copy.deepcopy(scenario)
    corrupted["public"]["periods"][0]["snapshots"][_ref(scenario, "Northstar Executive Pulse")][
        "observations"
    ][0]["current"] += 1
    with pytest.raises(ValueError, match="Observation values do not reproduce"):
        _validate(corrupted)
