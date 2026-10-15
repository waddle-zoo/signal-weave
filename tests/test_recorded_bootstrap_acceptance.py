"""The new acceptance gate rejects the actual retained v4 bootstrap failures.

Offline scoring of historical native outputs, NOT new inference or repaired
accuracy. No agent override, policy edit or label change is used to earn a pass.
"""

from types import SimpleNamespace

from test_recorded_question_handoff import recorded as recorded

from evaluations.bootstrap_scenarios import build_scenarios
from signalweave.evaluation import CardEvaluationCase, CardWorkflowEvaluator
from signalweave.models import InsightCard, InsightResult, ResourceSnapshot


async def test_empirical_acceptance_rejects_both_previously_approved_v4_cards(recorded):
    rows, periods = recorded
    scenarios = {s["scenario_id"]: s for s in build_scenarios(seed=20261002, split="holdout")}
    all_results = []
    for scenario_id in dict.fromkeys(row["scenario_id"] for row in rows):
        selected = [row for row in rows if row["scenario_id"] == scenario_id]
        scenario = scenarios[scenario_id]
        directory = {d["key"]: d["destination"] for d in scenario["public"]["destinations"]}
        cases = []
        for row in selected:
            card = InsightCard.model_validate(row["card"])
            period = periods[scenario_id, row["period_id"]]
            label = scenario["private"]["periods"][row["period_id"]]
            resources = []
            for source in card.sources:
                resource = ResourceSnapshot.model_validate(period["snapshots"][f"{source.adapter}|{source.resource}"])
                resource.source_key = source.key
                resources.append(resource)
            cases.append(CardEvaluationCase(
                id=row["period_id"], card=card, resources=resources,
                expected_outcome=label["outcome"],
                expected_delivery_method_keys=label["recipients"],
                expected_delivery_destinations={key: directory[key] for key in label["recipients"]},
                required_evidence_source_keys=[],
                expected_retrieval_refs=[f"{s.adapter}|{s.resource}" for s in card.sources],
            ))

        class RecordedEngine:
            def __init__(self, results):
                self.results = iter(results)

            async def evaluate(self, card, resources, context_override=None):
                return SimpleNamespace(
                    result=InsightResult.model_validate(next(self.results)["result"]), resources=resources,
                )

        acceptance = await CardWorkflowEvaluator(RecordedEngine(selected), max_concurrency=1).evaluate(
            cases, acceptance_outcomes=sorted({case.expected_outcome for case in cases}),
        )
        # The compact historical export omits compiled plans. Do not invent one
        # to call it a current acceptance artifact; the incomplete proof blocks.
        assert acceptance.acceptance_passed is False
        assert any("compiled_plan" in reason for reason in acceptance.preflight_blockers)
        # Diagnostic scoring still reveals the original outcome/endpoint failures.
        report = await CardWorkflowEvaluator(RecordedEngine(selected), max_concurrency=1).evaluate(cases)
        assert report.successful_case_count == 3
        assert report.status == "shadow"
        assert any(case.failure_reasons for case in report.cases)
        all_results.extend(report.cases)
    assert sum(row.exact_outcome and row.delivery_exact for row in all_results) == 2
    assert any("delivery_destinations_mismatch" in row.failure_reasons for row in all_results)
    assert any(row.evidence_plan and row.evidence_plan.missing_slot_keys for row in all_results)
