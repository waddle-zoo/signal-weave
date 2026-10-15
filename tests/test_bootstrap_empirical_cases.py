import copy
import json
from datetime import datetime, timedelta

import pytest

from evaluations.bootstrap_empirical_cases import build_companies
from signalweave.engine import InsightEngine
from signalweave.models import InsightCard, InsightResult, Outcome, ResourceSnapshot, SourceRef


def _all_cases(company):
    return [*company["setup_cases"], *company["holdout_cases"]]


def _resources(case):
    return [ResourceSnapshot.model_validate(resource) for resource in case["resources"]]


def test_fixture_has_exact_small_authoring_shape_and_compiled_control():
    companies = build_companies()

    assert len(companies) == 3
    assert {company["brief"].split()[0] for company in companies} == {"Support", "Database", "Finance"}
    for company in companies:
        assert set(company) == {
            "id", "brief", "owner_policy", "as_of", "destinations", "sources",
            "setup_cases", "holdout_cases", "expert_card",
        }
        assert len(company["setup_cases"]) == 3
        assert len(company["holdout_cases"]) == 4
        assert all("card" not in case for case in _all_cases(company))
        card = InsightCard.model_validate(company["expert_card"])
        assert card.compiled_plan is not None
        assert card.compiled_plan.card_id == card.id
        assert card.compiled_plan.selected_source_keys == [source["key"] for source in company["sources"]]
        assert card.max_source_age_hours == 24
        assert all("outcome" not in destination for destination in company["destinations"])
        assert all(
            SourceRef.model_validate(source).required
            for source in company["sources"]
            if source["label"] != "Database host CPU"
        )


def test_setup_and_holdout_are_disjoint_and_do_not_leak_condition_labels():
    for company in build_companies():
        periods = []
        for case in _all_cases(company):
            case_periods = set()
            for resource in _resources(case):
                case_periods.add(resource.metadata["period_id"])
                payload = json.dumps(resource.model_dump(mode="json")).lower()
                assert "event" not in payload
                assert "quiet" not in payload
                assert "missing" not in payload
            assert len(case_periods) == 1
            periods.extend(case_periods)
        assert len(periods) == len(set(periods))
        payload = json.dumps(company).lower()
        assert '"expert_card"' in payload  # only the separate expert control is allowed.
        assert '"event"' not in payload
        assert '"quiet"' not in payload
        assert '"missing"' not in payload


def test_refs_population_contract_and_timestamps_are_stable():
    for company in build_companies():
        sources = {source["key"]: SourceRef.model_validate(source) for source in company["sources"]}
        refs = {f"{source.adapter}|{source.resource}" for source in sources.values()}
        assert refs
        assert all(source.parameters["approval"] == "owner-reviewed synthetic source" for source in sources.values())
        assert all(source.parameters["period_contract"] for source in sources.values())
        assert all(source.parameters["source_age_contract"] for source in sources.values())
        company_as_of = datetime.fromisoformat(company["as_of"])
        for case in _all_cases(company):
            required_keys = set(case["required_evidence_source_keys"])
            optional_keys = {key for key, source in sources.items() if not source.required}
            assert required_keys == set(sources) - optional_keys
            assert set(case["expected_retrieval_refs"]) == refs
            for resource in _resources(case):
                assert resource.source_key in sources
                replay_clock = datetime.fromisoformat(resource.metadata["replay_clock"])
                assert resource.captured_at == replay_clock
                assert resource.captured_at <= company_as_of
                assert resource.captured_at - resource.source_captured_at == timedelta(hours=1)
                assert resource.source_captured_at <= resource.captured_at
                assert resource.metadata["as_of"] == company["as_of"]
                assert resource.metadata["period_contract"]
                assert resource.metadata["source_age_contract"]
                assert resource.metadata["period_end"] < resource.metadata["replay_clock"]
                assert resource.contract.population
                assert resource.contract.available_comparison_windows == ["previous_period"]


