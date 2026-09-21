"""Independent adversarial review of the generalized onboarding matrix.

This reviewer intentionally does not reuse the readiness rule implementation to
decide whether the matrix has coverage. It audits three separate claims:

* correctness: required candidates are retained and recommendations do not
  silently expand beyond the labeled relevant set;
* scope: tenant, authorization, and catalog-completeness boundaries are
  visible;
* generalization: the fixtures exercise multiple enterprise shapes and the
  production onboarding layer contains no source- or scenario-specific branch.

The labels are synthetic research fixtures, not a production accuracy estimate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

try:
    from evaluations.onboarding_contract_trial import DEFAULT_CASES, ScenarioResult, run_trial
except ModuleNotFoundError:  # Running the file directly from the evaluations directory.
    from onboarding_contract_trial import DEFAULT_CASES, ScenarioResult, run_trial

ROOT = Path(__file__).parents[1]
PRODUCTION_ONBOARDING = ROOT / "src" / "signalweave" / "onboarding.py"


@dataclass(frozen=True)
class AuditFinding:
    reviewer: Literal["correctness", "scope", "generalization"]
    severity: Literal["error", "warning"]
    message: str
    scenario_id: str | None = None


@dataclass(frozen=True)
class AuditReport:
    evaluator: str
    scenario_count: int
    findings: tuple[AuditFinding, ...]

    @property
    def passed(self) -> bool:
        return not any(finding.severity == "error" for finding in self.findings)

    def as_json(self) -> dict[str, Any]:
        return {
            "evaluator": self.evaluator,
            "scenario_count": self.scenario_count,
            "passed": self.passed,
            "findings": [
                {
                    "reviewer": finding.reviewer,
                    "severity": finding.severity,
                    "message": finding.message,
                    "scenario_id": finding.scenario_id,
                }
                for finding in self.findings
            ],
        }


def audit_matrix(
    scenarios: list[dict[str, Any]], results: list[ScenarioResult], *, evaluator: str
) -> AuditReport:
    findings: list[AuditFinding] = []
    scenarios_by_id = {scenario["scenario_id"]: scenario for scenario in scenarios}

    def add(
        reviewer: Literal["correctness", "scope", "generalization"],
        message: str,
        *,
        scenario_id: str | None = None,
        severity: Literal["error", "warning"] = "error",
    ) -> None:
        findings.append(AuditFinding(reviewer, severity, message, scenario_id))

    for result in results:
        scenario = scenarios_by_id[result.scenario_id]
        expected = scenario["expected"]
        expected_relevant = set(expected.get("relevant", []))
        returned = set(result.returned_refs)
        recommended = set(result.recommended_refs)
        if result.relevant_recall < 1.0:
            add(
                "correctness",
                "a labeled required candidate was omitted from the bounded result",
                scenario_id=result.scenario_id,
            )
        unexpected_recommendations = sorted(recommended - expected_relevant)
        if unexpected_recommendations:
            add(
                "correctness",
                "Jev recommended a candidate outside the labeled relevant set: "
                + ", ".join(unexpected_recommendations),
                scenario_id=result.scenario_id,
                severity=(
                    "warning" if "definition-conflict" in expected.get("blockers", []) else "error"
                ),
            )
        if expected.get("blockers") and result.readiness_status == "ready_for_approval":
            add(
                "correctness",
                "expected onboarding blockers were silently treated as approval-ready",
                scenario_id=result.scenario_id,
            )
        if expected.get("requires_truncation_warning") and not result.truncated:
            add(
                "correctness",
                "the scenario required a completeness warning but the result was not truncated",
                scenario_id=result.scenario_id,
            )
        if result.relevant_recall != 1.0 and not result.truncated:
            add(
                "correctness",
                "candidate recall failed without an explicit coverage warning",
                scenario_id=result.scenario_id,
            )

        principal = scenario["principal"]
        resources: dict[str, list[dict[str, Any]]] = {}
        for resource in scenario["resources"]:
            resources.setdefault(f"{resource['adapter']}|{resource['resource']}", []).append(
                resource
            )
        for ref in returned:
            candidates = resources.get(ref, [])
            if not candidates:
                add(
                    "scope",
                    "returned a reference absent from the scenario catalog",
                    scenario_id=result.scenario_id,
                )
                continue
            if not any(
                resource.get("authorized", True)
                and resource.get("tenant_id", "default") == principal["tenant_id"]
                for resource in candidates
            ):
                add(
                    "scope",
                    "returned a reference with no authorized resource for the principal tenant",
                    scenario_id=result.scenario_id,
                )
        if result.tenant_leaks:
            add(
                "scope",
                "the result reported a tenant leak",
                scenario_id=result.scenario_id,
            )

    required_scenario_keys = {
        "scenario_id",
        "domain",
        "company_shape",
        "goal",
        "why_watch",
        "watch_for",
        "questions",
        "principal",
        "expected",
        "resources",
    }
    for scenario in scenarios:
        missing = sorted(required_scenario_keys - scenario.keys())
        if missing:
            add(
                "generalization",
                "scenario is missing generic onboarding fields: " + ", ".join(missing),
                scenario_id=scenario.get("scenario_id"),
            )
        for resource in scenario.get("resources", []):
            if (
                not {"adapter", "resource", "kind", "title", "tenant_id", "domain"}
                <= resource.keys()
            ):
                add(
                    "generalization",
                    "resource fixture is missing generic adapter metadata",
                    scenario_id=scenario.get("scenario_id"),
                )

    adapters = {
        resource["adapter"] for scenario in scenarios for resource in scenario.get("resources", [])
    }
    domains = {scenario.get("domain") for scenario in scenarios}
    company_shapes = {scenario.get("company_shape") for scenario in scenarios}
    multi_adapter_cases = sum(
        len({resource["adapter"] for resource in scenario.get("resources", [])}) >= 2
        for scenario in scenarios
    )
    if len(adapters) < 6:
        add("generalization", f"only {len(adapters)} adapter types are covered")
    if len(domains) < 8:
        add("generalization", f"only {len(domains)} enterprise domains are covered")
    if len(company_shapes) < 4:
        add("generalization", f"only {len(company_shapes)} company shapes are covered")
    if multi_adapter_cases < 5:
        add("generalization", f"only {multi_adapter_cases} cases compose multiple adapters")

    production_source = PRODUCTION_ONBOARDING.read_text().lower()
    vendor_names = {"superset", "looker", "hex", "trino", "airflow", "tableau"}
    for vendor in sorted(vendor_names):
        if re.search(rf"(?<!\.)\b{vendor}\b", production_source):
            add(
                "generalization",
                f"production onboarding contains a vendor-specific branch or label: {vendor}",
            )
    for scenario in scenarios:
        scenario_id = scenario["scenario_id"].lower()
        if scenario_id in production_source:
            add(
                "generalization",
                "production onboarding contains a fixture-specific scenario identifier",
                scenario_id=scenario["scenario_id"],
            )

    return AuditReport(evaluator=evaluator, scenario_count=len(results), findings=tuple(findings))


def render_markdown(report: AuditReport) -> str:
    lines = [
        "# Adversarial onboarding review",
        "",
        f"Evaluator: {report.evaluator}.",
        f"Scenarios: {report.scenario_count}.",
        f"Result: {'PASS' if report.passed else 'FAIL'}.",
        "",
    ]
    for reviewer in ("correctness", "scope", "generalization"):
        reviewer_findings = [f for f in report.findings if f.reviewer == reviewer]
        reviewer_errors = [f for f in reviewer_findings if f.severity == "error"]
        reviewer_warnings = [f for f in reviewer_findings if f.severity == "warning"]
        reviewer_status = (
            "FAIL" if reviewer_errors else "PASS WITH WARNINGS" if reviewer_warnings else "PASS"
        )
        lines.append(f"- {reviewer}: {reviewer_status}")
        for finding in reviewer_findings:
            suffix = f" ({finding.scenario_id})" if finding.scenario_id else ""
            lines.append(f"  - {finding.severity}: {finding.message}{suffix}")
    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--evaluator", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--typesafe-key-file", type=Path)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    judger = None
    evaluator = "fixture-jev"
    if args.evaluator == "live":
        from signalweave.typesafe_adapter import JevJudger, load_api_key

        key = load_api_key(str(args.typesafe_key_file) if args.typesafe_key_file else None)
        if not key:
            raise SystemExit("live onboarding review requires a TypeSafe API key")
        judger = JevJudger(api_key=key, timeout=60)
        evaluator = "jev-live"
    scenarios = json.loads(args.cases.read_text())
    results = asyncio.run(run_trial(args.cases, judger=judger, evaluator=evaluator))
    report = audit_matrix(scenarios, results, evaluator=evaluator)
    rendered = (
        json.dumps(report.as_json(), indent=2) + "\n"
        if args.format == "json"
        else render_markdown(report)
    )
    print(rendered, end="")
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
