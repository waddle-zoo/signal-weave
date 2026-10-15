"""Small opt-in qualification run for the independent owner reviewer.

This is a transport qualification check, not a policy benchmark.  Each case is
sent once to the saved-login Codex/Luna reviewer, with its expected disposition
kept outside the reviewer payload.  The output directory is exclusive so an
interrupted run cannot be mistaken for a complete one.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from pathlib import Path
from typing import Any

from evaluations.bootstrap_agent_trial import Audit, RequestBudget, canonical, digest
from evaluations.bootstrap_owner_review import (
    REVIEW_INSTRUCTIONS,
    OwnerReview,
    review_owner_artifact,
)


def _write_exclusive(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        if isinstance(value, str):
            stream.write(value)
        else:
            stream.write(canonical(value))
        stream.write("\n")


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _audited_openai_attempts(events: list[dict[str, Any]]) -> int:
    """Count actual saved-Codex invocations, independent of legacy budgets."""
    return sum(
        event.get("kind") == "api.request" and event.get("provider") == "openai"
        for event in events
    )


def _source_context() -> dict[str, Any]:
    return {
        "catalog": [{
            "ref": "public_metrics|conversion_rates",
            "adapter": "public_metrics",
            "resource": "conversion_rates",
            "kind": "metric",
            "title": "Conversion rates",
            "description": "Publicly documented conversion-rate comparison.",
            "contract": {
                "domain": "commerce",
                "scope": "weekly conversion rates",
                "population": "eligible customer sessions",
                "grain": "week",
                "required_comparison_keys": ["conversion_previous_period"],
                "source_status": "healthy",
                "authorized": True,
            },
        }],
        "inspected_sources": [{
            "ref": "public_metrics|conversion_rates",
            "adapter": "public_metrics",
            "resource": "conversion_rates",
            "kind": "metric",
            "title": "Conversion rates",
            "description": "Publicly documented conversion-rate comparison.",
            "contract": {
                "domain": "commerce",
                "scope": "weekly conversion rates",
                "population": "eligible customer sessions",
                "grain": "week",
                "required_comparison_keys": ["conversion_previous_period"],
                "source_status": "healthy",
                "authorized": True,
            },
            "analytical_comparisons": [{
                "key": "conversion_previous_period",
                "metric": "conversion_rate",
                "definition": "Current weekly conversion rate versus the previous week.",
                "population": "eligible customer sessions",
                "unit": "rate",
                "dimension": "all eligible sessions",
                "kind": "rate",
                "comparison_window": "previous_period",
            }],
        }],
        "current_period": {"period_id": "current-week", "as_of": "2026-10-03"},
    }


def _card(*, guidance: str, route_outcome: str = "notify",
          destination: str = "operations", numeric_conditions: list[dict] | None = None,
            comparison_keys: list[str] | None = None) -> dict[str, Any]:
    return {
        "title": "Conversion monitoring",
        "what_to_watch": "Weekly conversion rate movement",
        "why_watch": "Protect the documented customer conversion process.",
        "watch_for": ["A material conversion-rate movement"],
        "questions": [],
        "evidence_requirements": {},
        "numeric_conditions": numeric_conditions or [],
        "decision_guidance": guidance,
        "follow_up_guidance": "Review the cited comparison before changing the policy.",
        "comparison_windows": ["previous_period"],
        "delivery_methods": [{
            "key": destination,
            "label": destination.title(),
            "outcome": route_outcome,
            "destination": f"route://{destination}",
        }],
        "sources": [{
            "key": "conversion",
            "adapter": "public_metrics",
            "resource": "conversion_rates",
            "required_comparison_keys": (
                ["conversion_previous_period"] if comparison_keys is None else comparison_keys
            ),
        }],
    }


def qualification_cases() -> list[dict[str, Any]]:
    """Return generic controls; expected values never enter the review payload."""
    public = {
        "brief": "Monitor a documented customer conversion metric and route material changes.",
            "glossary": {
            "within_effect": "Aggregate within-group rate change from the inspected symmetric rate comparison.",
            "conversion_rate": "Eligible customer sessions that convert during the week.",
            "gap": "If required evidence is unavailable or ambiguous, use insufficient_data and do not notify.",
            "otherwise": "When no stated trigger is met, ignore and do not notify.",
        },
        "destinations": [
            {"key": "operations", "label": "Operations", "destination": "route://operations"},
            {"key": "analytics", "label": "Analytics", "destination": "route://analytics"},
        ],
    }
    source_context = _source_context()
    within = [{
        "text": "Notify operations when the aggregate within-group rate effect is at most -0.10.",
        "source_key": "conversion",
        "comparison_key": "conversion_previous_period",
        "measurement": "within_effect",
        "unit": "rate",
        "threshold": -0.10,
        "comparator": "<=",
    }]
    return [
        {
            "case_id": "plain_numeric_policy_without_bindings",
            "public": public,
            "owner_answers": {
                "policy": "Notify operations when the signed conversion-rate movement is at most -0.10; otherwise ignore. If required evidence is unavailable or ambiguous, use insufficient_data with no recipient.",
            },
            "artifact": {
                "notes": "Notify operations at a signed conversion-rate movement of -0.10 or lower; otherwise ignore. If required evidence is unavailable or ambiguous, use insufficient_data with no recipient.",
                "card": _card(
                    guidance="Notify operations when the signed conversion-rate movement is at most -0.10; otherwise ignore. If required evidence is unavailable or ambiguous, use insufficient_data with no recipient.",
                    comparison_keys=[],
                    numeric_conditions=[],
                ),
            },
            "source_context": _source_context_empty_comparisons(),
            "expected_approved": True,
            "expectation": "approved",
        },
        {
            "case_id": "valid_within_effect_binding",
            "public": public,
            "owner_answers": {
                "policy": "Notify operations when the aggregate within-group rate effect is at most -0.10; otherwise ignore. If required evidence is unavailable or ambiguous, use insufficient_data with no recipient.",
            },
            "artifact": {
                "notes": "The card uses the inspected conversion comparison and its within-group rate effect; otherwise ignore, with insufficient_data and no recipient when required evidence is unavailable.",
                "card": _card(guidance="Notify operations when the aggregate within-group rate effect is at most -0.10; otherwise ignore. If required evidence is unavailable or ambiguous, use insufficient_data with no recipient.", numeric_conditions=within),
            },
            "source_context": source_context,
            "expected_approved": True,
            "expectation": "approved",
        },
        {
            "case_id": "wrong_recipient",
            "public": public,
            "owner_answers": {
                "policy": "Notify operations when conversion movement is at most -0.10; otherwise ignore. If required evidence is unavailable or ambiguous, use insufficient_data with no recipient.",
            },
            "artifact": {
                "notes": "Notify analytics when conversion movement is at most -0.10; otherwise ignore. If required evidence is unavailable or ambiguous, use insufficient_data with no recipient.",
                "card": _card(
                    guidance="Notify analytics when conversion movement is at most -0.10; otherwise ignore. If required evidence is unavailable or ambiguous, use insufficient_data with no recipient.",
                    destination="analytics",
                    numeric_conditions=[],
                ),
            },
            "source_context": None,
            "expected_approved": False,
            "expectation": "semantic_rejection",
        },
        {
            "case_id": "extra_gate",
            "public": public,
            "owner_answers": {
                "policy": "Notify operations when conversion movement is at most -0.10; otherwise ignore. If required evidence is unavailable or ambiguous, use insufficient_data with no recipient.",
            },
            "artifact": {
                "notes": "Notify operations only when conversion movement is at most -0.10 and revenue also declines; otherwise ignore. If required evidence is unavailable or ambiguous, use insufficient_data with no recipient.",
                "card": _card(
                    guidance="Notify operations when conversion movement is at most -0.10 and revenue also declines; otherwise ignore. If required evidence is unavailable or ambiguous, use insufficient_data with no recipient.",
                    numeric_conditions=[],
                ),
            },
            "source_context": None,
            "expected_approved": False,
            "expectation": "semantic_rejection",
        },
        {
            "case_id": "fabricated_comparison_binding",
            "public": public,
            "owner_answers": {
                        "policy": "Notify operations when the inspected conversion comparison reaches -0.10; otherwise ignore. If required evidence is unavailable or ambiguous, use insufficient_data with no recipient.",
            },
            "artifact": {
                "notes": "The card claims a comparison that is not in the inspected source contract; otherwise ignore, with insufficient_data and no recipient when required evidence is unavailable.",
                "card": _card(
                    guidance="Notify operations when the fabricated comparison reaches -0.10; otherwise ignore. If required evidence is unavailable or ambiguous, use insufficient_data with no recipient.",
                    numeric_conditions=[{
                        "text": "Notify at the fabricated comparison threshold.",
                        "source_key": "conversion",
                        "comparison_key": "future_conversion_comparison",
                        "measurement": "delta",
                        "unit": "rate",
                        "threshold": -0.10,
                        "comparator": "<=",
                    }],
                    comparison_keys=["future_conversion_comparison"],
                ),
            },
            "source_context": source_context,
            "expected_approved": False,
            "expectation": "invalid_review_input",
        },
    ]


def _source_context_empty_comparisons() -> dict[str, Any]:
    context = _source_context()
    context["catalog"][0]["contract"]["required_comparison_keys"] = []
    context["inspected_sources"][0]["contract"]["required_comparison_keys"] = []
    context["inspected_sources"][0]["analytical_comparisons"] = []
    return context


def _passed(case: dict[str, Any], result: dict[str, Any]) -> bool:
    expectation = case["expectation"]
    episode = result.get("episode") or {}
    review = result.get("review")
    try:
        valid_review = OwnerReview.model_validate(review)
    except (TypeError, ValueError):
        valid_review = None
    clean_completion = (
        episode.get("status") == "complete"
        and not episode.get("error")
        and type(episode.get("exit_code")) is int
        and episode["exit_code"] == 0
        and episode.get("foreign_tools") == []
    )
    if expectation == "approved":
        return bool(clean_completion and result.get("approved") is True
                    and valid_review is not None and valid_review.approved is True)
    if expectation == "semantic_rejection":
        return bool(clean_completion and result.get("approved") is False
                    and valid_review is not None and valid_review.approved is False)
    return bool(
        expectation == "invalid_review_input"
        and result.get("approved") is False
        and episode.get("error") == "invalid_review_input"
        and episode.get("tool_calls") == 0
        and result.get("review") is None
    )


async def run_qualification(output: Path) -> dict[str, Any]:
    """Run the bounded live qualification; caller must have created no output path."""
    cases = qualification_cases()
    output.mkdir(parents=True, exist_ok=False)
    source_root = Path(__file__).resolve().parents[1]
    source_files = {
        str(path.relative_to(source_root)): _file_digest(path)
        for path in (
            Path(__file__).resolve(),
            source_root / "evaluations" / "bootstrap_owner_review.py",
            source_root / "evaluations" / "bootstrap_agent_trial.py",
        )
    }
    input_digests = {
        case["case_id"]: digest({
            "public": case["public"], "owner_answers": case["owner_answers"],
            "artifact": case["artifact"], "source_context": case["source_context"],
        })
        for case in cases
    }
    _write_exclusive(output / "manifest.json", {
        "runner": "owner_review_qualification",
        "model": "gpt-5.6-luna",
        "case_ids": [case["case_id"] for case in cases],
        "attempt_limit": len(cases),
        "retry_policy": "none",
        "expectations_excluded_from_reviewer": True,
        "instructions_digest": digest(REVIEW_INSTRUCTIONS),
        "source_files": source_files,
        "input_digests": input_digests,
    })
    budget = RequestBudget(len(cases))
    rows = []
    audited_attempts = 0
    for case in cases:
        case_dir = output / case["case_id"]
        case_dir.mkdir()
        reviewer_input = {
            "public": case["public"],
            "owner_answers": case["owner_answers"],
            "artifact": case["artifact"],
            "source_context": case["source_context"],
        }
        _write_exclusive(case_dir / "input.json", reviewer_input)
        audit = Audit(path=case_dir / "trace.jsonl", episode=case["case_id"])
        result = await review_owner_artifact(
            public=case["public"], owner_answers=case["owner_answers"],
            artifact=case["artifact"], source_context=case["source_context"],
            audit=audit, budget=budget,
        )
        case_audited_attempts = _audited_openai_attempts(audit.events)
        audited_attempts += case_audited_attempts
        row = {
            "case_id": case["case_id"],
            "expected_approved": case["expected_approved"],
            "actual_approved": result["approved"],
            "expectation": case["expectation"],
            "passed": _passed(case, result),
            "result": result,
            "input_digest": digest(reviewer_input),
            "trace_event_count": len(audit.events),
            "audited_openai_attempts": case_audited_attempts,
            "budget_claims": budget.used,
        }
        _write_exclusive(case_dir / "result.json", row)
        rows.append(row)
    summary = {
        "runner": "owner_review_qualification",
        "model": "gpt-5.6-luna",
        "attempt_limit": len(cases),
        "attempts_used": audited_attempts,
        "budget_claims_used": budget.used,
        "all_passed": all(row["passed"] for row in rows),
        "cases": rows,
    }
    _write_exclusive(output / "summary.json", summary)
    return summary


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--live", action="store_true", help="Required: use the saved-login Codex/Luna transport.")
    result.add_argument("--output", type=Path, default=Path("artifacts/owner-review-qualification"))
    return result


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if not args.live:
        raise SystemExit("Refusing to run: pass --live explicitly.")
    if args.output.exists():
        raise SystemExit(f"Output already exists; choose a new path: {args.output}")
    asyncio.run(run_qualification(args.output))


if __name__ == "__main__":
    main()