def test_support_arithmetic_and_policy_labels_are_independently_checkable():
    company = next(item for item in build_companies() if item["brief"].startswith("Support"))
    for case in _all_cases(company):
        measurement = _resources(case)[0]
        values = measurement.evidence[0].values
        denominator = values["current_denominator"]
        expected = Outcome.INVESTIGATE if denominator is None else (
            Outcome.NOTIFY if values["current_numerator"] / denominator >= 0.10 else Outcome.IGNORE
        )
        assert case["expected_outcome"] == expected.value
        if denominator is not None:
            assert values["current_rate"] == values["current_numerator"] / denominator
            assert values["delta"] == values["current_rate"] - values["baseline_rate"]


def test_database_coverage_and_cpu_cases_do_not_collapse_into_notification():
    company = next(item for item in build_companies() if item["brief"].startswith("Database"))
    source_by_label = {source["label"]: source for source in company["sources"]}
    assert source_by_label["Database host CPU"]["required"] is False
    for case in _all_cases(company):
        resources = _resources(case)
        latency = resources[0].evidence[0].values
        inventory = resources[1].evidence[0].values
        if inventory["coverage"] == "unknown":
            expected = Outcome.INSUFFICIENT_DATA
        elif latency["current_p95_ms"] > 120 and latency["current_lag_ms"] > 50:
            expected = Outcome.INVESTIGATE
        else:
            expected = Outcome.IGNORE
        assert case["expected_outcome"] == expected.value
        assert case["expected_outcome"] != Outcome.NOTIFY.value
        assert latency["p95_delta_ms"] == latency["current_p95_ms"] - latency["baseline_p95_ms"]
        assert latency["lag_delta_ms"] == latency["current_lag_ms"] - latency["baseline_lag_ms"]
        assert source_by_label["Database host CPU"]["key"] not in case["required_evidence_source_keys"]
        assert any(resource.source_key == source_by_label["Database host CPU"]["key"] for resource in resources)


def test_case_substance_is_unique_after_scrubbing_fixture_ids_and_clocks():
    scrub_keys = {"company_id", "period_id", "period_start", "period_end", "as_of", "replay_clock"}

    def substantive(case):
        payload = copy.deepcopy(case["resources"])
        for resource in payload:
            resource["metadata"] = {
                key: value for key, value in resource["metadata"].items() if key not in scrub_keys
            }
            resource.pop("captured_at", None)
            resource.pop("source_captured_at", None)
            for evidence in resource["evidence"]:
                evidence.pop("subject_id", None)
                evidence.pop("provenance", None)
            for observation in resource["observations"]:
                observation.pop("subject_id", None)
                observation.pop("provenance", None)
        return json.dumps(payload, sort_keys=True)

    for company in build_companies():
        values = [substantive(case) for case in _all_cases(company)]
        assert len(values) == len(set(values))


def test_finance_uses_signed_status_precedence_without_numeric_facts():
    company = next(item for item in build_companies() if item["brief"].startswith("Finance"))
    for case in _all_cases(company):
        resources = _resources(case)
        ledger = resources[0].evidence[0].values["signed_status"]
        note = resources[1].evidence[0].values["note_status"]
        expected = Outcome.INSUFFICIENT_DATA if ledger is None else (
            Outcome.NOTIFY if ledger == "approved" else
            Outcome.INVESTIGATE if ledger == "unresolved" else Outcome.IGNORE
        )
        assert case["expected_outcome"] == expected.value
        assert all(not isinstance(value, (int, float)) for resource in resources for evidence in resource.evidence for value in evidence.values.values())
        if ledger == "approved" and note == "rejected":
            assert case["expected_outcome"] == Outcome.NOTIFY.value
        if ledger == "unresolved":
            directory = {item["key"]: item["destination"] for item in company["destinations"]}
            assert case["expected_delivery_destinations"] == {
                key: directory[key] for key in case["expected_delivery_method_keys"]
            }


