"""Offline replay of retained live judgments; not new live or accuracy evidence."""

import json
from pathlib import Path

import pytest

from signalweave.compiler import base_plan
from signalweave.engine import InsightEngine
from signalweave.models import InsightCard, InsightResult, ResourceSnapshot

EVIDENCE = Path(__file__).resolve().parents[1] / "docs/evidence/bootstrap-owner-reviewed-v4-01"


@pytest.fixture(scope="module")
def recorded():
    native = json.loads((EVIDENCE / "owner-review-and-native.json").read_text())["native"]
    blind = json.loads((EVIDENCE / "blind-review.json").read_text())["cases"]
    mapping = json.loads((EVIDENCE / "review-key.json").read_text())
    periods = {
        (mapping[c["case_id"]]["scenario_id"], mapping[c["case_id"]]["period_id"]): c["business"]["period"]
        for c in blind
    }
    return native, periods


@pytest.mark.parametrize("index", range(6))
def test_retained_live_judgments_produce_truthful_question_handoffs(recorded, index):
    rows, periods = recorded
    row = rows[index]
    original = json.dumps(row, sort_keys=True)
    card = InsightCard.model_validate(row["card"])
    result = InsightResult.model_validate(row["result"])
    period = periods[row["scenario_id"], row["period_id"]]
    resources = []
    for source in card.sources:
        resource = ResourceSnapshot.model_validate(period["snapshots"][f"{source.adapter}|{source.resource}"])
        resource.source_key = source.key
        resource.evidence = [e.model_copy(update={"source_key": source.key}) for e in resource.evidence]
        resource.observations = [o.model_copy(update={"source_key": source.key}) for o in resource.observations]
        resources.append(resource)
    errors = InsightEngine._source_errors(card, resources, now=result.evaluated_at)
    current = InsightEngine._build_evidence_plan(
        card=card, plan=base_plan(card), result=result, resources=resources,
        context=result.context, source_errors=errors,
    )
    blocked = any(e["blocking"] for e in errors) or any(
        report.required and report.status != "complete" for report in result.analyses
    )
    for slot in current.slots:
        if slot.role != "question":
            continue
        judgment = result.question_results[int(slot.key.split(":")[1]) - 1]
        expected = "unavailable" if blocked else "fulfilled" if judgment.status.value == "supported" else "pending"
        assert slot.status == expected
        assert slot.key not in current.conflicting_slot_keys
        if expected != "fulfilled":
            assert slot.key in current.missing_slot_keys
    assert current.status == result.evidence_plan.status
    assert json.dumps(row, sort_keys=True) == original
