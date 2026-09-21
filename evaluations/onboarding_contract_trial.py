"""Fixture-backed exploration of generalized insight-card onboarding.

This is intentionally not a Jev accuracy benchmark.  The fixture supplies
opaque, deterministic Jev scores so the trial can isolate SignalWeave's
candidate, authorization, coverage, and human-review contracts across messy
enterprise shapes.  A live Jev replay is a later step described in the
exploration document.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from signalweave.models import (
    CatalogSearchPage,
    InsightCard,
    PrincipalContext,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.onboarding import InsightAuthoringService
from signalweave.retrieval import resource_ref
from signalweave.sources import SourceRegistry

try:
    from evaluations.onboarding_readiness import assess_readiness
except ModuleNotFoundError:  # Running the file directly from the evaluations directory.
    from onboarding_readiness import assess_readiness

DEFAULT_CASES = Path(__file__).parent / "data" / "onboarding-scenarios.json"


def _descriptor(raw: dict[str, Any]) -> ResourceDescriptor:
    related_refs = raw.get("related_refs", [])
    metadata = dict(raw.get("metadata", {}))
    if related_refs:
        metadata["related_refs"] = related_refs
    return ResourceDescriptor(
        adapter=raw["adapter"],
        resource=raw["resource"],
        kind=raw["kind"],
        title=raw["title"],
        description=raw.get("description", ""),
        metadata=metadata,
        contract=ResourceContract(
            tenant_id=raw.get("tenant_id", "default"),
            domain=raw.get("domain", "unknown"),
            source_status=raw.get("source_status", "healthy"),
            authorized=bool(raw.get("authorized", True)),
            lineage=related_refs,
            roles=[str(role) for role in raw.get("roles", [])],
        ),
    )


class ScenarioAdapter:
    """Adapter double that can prove bounded search without a full catalog scan."""

    def __init__(
        self,
        name: str,
        resources: list[ResourceDescriptor],
        *,
        server_search: bool,
        total_count: int,
        has_more: bool,
    ) -> None:
        self.name = name
        self.resources = resources
        self.server_search = server_search
        self.total_count = total_count
        self.has_more = has_more
        self.list_called = False
        self.search_called = False
        if not server_search:
            # Hide the optional protocol method so SourceRegistry exercises its
            # explicit local-scan fallback for this scenario.
            self.search_resources = None  # type: ignore[method-assign]

    async def list_resources(self) -> list[ResourceDescriptor]:
        self.list_called = True
        if self.server_search:
            raise AssertionError(f"{self.name} must use bounded server search")
        return list(self.resources)

    async def search_resources(
        self, query: str, *, limit: int, cursor: str | None = None
    ) -> CatalogSearchPage:
        del query, cursor
        self.search_called = True
        if not self.server_search:
            raise AssertionError(f"{self.name} should use local fallback in this case")
        return CatalogSearchPage(
            resources=self.resources[:limit],
            total_count=self.total_count,
            has_more=self.has_more,
            next_cursor="scenario-next" if self.has_more else None,
            provider=f"scenario-{self.name}-index",
            strategy="server-search",
        )

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        return ResourceSnapshot(
            source_key=source.key,
            adapter=source.adapter,
            resource=source.resource,
            title=source.label,
        )


class ScenarioJev:
    """Deterministic typed-judgment stand-in; no heuristic fallback is used."""

    name = "jev-exploration-fixture"

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    async def rank_resources(
        self, goal: str, resources: list[ResourceDescriptor]
    ) -> dict[str, float]:
        del goal
        return {
            resource_ref(resource): self.scores.get(resource_ref(resource), 0.0)
            for resource in resources
        }


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    domain: str
    company_shape: str
    candidate_count: int
    returned_refs: list[str]
    recommended_refs: list[str]
    expected_relevant_refs: list[str]
    expected_recommended_refs: list[str]
    relevant_recall: float
    recommended_precision: float
    recommended_recall: float
    review_status: str
    expected_review_status: str
    no_match: bool
    expected_no_match: bool
    truncated: bool
    tenant_leaks: list[str]
    warnings: list[str]
    failures: list[str]
    passed: bool
    readiness_status: str
    readiness_codes: list[str]
    expected_readiness_codes: list[str]
    missing_readiness_codes: list[str]
    unexpected_readiness_codes: list[str]
    readiness_passed: bool
    role_labels_checked: int
    role_mismatches: list[str]
    safe: bool
    evaluator: str

    def as_json(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "domain": self.domain,
            "company_shape": self.company_shape,
            "candidate_count": self.candidate_count,
            "returned_refs": self.returned_refs,
            "recommended_refs": self.recommended_refs,
            "expected_relevant_refs": self.expected_relevant_refs,
            "expected_recommended_refs": self.expected_recommended_refs,
            "relevant_recall": self.relevant_recall,
            "recommended_precision": self.recommended_precision,
            "recommended_recall": self.recommended_recall,
            "review_status": self.review_status,
            "expected_review_status": self.expected_review_status,
            "no_match": self.no_match,
            "expected_no_match": self.expected_no_match,
            "truncated": self.truncated,
            "tenant_leaks": self.tenant_leaks,
            "warnings": self.warnings,
            "failures": self.failures,
            "passed": self.passed,
            "readiness_status": self.readiness_status,
            "readiness_codes": self.readiness_codes,
            "expected_readiness_codes": self.expected_readiness_codes,
            "missing_readiness_codes": self.missing_readiness_codes,
            "unexpected_readiness_codes": self.unexpected_readiness_codes,
            "readiness_passed": self.readiness_passed,
            "role_labels_checked": self.role_labels_checked,
            "role_mismatches": self.role_mismatches,
            "safe": self.safe,
            "evaluator": self.evaluator,
        }


def _source_ref(raw_ref: str, descriptors: dict[str, ResourceDescriptor]) -> SourceRef:
    descriptor = descriptors[raw_ref]
    key = raw_ref.replace("|", "-").replace(":", "-")
    return SourceRef(
        key=key,
        adapter=descriptor.adapter,
        resource=descriptor.resource,
        label=descriptor.title,
    )


async def run_scenario(
    scenario: dict[str, Any], *, judger: Any | None = None, evaluator: str = "fixture-jev"
) -> ScenarioResult:
    tenant_id = scenario["principal"]["tenant_id"]
    descriptors: dict[str, ResourceDescriptor] = {}
    for raw in scenario["resources"]:
        descriptor = _descriptor(raw)
        ref = resource_ref(descriptor)
        # Native IDs can collide across tenants.  Keep the caller-visible
        # descriptor for seed construction while the registry still receives
        # both records and must filter the decoy before Jev sees it.
        if ref not in descriptors or descriptor.contract.tenant_id == tenant_id:
            descriptors[ref] = descriptor
    grouped: dict[str, list[ResourceDescriptor]] = {}
    for raw in scenario["resources"]:
        descriptor = _descriptor(raw)
        grouped.setdefault(descriptor.adapter, []).append(descriptor)

    adapters = []
    server_search_only = bool(
        scenario.get("server_search_only", scenario["expected"].get("server_search_only", False))
    )
    for adapter_name, resources in grouped.items():
        adapters.append(
            ScenarioAdapter(
                adapter_name,
                resources,
                server_search=server_search_only,
                total_count=int(scenario.get("catalog_total_count", len(resources))),
                has_more=bool(scenario.get("catalog_has_more", False)),
            )
        )

    registry = SourceRegistry(adapters, authorized_tenants={tenant_id})
    active_judger = judger or ScenarioJev(scenario["jev_scores"])
    service = InsightAuthoringService(
        registry=registry,
        engine=SimpleNamespace(judger=active_judger),
        max_candidates=40,
        recommendation_threshold=0.60,
        principal=PrincipalContext(
            principal_id=scenario["principal"]["principal_id"],
            tenant_id=tenant_id,
        ),
    )
    discovery = await service.discover(scenario["goal"], limit=10)

    seed_refs = [ref for ref in scenario.get("seeds", []) if ref in descriptors]
    card = InsightCard(
        id=f"exploration-{scenario['scenario_id']}",
        title=scenario["goal"][:200],
        what_to_watch=scenario["goal"],
        why_watch=scenario["why_watch"],
        watch_for=scenario.get("watch_for", []),
        questions=scenario.get("questions", []),
        sources=[_source_ref(ref, descriptors) for ref in seed_refs],
    )
    review = InsightAuthoringService.build_onboarding_review(card, discovery)
    readiness = assess_readiness(
        card,
        discovery,
        review,
        principal_tenant=tenant_id,
    )

    returned_refs = [match.ref for match in discovery.matches]
    recommended_refs = [match.ref for match in discovery.matches if match.recommended]
    expected = scenario["expected"]
    expected_relevant = list(expected.get("relevant", []))
    expected_recommended = list(expected.get("recommended", []))
    returned_set = set(returned_refs)
    recommended_set = set(recommended_refs)
    expected_relevant_set = set(expected_relevant)
    expected_recommended_set = set(expected_recommended)
    relevant_recall = (
        len(expected_relevant_set & returned_set) / len(expected_relevant_set)
        if expected_relevant_set
        else 1.0
    )
    recommended_precision = (
        len(recommended_set & expected_recommended_set) / len(recommended_set)
        if recommended_set
        else (1.0 if not expected_recommended_set else 0.0)
    )
    recommended_recall = (
        len(recommended_set & expected_recommended_set) / len(expected_recommended_set)
        if expected_recommended_set
        else 1.0
    )
    tenant_leaks = [
        match.ref for match in discovery.matches if match.contract.tenant_id != tenant_id
    ]
    governed_roles = {
        _resource_ref(raw): {str(role).strip().lower() for role in raw.get("roles", [])}
        for raw in scenario["resources"]
        if raw.get("roles")
        and raw.get("tenant_id", "default") == tenant_id
        and raw.get("authorized", True)
    }
    role_mismatches = [
        match.ref
        for match in discovery.matches
        if match.ref in governed_roles
        and match.suggested_role not in governed_roles[match.ref]
    ]
    role_labels_checked = sum(match.ref in governed_roles for match in discovery.matches)
    failures: list[str] = []
    if relevant_recall < 1.0:
        failures.append("required candidate omitted")
    if expected_recommended_set and recommended_set != expected_recommended_set:
        failures.append("recommended candidate set differs")
    if tenant_leaks:
        failures.append("wrong-tenant candidate returned")
    if review.status != expected.get("review", "needs_human_input"):
        failures.append("human-review gate differs")
    if discovery.no_match != bool(expected.get("no_match", False)):
        failures.append("no-match decision differs")
    if expected.get("requires_truncation_warning") and not discovery.truncated:
        failures.append("catalog truncation is not visible")
    if expected.get("forbid_tenant_leaks") and tenant_leaks:
        failures.append("tenant isolation failed")
    if role_mismatches:
        failures.append("governed role disagreement")
    expected_readiness_codes = set(expected.get("blockers", []))
    readiness_codes = set(readiness.blocker_codes)
    missing_readiness_codes = sorted(expected_readiness_codes - readiness_codes)
    optional_readiness_codes = set(expected.get("optional_blockers", []))
    unexpected_readiness_codes = sorted(
        readiness_codes
        - expected_readiness_codes
        - optional_readiness_codes
        - {"delivery-policy-missing"}
    )
    readiness_passed = not missing_readiness_codes and not unexpected_readiness_codes
    safe = (
        relevant_recall == 1.0
        and not tenant_leaks
        and not role_mismatches
        and review.status == expected.get("review", "needs_human_input")
        and discovery.no_match == bool(expected.get("no_match", False))
        and (
            not expected.get("requires_truncation_warning") or discovery.truncated
        )
        and (
            (
                bool(expected.get("blockers"))
                and readiness.status.value != "ready_for_approval"
            )
            or (
                not expected.get("blockers")
                and readiness.status.value == "ready_for_approval"
            )
        )
    )
    return ScenarioResult(
        scenario_id=scenario["scenario_id"],
        domain=scenario["domain"],
        company_shape=scenario["company_shape"],
        candidate_count=discovery.candidate_count,
        returned_refs=returned_refs,
        recommended_refs=recommended_refs,
        expected_relevant_refs=expected_relevant,
        expected_recommended_refs=expected_recommended,
        relevant_recall=relevant_recall,
        recommended_precision=recommended_precision,
        recommended_recall=recommended_recall,
        review_status=review.status,
        expected_review_status=expected.get("review", "needs_human_input"),
        no_match=discovery.no_match,
        expected_no_match=bool(expected.get("no_match", False)),
        truncated=discovery.truncated,
        tenant_leaks=tenant_leaks,
        warnings=discovery.warnings + review.warnings,
        failures=failures,
        passed=not failures,
        readiness_status=readiness.status.value,
        readiness_codes=sorted(readiness_codes),
        expected_readiness_codes=sorted(expected_readiness_codes),
        missing_readiness_codes=missing_readiness_codes,
        unexpected_readiness_codes=unexpected_readiness_codes,
        readiness_passed=readiness_passed,
        role_labels_checked=role_labels_checked,
        role_mismatches=role_mismatches,
        safe=safe,
        evaluator=evaluator,
    )


def _resource_ref(raw: dict[str, Any]) -> str:
    return f"{raw['adapter']}|{raw['resource']}"


async def run_trial(
    path: Path = DEFAULT_CASES, *, judger: Any | None = None, evaluator: str = "fixture-jev"
) -> list[ScenarioResult]:
    scenarios = json.loads(path.read_text())
    return [
        await run_scenario(scenario, judger=judger, evaluator=evaluator) for scenario in scenarios
    ]


def render_markdown(results: list[ScenarioResult]) -> str:
    passed = sum(result.passed for result in results)
    readiness_passed = sum(result.readiness_passed for result in results)
    safe = sum(result.safe for result in results)
    recall = sum(result.relevant_recall for result in results) / len(results)
    exact_recommendations = sum(
        set(result.recommended_refs) == set(result.expected_recommended_refs) for result in results
    )
    role_labels_checked = sum(result.role_labels_checked for result in results)
    role_mismatches = sum(bool(result.role_mismatches) for result in results)
    lines = [
        "# Enterprise onboarding contract trial",
        "",
        f"Evaluator: {results[0].evaluator if results else 'unknown'}.",
        "",
        f"- Scenarios: {len(results)}",
        f"- Contract passes: {passed}/{len(results)}",
        f"- Prototype readiness gates satisfied: {readiness_passed}/{len(results)}",
        f"- Safe onboarding outcomes: {safe}/{len(results)}",
        f"- Mean required-candidate recall: {recall:.2f}",
        f"- Exact recommended sets: {exact_recommendations}/{len(results)}",
        f"- Wrong-tenant candidate leaks: {sum(bool(result.tenant_leaks) for result in results)}",
        f"- Governed role labels checked: {role_labels_checked}",
        f"- Governed role disagreements: {role_mismatches}",
        "",
        "| Scenario | Domain | Recall | Recommended | Current review | Prototype readiness | Safe | Exact result | Failures |",
        "| --- | --- | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        recommendation = f"{result.recommended_recall:.2f}/{result.recommended_precision:.2f}"
        failures = ", ".join(result.failures) or "—"
        lines.append(
            f"| {result.scenario_id} | {result.domain} | {result.relevant_recall:.2f} | "
            f"{recommendation} | {result.review_status} | "
            f"{result.readiness_status} ({','.join(result.readiness_codes) or 'none'}) | "
            f"{'PASS' if result.safe else 'FAIL'} | {'PASS' if result.passed else 'FAIL'} | {failures} |"
        )
    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--evaluator", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--typesafe-key-file", type=Path)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    judger = None
    evaluator = "fixture-jev"
    if args.evaluator == "live":
        from signalweave.typesafe_adapter import JevJudger, load_api_key

        key = load_api_key(str(args.typesafe_key_file) if args.typesafe_key_file else None)
        if not key:
            raise SystemExit(
                "live onboarding replay requires TYPESAFE_API_KEY or --typesafe-key-file"
            )
        judger = JevJudger(api_key=key, timeout=60)
        evaluator = "jev-live"
    results = asyncio.run(run_trial(args.cases, judger=judger, evaluator=evaluator))
    if args.format == "json":
        rendered = json.dumps([result.as_json() for result in results], indent=2) + "\n"
    else:
        rendered = render_markdown(results)
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
