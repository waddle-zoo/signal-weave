from __future__ import annotations

import asyncio
import json
from pathlib import Path

from evaluations.northstar_growth_history_adversarial_review import audit_report
from evaluations.northstar_growth_history_trial import (
    DEFAULT_SPEC,
    build_historical_cases,
    card_for_spec,
    load_spec,
    movement_only_outcome,
    run_trial,
)
from evaluations.northstar_shadow_trial import _build_resources, _load_period_data
from signalweave.models import Evidence, InsightResult, Outcome


def _write_seed_dir(root: Path) -> Path:
    root.mkdir()
    (root / "fct_sales_order_line.csv").write_text(
        "order_date,channel,net_sales\n"
        "2026-01-01,Online,100\n"
        "2026-02-01,Store,120\n"
        "2026-03-01,Mobile,140\n",
        encoding="utf-8",
    )
    (root / "fct_web_session.csv").write_text(
        "event_date,sessions,orders,revenue\n"
        "2026-01-01,100,10,100\n"
        "2026-02-01,100,10,100\n"
        "2026-03-01,100,10,100\n",
        encoding="utf-8",
    )
    (root / "fct_support_ticket.csv").write_text(
        "event_date,backlog\n2026-01-01,10\n2026-02-01,10\n2026-03-01,10\n",
        encoding="utf-8",
    )
    (root / "fct_finance_daily.csv").write_text(
        "event_date,revenue\n2026-01-01,100\n2026-02-01,100\n2026-03-01,100\n",
        encoding="utf-8",
    )
    return root


class _FakeJev:
    name = "fake-jev-for-harness-tests"

    def __init__(self) -> None:
        self.metrics = type("Metrics", (), {"requests": 0, "input_tokens": 0, "output_tokens": 0})()

    async def compile_plan(self, state, card):
        self.metrics.requests += 1
        return {
            "capabilities": ["typed judgment"],
            "baseline": "previous_period",
        }

    async def judge(self, state, card, plan, observations):
        self.metrics.requests += 1
        primary = next(item for item in observations if item.subject_id == "revenue-total")
        if abs(primary.change_pct or 0) < 10:
            outcome = Outcome.IGNORE
        elif any(item.subject_id == "finance-revenue" and (item.change_pct or 0) <= -10 for item in observations):
            outcome = Outcome.NOTIFY
        else:
            outcome = Outcome.INVESTIGATE
        return InsightResult(
            card_id=card.id,
            outcome=outcome,
            delivery_methods=[method for method in card.delivery_methods if method.outcome == outcome],
            summary="The evidence bundle contains the observed sources.",
            rationale="The primary movement was evaluated with cross-source context.",
            confidence=0.9,
            probabilities={outcome.value: 0.9},
            observations=observations,
            evidence=[
                Evidence(
                    source_key=observation.source_key,
                    subject_id=observation.subject_id,
                    subject_label=observation.subject_label,
                    statement="Observed in the source snapshot.",
                )
                for observation in observations
            ],
            evaluator=self.name,
        )


def test_register_expands_without_labels_in_card():
    spec = load_spec(DEFAULT_SPEC)
    cases = build_historical_cases(spec)

    assert len(cases) == 48
    assert {case.split for case in cases} == {"train", "validation", "holdout"}
    assert len({case.case_id for case in cases}) == 48
    payload = json.dumps(card_for_spec(spec).execution_payload()).lower()
    assert "historical_outcome" not in payload
    assert "manual_minutes" not in payload


def test_movement_only_control_pushes_on_movement_but_does_not_explain_it(tmp_path):
    seed_dir = _write_seed_dir(tmp_path / "seed")
    spec = load_spec(DEFAULT_SPEC)
    case = next(case for case in build_historical_cases(spec) if case.variant_id == "day-04-corroborated-decline")
    period = _load_period_data(seed_dir)
    resources = _build_resources(period, case.replay_case)

    assert movement_only_outcome(resources, threshold_percent=10, missing_primary="ignore") == "notify"
    assert all(resource.evidence for resource in resources)


def test_live_harness_shape_and_adversarial_gate_with_deterministic_jev_stub(tmp_path):
    seed_dir = _write_seed_dir(tmp_path / "seed")
    report = asyncio.run(
        run_trial(
            seed_dir=seed_dir,
            output=tmp_path / "report.json",
            judger=_FakeJev(),
        )
    )

    assert report["decision_register"]["case_count"] == 48
    assert report["overall"]["movement_only_unnecessary_pushes"] > 0
    assert (tmp_path / "report.md").exists()

    review = audit_report(report)
    assert review["passed"] is False
    assert review["summary"]["error_count"] > 0


def test_adversarial_reviewer_catches_mutated_unsafe_push(tmp_path):
    seed_dir = _write_seed_dir(tmp_path / "seed")
    report = asyncio.run(
        run_trial(seed_dir=seed_dir, output=tmp_path / "report.json", judger=_FakeJev())
    )
    mutated = json.loads(json.dumps(report))
    target = next(item for item in mutated["cases"] if item["historical_outcome"] == "ignore")
    target["signalweave_unnecessary_push"] = True
    target["actual_outcome"] = "notify"

    review = audit_report(mutated)

    assert review["passed"] is False
    assert any(
        finding.get("case_id") == target["case_id"]
        and "unnecessary leadership push" in finding["message"]
        for finding in review["findings"]
    )
