"""Independent mechanical review for a live paired bootstrap comparison.

This is deliberately separate from the runner.  It reconstructs the public
fixture from the recorded digest, recomputes every monitoring score, checks
that both arms really used the same card, and reports which claims the artifact
can support.  It does not call an LLM or Jev and it never silently converts a
failed gate into a positive result.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evaluations.bootstrap_agent_trial import canonical, select_scenarios, write_exclusive
from evaluations.bootstrap_scenarios import build_scenarios, dataset_digest, score_submission


def _fixture_options(config: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {
        "seed": config["seed"],
        "split": config["split"],
    }
    if config.get("connector_profile", False):
        options["connector_profile"] = True
    if config.get("catalog_noise", 0):
        options["catalog_noise"] = config["catalog_noise"]
    return options


def _same(value: Any, expected: Any) -> bool:
    return canonical(value) == canonical(expected)


def _card_statuses(report_path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    treatment_rows = [row for row in rows if row.get("arm") == "luna_signalweave_jev"]
    card_ids = {row.get("card_id") for row in treatment_rows if row.get("card_id")}
    if not card_ids:
        return {"pass": False, "card_ids": [], "reason": "no_treatment_card_id"}
    statuses: dict[str, str] = {}
    missing_files: list[str] = []
    for scenario_id in sorted({row.get("scenario_id") for row in treatment_rows}):
        path = report_path.parent / scenario_id / "luna_signalweave_jev" / "cards.json"
        if not path.exists():
            missing_files.append(str(path))
            continue
        try:
            cards = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            missing_files.append(str(path))
            continue
        for card_id in card_ids:
            card = cards.get(card_id) if isinstance(cards, dict) else None
            if isinstance(card, dict):
                statuses[card_id] = str(card.get("status"))
    bad = sorted(card_id for card_id in card_ids if statuses.get(card_id) != "approved")
    return {
        "pass": not missing_files and not bad,
        "card_ids": sorted(card_ids),
        "statuses": statuses,
        "missing_files": missing_files,
        "not_approved": bad,
    }


def review_report(report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text())
    config = report["config"]
    fixtures = build_scenarios(**_fixture_options(config))
    fixtures = select_scenarios(
        fixtures,
        config.get("selected_scenario_ids"),
        config.get("selected_companies", len(fixtures)),
    )
    fixture_digest = dataset_digest(fixtures)
    rows = [row for row in report.get("rows", []) if row.get("phase") == "monitoring"]
    scenarios = {scenario["scenario_id"]: scenario for scenario in fixtures}
    gates: dict[str, bool] = {}
    findings: list[str] = []

    gates["fixture_digest_matches"] = fixture_digest == config.get("dataset_digest")
    if not gates["fixture_digest_matches"]:
        findings.append("reconstructed fixture digest differs from the measured run")

    gates["report_complete"] = report.get("status") == "complete"
    gates["comparative_eligible"] = report.get("comparative_eligible") is True
    gates["live_jev_observed"] = report.get("live_jev_observed") is True
    gates["budget_not_censored"] = report.get("budget_censored") is not True
    gates["usage_complete"] = all(
        row.get("usage", {}).get("jev", {}).get("unknown_usage_attempts", 0) == 0
        and row.get("usage", {}).get("openai", {}).get("unknown_usage_attempts", 0) == 0
        for row in report.get("rows", [])
        if row.get("phase") == "monitoring"
    )
    gates["foreign_tools_absent"] = all(not row.get("foreign_tools") for row in report.get("rows", []))

    by_arm: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_arm.setdefault(str(row.get("arm")), []).append(row)
    treatment = by_arm.get("luna_signalweave_jev", [])
    baseline = by_arm.get("luna_bi", [])
    gates["paired_denominators"] = bool(treatment and len(treatment) == len(baseline))
    if not gates["paired_denominators"]:
        findings.append("treatment and baseline do not have the same monitoring denominator")

    card_digests: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        key = (str(row.get("scenario_id")), str(row.get("period_id")))
        digest = row.get("shared_card_digest")
        if digest:
            card_digests.setdefault(key, set()).add(str(digest))
    gates["same_card_monitoring"] = bool(card_digests) and all(len(values) == 1 for values in card_digests.values())
    if not gates["same_card_monitoring"]:
        findings.append("monitoring arms did not share one identical non-empty card digest per paired period")

    recomputed: list[dict[str, Any]] = []
    for row in rows:
        scenario = scenarios.get(row.get("scenario_id"))
        if scenario is None:
            recomputed.append({"row": row, "match": False, "reason": "unknown_scenario"})
            continue
        try:
            expected = score_submission(
                scenario,
                row["period_id"],
                row.get("submission") or {},
                inspected_refs=row.get("inspected_refs", []),
                asked_owner_topics=row.get("asked_owner_topics", []),
            )
            match = _same(row.get("score"), expected)
            recomputed.append({"row": row, "match": match, "expected": expected})
        except Exception as error:  # pragma: no cover - defensive review boundary
            recomputed.append({"row": row, "match": False, "reason": type(error).__name__})
    gates["scores_recompute"] = bool(recomputed) and all(item["match"] for item in recomputed)
    if not gates["scores_recompute"]:
        findings.append("at least one stored score differs from an independent recomputation")

    gates["no_unsafe_suppression"] = all(
        not row.get("score", {}).get("unsafe_suppression")
        and not row.get("score", {}).get("unsafe_route")
        for row in rows
    )
    gates["approved_treatment_card"] = _card_statuses(report_path, rows)["pass"]
    if not gates["approved_treatment_card"]:
        findings.append("the recorded treatment card is missing or not approved")

    raw_system_checks: list[bool] = []
    for row in treatment:
        raw = row.get("raw_system_decision")
        scenario = scenarios.get(row.get("scenario_id"))
        label = (scenario or {}).get("private", {}).get("periods", {}).get(row.get("period_id"), {})
        if not isinstance(raw, dict) or not label:
            raw_system_checks.append(False)
            continue
        raw_system_checks.append(
            raw.get("outcome") == label.get("outcome")
            and set(raw.get("recipients", [])) == set(label.get("recipients", []))
            and raw.get("agent_changed_outcome") is False
        )
    gates["raw_jev_routing"] = bool(raw_system_checks) and all(raw_system_checks)
    if not gates["raw_jev_routing"]:
        findings.append("a raw Jev routing decision did not match the declared scenario route")

    push_enabled = bool(config.get("push_gated"))
    skipped = [row for row in treatment if row.get("agent_wakeup_skipped")]
    baseline_skipped = [row for row in baseline if row.get("agent_wakeup_skipped")]
    if push_enabled:
        gates["push_gate_contract"] = (
            not baseline_skipped
            and all(
                row.get("raw_system_decision", {}).get("outcome") == "ignore"
                and row.get("agent_seconds") == 0.0
                and row.get("tool_calls") == 0
                and row.get("score", {}).get("exact") is True
                for row in skipped
            )
            and all(not row.get("agent_wakeup_skipped") for row in treatment if row not in skipped)
        )
        if not gates["push_gate_contract"]:
            findings.append("push-gated rows do not satisfy the complete-ignore/no-agent/exact contract")
    else:
        gates["push_gate_contract"] = True

    def total(arm_rows: list[dict[str, Any]], field: str) -> float:
        return sum(float(row.get(field) or 0.0) for row in arm_rows)

    treatment_warm = total(treatment, "agent_seconds")
    baseline_warm = total(baseline, "agent_seconds")
    treatment_exact = sum(bool(row.get("score", {}).get("exact")) for row in treatment)
    baseline_exact = sum(bool(row.get("score", {}).get("exact")) for row in baseline)
    value_signal = {
        "treatment_exact": treatment_exact,
        "baseline_exact": baseline_exact,
        "treatment_warm_agent_seconds": treatment_warm,
        "baseline_warm_agent_seconds": baseline_warm,
        "warm_agent_seconds_reduction_pct": (
            (baseline_warm - treatment_warm) / baseline_warm * 100 if baseline_warm else None
        ),
        "treatment_agent_wakeups": sum(not row.get("agent_wakeup_skipped") for row in treatment),
        "baseline_agent_wakeups": sum(not row.get("agent_wakeup_skipped") for row in baseline),
        "treatment_source_reads": sum(int(row.get("source_reads") or 0) for row in treatment),
        "baseline_source_reads": sum(int(row.get("source_reads") or 0) for row in baseline),
    }
    integrity_pass = all(gates.values())
    gates["cost_comparison_measured"] = False
    strong_claim = bool(
        integrity_pass
        and len({row.get("scenario_id") for row in rows}) >= 3
        and treatment_exact >= baseline_exact
        and treatment_warm < baseline_warm
        and value_signal["treatment_agent_wakeups"] < value_signal["baseline_agent_wakeups"]
        and gates["cost_comparison_measured"]
    )
    return {
        "review_version": 1,
        "report": str(report_path),
        "integrity_pass": integrity_pass,
        "strong_superiority_claim_allowed": strong_claim,
        "gates": gates,
        "findings": findings,
        "value_signal": value_signal,
        "push_gated": push_enabled,
        "skipped_treatment_rows": [
            {key: row.get(key) for key in ("scenario_id", "period_id", "seconds", "agent_seconds", "tool_calls")}
            for row in skipped
        ],
        "card_review": _card_statuses(report_path, rows),
        "recomputed_rows": [
            {"arm": item["row"].get("arm"), "scenario_id": item["row"].get("scenario_id"),
             "period_id": item["row"].get("period_id"), "match": item["match"]}
            for item in recomputed
        ],
        "interpretation": (
            "Integrity checks pass, but this artifact alone is not evidence of general superiority. "
            "It may show a value signal only when warm work and downstream wakeups are lower; "
            "illustrative token estimates are not measured subscription cost."
            if integrity_pass else
            "Do not use this artifact for a value claim until the failed integrity gates are fixed."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = review_report(args.report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_exclusive(args.output, result)
    print(canonical(result))
    return 0 if result["integrity_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
