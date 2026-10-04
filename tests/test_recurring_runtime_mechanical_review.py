from __future__ import annotations

from copy import deepcopy

from evaluations.recurring_runtime_mechanical_review import (
    EXPECTED,
    _arithmetic,
    _primary,
    audit_report,
)
from evaluations.recurring_runtime_transfer_cases import cases


def _submission(company, period):
    outcome, recipient = EXPECTED[company["id"]][period["id"]]
    arithmetic = _arithmetic(company, period)
    submission = {
        "status": "blocked" if outcome == "insufficient_data" else "complete",
        "outcome": outcome,
        "recipients": [] if recipient is None else [recipient],
        "narrative": "Independent test report.",
        "analyses": [],
    }
    if arithmetic["complete"]:
        comparison = _primary(company, period).analytical_comparisons[0]
        submission["analyses"] = [{
            "status": "complete",
            "metric": arithmetic["metric"],
            "unit": arithmetic["unit"],
            "dimension": arithmetic["dimension"],
            "baseline": arithmetic["baseline"],
            "current": arithmetic["current"],
            "delta": arithmetic["delta"],
            "contributions": [
                {"segment": key, "contribution": value}
                for key, value in arithmetic["contributions"].items()
            ],
            "query_refs": arithmetic["query_refs"],
            "comparison": {
                "definition": arithmetic["definition"],
                "population": arithmetic["population"],
                **arithmetic["periods"],
            },
            "source_key": comparison.key,
            "comparison_key": comparison.key,
        }]
    return submission


def _valid_report():
    companies = cases()
    rows = []
    for company in companies:
        runs = []
        for period in company["periods"]:
            if period["split"] != "holdout":
                continue
            runs.append({
                "period": period["id"],
                "submission": _submission(company, period),
                "card_digest": "same-card",
                "catalog_digest": "same-catalog",
                "analysis_input_digest": "same-analysis",
                "replay_exact_no_calls": True,
            })
        for arm in ("baseline", "signalweave"):
            rows.append({"company": company["id"], "arm": arm, "runs": deepcopy(runs)})
    return {
        "results": rows,
        "usage": {"cost_status": "complete"},
        "protocol_checks": {
            "no_foreign_tools": True,
            "paired_catalog_and_analysis": True,
        },
        "jev_attempts": 1,
    }, companies


def test_mechanical_review_recomputes_a_valid_transfer_artifact():
    report, companies = _valid_report()

    result = audit_report(report, companies)

    assert result["passed"] is True
    assert result["checked_runs"] == 24
    assert result["independent_of_trial_score"] is True


def test_mechanical_review_rejects_mutated_submission_even_if_trial_score_lies():
    report, companies = _valid_report()
    target = next(
        run
        for row in report["results"]
        if row["company"] == "lattice-energy" and row["arm"] == "signalweave"
        for run in row["runs"]
        if run["period"] == "p06"
    )
    target["submission"]["outcome"] = "notify"
    target["submission"]["recipients"] = ["commercial-operations"]
    target["score"] = {"passed": True}

    result = audit_report(report, companies)

    assert result["passed"] is False
    assert any(error.startswith("outcome:") for error in result["errors"])
    assert all("score" not in error for error in result["errors"])