def test_case_routes_are_exact_and_fixture_is_reproducible_without_mutation():
    first = build_companies()
    second = build_companies()
    assert first == second
    assert first != build_companies(seed=7)
    original = copy.deepcopy(first)
    first[0]["setup_cases"][0]["resources"][0]["evidence"][0]["values"]["current_numerator"] = 999
    assert build_companies() == original

    for company in build_companies():
        directory = {item["key"]: item["destination"] for item in company["destinations"]}
        for case in _all_cases(company):
            keys = case["expected_delivery_method_keys"]
            destinations = case["expected_delivery_destinations"]
            assert set(destinations) == set(keys)
            assert destinations == {key: directory[key] for key in keys}
            if case["expected_outcome"] in {Outcome.NOTIFY.value, Outcome.INVESTIGATE.value}:
                assert keys, f"actionable case lost its independently authored route: {case['id']}"
            assert set(case["expected_retrieval_refs"]) == {
                f"{resource.adapter}|{resource.resource}" for resource in _resources(case)
            }


class _ExpectedOutcomeJudger:
    """Test-only plumbing double; this makes no semantic-accuracy claim."""

    name = "fixture-expected-outcome-only"

    def __init__(self, labels):
        self.labels = labels

    async def judge(self, state, card, plan, observations):
        del plan
        period_id = state["sources"][0]["metadata"]["period_id"]
        label = self.labels[period_id]
        outcome = Outcome(label["expected_outcome"])
        return InsightResult(
            card_id=card.id,
            outcome=outcome,
            delivery_methods=[
                method for method in card.delivery_methods
                if method.key in label["expected_delivery_method_keys"]
            ],
            summary="Test-only injected expected outcome.",
            rationale="Test-only injected expected outcome; not a Jev result.",
            confidence=0.99,
            probabilities={outcome.value: 0.99},
            watch_results=[
                {"key": f"watch_{index}", "watch_for": watch, "status": "present", "probability": 0.99}
                for index, watch in enumerate(card.watch_for)
            ],
            question_results=[
                {"key": f"question_{index}", "question": question, "status": "supported", "probability": 0.99}
                for index, question in enumerate(card.questions)
            ],
            evidence=state["evidence"],
            observations=observations,
            source_keys=[source["source_key"] for source in state["sources"]],
            evaluator=self.name,
        )


@pytest.mark.asyncio
async def test_real_engine_replays_all_cases_with_test_only_expected_judger():
    """Exercise compile, admission, freshness, evidence and routing plumbing only."""

    replayed = 0
    for company in build_companies():
        card = InsightCard.model_validate(company["expert_card"])
        labels = {
            resource.metadata["period_id"]: case
            for case in _all_cases(company)
            for resource in [_resources(case)[0]]
        }
        for case in _all_cases(company):
            resources = _resources(case)
            replay_clock = datetime.fromisoformat(resources[0].metadata["replay_clock"])
            run = await InsightEngine(
                _ExpectedOutcomeJudger(labels), clock=lambda replay_clock=replay_clock: replay_clock
            ).evaluate(card, resources)
            result = run.result

            # These are independent contract checks; no assertion derives one
            # route or outcome from another, and no engine result is replaced.
            assert result.outcome.value == case["expected_outcome"]
            assert [method.key for method in result.delivery_methods] == case["expected_delivery_method_keys"]
            assert {
                method.key: method.destination for method in result.delivery_methods
            } == case["expected_delivery_destinations"]
            assert set(case["required_evidence_source_keys"]).issubset(result.source_keys)
            assert set(result.source_keys) == {resource.source_key for resource in resources}
            assert not any(
                "old" in warning.lower() or "stale" in warning.lower()
                for warning in result.telemetry.warnings
            )

            raw_evidence = {
                (item["source_key"], item["statement"], json.dumps(item["values"], sort_keys=True))
                for resource in case["resources"]
                for item in resource["evidence"]
            }
            returned_evidence = {
                (item.source_key, item.statement, json.dumps(item.values, sort_keys=True))
                for item in result.evidence
            }
            assert raw_evidence <= returned_evidence
            assert {observation.source_key for observation in result.observations} <= set(result.source_keys)
            replayed += 1

    assert replayed == 21
