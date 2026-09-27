"""Independently review a real-local-Superset runtime shadow report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def review(report: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    require(report.get("trial") == "local-superset-runtime-shadow", "wrong trial")
    require(report.get("real_local_superset_transport") is True, "not a real local Superset run")
    require(report.get("synthetic_typesafe_transport") is True, "TypeSafe transport was not marked synthetic")
    require(report.get("live_jev_semantics_proven") is False, "report overclaims live Jev semantics")
    require(report.get("managed_hosting_proven") is False, "report overclaims managed hosting")

    discovery = report.get("discovery") or {}
    require(int(discovery.get("match_count", 0)) >= 1, "discovery returned no candidates")
    require(str(discovery.get("selected_ref", "")).startswith("superset|dashboard:"), "selected source is not a dashboard")

    onboarding = report.get("onboarding") or {}
    approval = report.get("approval") or {}
    evaluation = report.get("evaluation") or {}
    receipt = report.get("receipt") or {}
    provider = report.get("provider") or {}
    chart_summary = evaluation.get("chart_summary") or {}

    require(onboarding.get("status") == "ready_for_approval", "onboarding was not reviewable")
    require(approval.get("status") == "approved", "approval did not pass")
    require(evaluation.get("evaluator") == "jev-latest", "result was not Jev-evaluated")
    require(int(evaluation.get("charts", chart_summary.get("charts", 0))) > 0, "no chart shape reached the result")
    require(int(chart_summary.get("charts", 0)) > 0, "no chart shape reached the result")
    require(int(evaluation.get("observation_count", 0)) > 0, "no normalized observations reached the result")
    require(int(evaluation.get("evidence_count", 0)) > 0, "no evidence reached the result")
    require(int(evaluation.get("jev_calls_for_evaluation", 0)) > 0, "evaluation made no Jev-shaped call")
    require(receipt.get("status") == "delivery_disabled", "delivery was enabled")
    require(receipt.get("delivery_enabled") is False, "delivery-enabled receipt was reported")
    require(receipt.get("replayed") is True, "replay was not observed")
    require(int(provider.get("requests_for_evaluation", 0)) > 0, "evaluation did not cross the provider")
    require(int(provider.get("requests_for_replay", 0)) == 0, "replay contacted the provider")
    paths = provider.get("request_path_counts") or {}
    require(any(str(path).endswith("/data/") for path in paths), "no saved chart-data path was observed")
    scope = provider.get("dashboard_scope") or {}
    require(
        all(isinstance(scope.get(key), int) for key in ("dashboard_scoped_requests", "chart_query_fallbacks")),
        "dashboard scope telemetry is missing",
    )
    if int(scope.get("chart_query_fallbacks", 0)) > 0:
        require(
            isinstance(provider.get("dashboard_scope_warning"), str)
            and bool(provider["dashboard_scope_warning"]),
            "unscoped chart-query fallback was not disclosed",
        )

    checks = report.get("checks") or {}
    require(bool(checks) and all(checks.values()), "producer checks did not all pass")
    require(report.get("passed") is True, "producer did not report pass")
    require(
        set(report.get("not_proven") or {})
        >= {
            "live Jev semantic accuracy or business usefulness",
            "managed SignalWeave hosting",
        },
        "explicit non-claims are missing",
    )
    return {
        "review": "local-superset-runtime-shadow-independent",
        "passed": not failures,
        "failures": failures,
        "checks_recomputed": len(checks),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    result = review(report)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
