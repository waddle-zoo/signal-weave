"""Jev-only counterfactual trial for card-context quality.

This evaluation does not change production card semantics. It compares the
same enterprise cases before and after a human adds two explicit boundaries:
planned movement is not actionable, and an uncorroborated material movement is
investigate-only. The expected labels stay outside Jev; the clarification is
the only input change.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluations.everything_tracking_trial import (
    DEFAULT_CONFIG,
    TrackingCase,
    build_cases,
    load_config,
)
from signalweave.engine import InsightEngine
from signalweave.models import InsightCard, Outcome
from signalweave.typesafe_adapter import JevJudger, load_api_key

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "everything-tracking-card-clarity-trial.json"


def clarify_card(card: InsightCard, variant: str) -> InsightCard:
    watch_for = list(card.watch_for)
    questions = list(card.questions)
    if variant == "expected_change":
        watch_for.append(
            "If an owner or planning source says the movement was planned or expected, treat it as expected context and do not notify or escalate."
        )
        questions.append(
            "Does the owner or planning source explicitly say this movement was planned? If yes, return ignore."
        )
    elif variant == "ambiguous_state":
        watch_for.append(
            "If the primary movement is material but connected evidence does not corroborate it, do not notify or escalate; return investigate."
        )
        questions.append(
            "Is the movement corroborated by a connected signal? If not, return investigate."
        )
    else:
        raise ValueError(f"clarity trial only supports expected_change and ambiguous_state, got {variant}")
    return card.model_copy(update={"watch_for": watch_for, "questions": questions})


def clarified_case(case: TrackingCase) -> TrackingCase:
    return case.__class__(
        case_id=case.case_id,
        company_id=case.company_id,
        tenant_id=case.tenant_id,
        company_shape=case.company_shape,
        workflow_id=case.workflow_id,
        domain=case.domain,
        variant=case.variant,
        card=clarify_card(case.card, case.variant),
        resources=case.resources,
        expected_outcome=case.expected_outcome,
        expected_evidence_source_keys=case.expected_evidence_source_keys,
    )


def _expected_delivery(case: TrackingCase) -> list[str]:
    if case.expected_outcome not in {Outcome.NOTIFY.value, Outcome.ESCALATE.value}:
        return []
    return sorted(
        method.key
        for method in case.card.delivery_methods
        if method.outcome.value == case.expected_outcome
    )


def _score(case: TrackingCase, result: Any, elapsed_ms: float, error: str | None) -> dict[str, Any]:
    actual = result.outcome.value if result is not None else None
    actual_delivery = sorted(method.key for method in (result.delivery_methods if result else []))
    actual_evidence = sorted({item.source_key for item in (result.evidence if result else [])})
    required = set(case.expected_evidence_source_keys)
    exact = bool(
        error is None
        and actual == case.expected_outcome
        and actual_delivery == _expected_delivery(case)
        and required <= set(actual_evidence)
    )
    unsafe = actual in {Outcome.NOTIFY.value, Outcome.ESCALATE.value} and not exact
    return {
        "case_id": case.case_id,
        "variant": case.variant,
        "expected_outcome": case.expected_outcome,
        "actual_outcome": actual,
        "exact": exact,
        "unsafe_automatic_action": unsafe,
        "expected_evidence_source_keys": sorted(required),
        "actual_evidence_source_keys": actual_evidence,
        "confidence": result.confidence if result else None,
        "actual_delivery": actual_delivery,
        "elapsed_ms": round(elapsed_ms, 2),
        "error": error,
    }


async def _evaluate(engine: InsightEngine, case: TrackingCase, arm: str) -> dict[str, Any]:
    started = asyncio.get_running_loop().time()
    try:
        run = await engine.evaluate(case.card, case.resources)
        row = _score(case, run.result, (asyncio.get_running_loop().time() - started) * 1000, None)
    except Exception as error:  # noqa: BLE001 - provider errors remain visible in the report
        row = _score(
            case,
            None,
            (asyncio.get_running_loop().time() - started) * 1000,
            f"{type(error).__name__}: {error}",
        )
    row["arm"] = arm
    return row


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_variant[row["variant"]].append(row)
    return {
        "cases": len(rows),
        "exact": sum(row["exact"] for row in rows),
        "exact_rate": round(sum(row["exact"] for row in rows) / len(rows), 4) if rows else 0.0,
        "unsafe_automatic_actions": sum(row["unsafe_automatic_action"] for row in rows),
        "errors": sum(row["error"] is not None for row in rows),
        "median_ms": round(sorted(row["elapsed_ms"] for row in rows)[len(rows) // 2], 2) if rows else None,
        "by_variant": {
            variant: {
                "cases": len(items),
                "exact": sum(row["exact"] for row in items),
                "exact_rate": round(sum(row["exact"] for row in items) / len(items), 4),
                "unsafe_automatic_actions": sum(row["unsafe_automatic_action"] for row in items),
            }
            for variant, items in sorted(by_variant.items())
        },
    }


async def run_trial(args: argparse.Namespace) -> dict[str, Any]:
    cases = [
        case
        for case in build_cases(load_config(args.config), repeats=args.repeats)
        if case.variant in {"expected_change", "ambiguous_state"}
    ]
    if args.limit is not None:
        cases = cases[: args.limit]
    key = load_api_key(args.typesafe_key_file)
    if not key:
        raise RuntimeError("provide a TypeSafe key with --typesafe-key-file or TYPESAFE_API_KEY")
    engine = InsightEngine(judger=JevJudger(api_key=key))
    rows: list[dict[str, Any]] = []
    for case in cases:
        rows.append(await _evaluate(engine, case, "original-card"))
        rows.append(await _evaluate(engine, clarified_case(case), "clarified-card"))
    report = {
        "trial": "everything-tracking-card-clarity",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": len(cases),
        "design": {
            "same_resources": True,
            "same_expected_labels": True,
            "only_change": "human-authored watch_for and questions boundaries",
            "variants": ["expected_change", "ambiguous_state"],
        },
        "arms": {
            arm: _summary([row for row in rows if row["arm"] == arm])
            for arm in ("original-card", "clarified-card")
        },
        "rows": rows,
        "limitations": [
            "The clarification is a counterfactual human edit, not an automatically generated card policy.",
            "The fixture and labels are synthetic; this tests context sensitivity, not enterprise correctness.",
            "A successful clarification does not prove every card can be repaired with two sentences.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--typesafe-key-file", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.repeats < 1:
        raise SystemExit("--repeats must be positive")
    report = asyncio.run(run_trial(args))
    print(json.dumps(report["arms"], indent=2))


if __name__ == "__main__":
    main()
