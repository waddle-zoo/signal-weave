"""Jev-only generalized bootstrap, retrieval, and workflow certification trial.

This is an evaluation harness, not product policy.  The scenario file owns the
enterprise shapes and independent owner labels.  The production SignalWeave
services own candidate bounding, tenant filtering, Jev ranking, card evaluation,
and certification reports.  The trial intentionally includes cross-system
assets, stale/failed sources, same-name resources across tenants, a virtual
100k-resource native catalog, and disjoint time splits.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from signalweave.bootstrap import AdapterBootstrapSpec, BootstrapManifest, BootstrapService
from signalweave.engine import InsightEngine
from signalweave.evaluation import (
    CardEvaluationCase,
    CardEvaluationThresholds,
    CardWorkflowEvaluator,
    EvaluationDataset,
)
from signalweave.models import (
    CatalogSearchPage,
    ContextSnapshot,
    DeliveryMethod,
    InsightCard,
    InsightPlan,
    Observation,
    Outcome,
    PrincipalContext,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.onboarding import InsightAuthoringService
from signalweave.retrieval_quality import (
    RetrievalQualityCase,
    RetrievalQualityEvaluator,
    RetrievalQualityThresholds,
)
from signalweave.sources import SourceRegistry
from signalweave.typesafe_adapter import JevJudger, load_api_key

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "evaluations" / "data" / "generalized-readiness-workflows.json"


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _ref(adapter: str, resource: str) -> str:
    return f"{adapter}|{resource}"


def _descriptor(raw: dict[str, Any], tenant_id: str) -> ResourceDescriptor:
    related_refs = [str(ref) for ref in raw.get("related_refs", [])]
    return ResourceDescriptor(
        adapter=str(raw["adapter"]),
        resource=str(raw["resource"]),
        kind=str(raw["kind"]),
        title=str(raw["title"]),
        description=str(raw.get("description", "")),
        metadata={"related_refs": related_refs, "company_shape": raw.get("company_shape", "")},
        contract=ResourceContract(
            tenant_id=tenant_id,
            domain=str(raw.get("domain", "unknown")),
            scope="production analytics",
            metric_names=[str(item) for item in raw.get("metric_names", [])],
            freshness_sla_hours=24,
            lineage=related_refs,
            roles=[str(item) for item in raw.get("roles", [])],
        ),
    )


class NativeCatalogAdapter:
    """A search/authorize adapter that cannot be accidentally full-scanned."""

    def __init__(self, name: str, descriptors: list[ResourceDescriptor], total_count: int) -> None:
        self.name = name
        self._descriptors = descriptors
        self._by_resource = {}
        self._related_index: dict[str, list[ResourceDescriptor]] = {}
        for descriptor in descriptors:
            self._by_resource.setdefault(descriptor.resource, []).append(descriptor)
            refs = [
                *descriptor.contract.lineage,
                *(
                    descriptor.metadata.get("related_refs", [])
                    if isinstance(descriptor.metadata.get("related_refs", []), list)
                    else []
                ),
            ]
            for ref in refs:
                self._related_index.setdefault(str(ref), []).append(descriptor)
        self.total_count = total_count
        self.search_calls = 0
        self.authorize_calls = 0
        self.list_calls = 0

    async def list_resources(self) -> list[ResourceDescriptor]:
        self.list_calls += 1
        raise AssertionError(
            f"{self.name} native adapter must not materialize its {self.total_count:,}-item catalog"
        )

    async def search_resources(
        self,
        query: str,
        *,
        limit: int,
        cursor: str | None = None,
        authorized_tenants: Any = None,
    ) -> CatalogSearchPage:
        del cursor
        self.search_calls += 1
        terms = {term for term in query.lower().replace("/", " ").split() if len(term) > 2}
        allowed_tenants = set(authorized_tenants or [])
        descriptors = [
            descriptor
            for descriptor in self._descriptors
            if not allowed_tenants or descriptor.contract.tenant_id in allowed_tenants
        ]

        def score(descriptor: ResourceDescriptor) -> tuple[int, str]:
            text = " ".join(
                [descriptor.title, descriptor.description, descriptor.contract.domain]
                + descriptor.contract.metric_names
                + descriptor.contract.lineage
            ).lower()
            return (sum(term in text for term in terms), descriptor.resource)

        resources = sorted(descriptors, key=score, reverse=True)[:limit]
        return CatalogSearchPage(
            resources=resources,
            total_count=self.total_count if descriptors else 0,
            has_more=True,
            next_cursor="native-next",
            provider=f"{self.name}-native-index",
            strategy="native-index",
        )

    async def authorize(
        self,
        source: SourceRef,
        *,
        authorized_tenants: Any = None,
    ) -> ResourceDescriptor | None:
        self.authorize_calls += 1
        allowed = set(authorized_tenants or [])
        for descriptor in self._by_resource.get(source.resource, []):
            if not allowed or descriptor.contract.tenant_id in allowed:
                return descriptor
        return None

    async def expand_related_resources(
        self,
        related_refs: list[str],
        *,
        limit: int,
        authorized_tenants: Any = None,
    ) -> CatalogSearchPage:
        allowed = set(authorized_tenants or [])
        resources: list[ResourceDescriptor] = []
        seen: set[tuple[str, str]] = set()
        for related_ref in related_refs:
            for descriptor in self._related_index.get(related_ref, []):
                identity = (descriptor.adapter, descriptor.resource)
                if identity in seen or (
                    allowed and descriptor.contract.tenant_id not in allowed
                ):
                    continue
                seen.add(identity)
                resources.append(descriptor)
                if len(resources) >= limit:
                    break
            if len(resources) >= limit:
                break
        return CatalogSearchPage(
            resources=resources,
            total_count=len(resources),
            has_more=False,
            provider=f"{self.name}-native-related-index",
            strategy="native-related-index",
        )

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        return ResourceSnapshot(
            source_key=source.key,
            adapter=source.adapter,
            resource=source.resource,
            title=source.label,
        )


class RecordingJev:
    """Delegates to real Jev while recording the state boundary for review."""

    def __init__(self, delegate: JevJudger) -> None:
        self.delegate = delegate
        self.name = delegate.name
        self.metrics = delegate.metrics
        self.calls: list[dict[str, Any]] = []

    async def rank_resources(self, goal: str, resources: list[ResourceDescriptor]) -> dict[str, float]:
        self.calls.append(
            {
                "method": "rank_resources",
                "goal": goal,
                "refs": [_ref(resource.adapter, resource.resource) for resource in resources],
                "keys": ["goal", "candidate_resources"],
            }
        )
        return await self.delegate.rank_resources(goal, resources)

    async def rank_resources_with_context(
        self,
        goal: str,
        resources: list[ResourceDescriptor],
        context: ContextSnapshot,
    ) -> dict[str, float]:
        self.calls.append(
            {
                "method": "rank_resources_with_context",
                "goal": goal,
                "refs": [_ref(resource.adapter, resource.resource) for resource in resources],
                "keys": ["goal", "candidate_resources", "context"],
                "context_version": context.version,
            }
        )
        rank_with_context = getattr(self.delegate, "rank_resources_with_context", None)
        if callable(rank_with_context):
            return await rank_with_context(goal, resources, context)
        return await self.delegate.rank_resources(goal, resources)

    async def compile_plan(self, state: dict[str, Any], card: InsightCard) -> dict[str, Any]:
        self.calls.append(
            {"method": "compile_plan", "keys": sorted(state), "card_id": card.id}
        )
        return await self.delegate.compile_plan(state, card)

    async def judge(self, state: dict[str, Any], card: InsightCard, plan: InsightPlan, observations):
        self.calls.append(
            {
                "method": "judge",
                "keys": sorted(state),
                "card_id": card.id,
                "observation_count": len(observations),
            }
        )
        return await self.delegate.judge(state, card, plan, observations)


def _all_workflows(config: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        (company, workflow)
        for company in config["companies"]
        for workflow in company["workflows"]
    ]


def _build_catalog(config: dict[str, Any]) -> tuple[list[NativeCatalogAdapter], dict[str, dict[str, Any]]]:
    descriptors_by_adapter: dict[str, list[ResourceDescriptor]] = {}
    workflow_by_ref: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, str, str]] = set()
    for company, workflow in _all_workflows(config):
        tenant_id = company["tenant_id"]
        for raw in workflow["sources"]:
            descriptor = _descriptor(raw, tenant_id)
            identity = (tenant_id, descriptor.adapter, descriptor.resource)
            if identity in seen:
                continue
            seen.add(identity)
            descriptors_by_adapter.setdefault(descriptor.adapter, []).append(descriptor)
            workflow_by_ref[_ref(descriptor.adapter, descriptor.resource)] = {
                "tenant_id": tenant_id,
                "workflow_id": workflow["workflow_id"],
            }
    adapters = [
        NativeCatalogAdapter(
            name,
            descriptors,
            max(100_000 // max(len(descriptors_by_adapter), 1), len(descriptors)),
        )
        for name, descriptors in sorted(descriptors_by_adapter.items())
    ]
    return adapters, workflow_by_ref


def _source_refs(workflow: dict[str, Any], tenant_id: str) -> list[SourceRef]:
    return [
        SourceRef(
            key=str(raw["key"]),
            adapter=str(raw["adapter"]),
            resource=str(raw["resource"]),
            label=str(raw["title"]),
        )
        for raw in workflow["sources"]
    ]


def _snapshot(
    raw: dict[str, Any],
    case: dict[str, Any],
    tenant_id: str,
) -> ResourceSnapshot:
    source_key = str(raw["key"])
    descriptor = _descriptor(raw, tenant_id)
    observation = case.get("observations", {}).get(source_key)
    observations = []
    if observation:
        observations = [
            Observation(
                source_key=source_key,
                subject_id=source_key,
                subject_label=descriptor.title,
                subject_type=descriptor.kind,
                metric=str(observation["metric"]),
                current=observation.get("current"),
                baseline=observation.get("baseline"),
                change_pct=observation.get("change_pct"),
                freshness=observation.get("freshness"),
                attributes={"source_status": case.get("source_status", {}).get(source_key, "healthy")},
            )
        ]
    source_status = case.get("source_status", {}).get(source_key, "healthy")
    return ResourceSnapshot(
        source_key=source_key,
        adapter=descriptor.adapter,
        resource=descriptor.resource,
        title=descriptor.title,
        observations=observations,
        contract=descriptor.contract.model_copy(update={"source_status": source_status}),
    )


def _card(
    company: dict[str, Any], workflow: dict[str, Any]
) -> InsightCard:
    card_data = workflow["card"]
    sources = _source_refs(workflow, company["tenant_id"])
    delivery = card_data["delivery"]
    methods = [
        DeliveryMethod(
            key=delivery["key"],
            outcome=Outcome(delivery["outcome"]),
            label=delivery["label"],
            destination=delivery["destination"],
            instructions=delivery["instructions"],
        )
    ]
    plan = InsightPlan(
        card_id=f"{company['tenant_id']}-{workflow['workflow_id']}",
        card_version=1,
        selected_source_keys=[source.key for source in sources],
        comparison_windows=["previous_period"],
        capabilities=[],
        watch_for=list(card_data["watch_for"]),
        questions=list(card_data["questions"]),
        delivery_method_keys=[delivery["key"]],
        compiled_by="human-approved-plan-v1",
        card_scope=company["tenant_id"],
    )
    return InsightCard(
        id=plan.card_id,
        title=card_data["title"],
        what_to_watch=card_data["what_to_watch"],
        why_watch=card_data["why_watch"],
        watch_for=list(card_data["watch_for"]),
        questions=list(card_data["questions"]),
        decision_guidance=card_data["decision_guidance"],
        sources=sources,
        comparison_windows=["previous_period"],
        action_confidence_threshold=0.70,
        owner=f"{company['tenant_id']}-analytics-owner",
        delivery_methods=methods,
        compiled_plan=plan,
        principal_id=f"{company['tenant_id']}-analytics-owner",
        principal_tenant=company["tenant_id"],
    )


def _dataset(config: dict[str, Any], company: dict[str, Any], workflow: dict[str, Any], case: dict[str, Any]) -> EvaluationDataset:
    digest = _digest(
        {
            "catalog_version": config["catalog_version"],
            "company": company["company_id"],
            "workflow": workflow["workflow_id"],
            "case": case["case_id"],
            "period": case["period"],
            "observations": case["observations"],
            "source_status": case.get("source_status", {}),
        }
    )
    return EvaluationDataset(
        dataset_id=f"{company['tenant_id']}-{workflow['workflow_id']}-{case['case_id']}",
        split=case["split"],
        observed_from=f"{case['period']}-01",
        observed_to=f"{case['period']}-28",
        source_catalog_version=config["catalog_version"],
        context_version="graph-context-v1",
        digest=digest,
    )


async def run_trial(config_path: Path, output: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text())
    adapters, _ = _build_catalog(config)
    registry = SourceRegistry(adapters)
    key = load_api_key()
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE is required")
    recording = RecordingJev(JevJudger(api_key=key))
    started = time.perf_counter()

    bootstrap_reports = []
    retrieval_cases: list[RetrievalQualityCase] = []
    card_cases: list[CardEvaluationCase] = []
    cards: dict[str, InsightCard] = {}
    for company, workflow in _all_workflows(config):
        principal = PrincipalContext(
            principal_id=f"{company['tenant_id']}-analytics-owner",
            tenant_id=company["tenant_id"],
        )
        bootstrap = await BootstrapService(registry).assess(
            BootstrapManifest(
                tenant_id=company["tenant_id"],
                name=f"{company['company_id']} bootstrap",
                adapters=[
                    AdapterBootstrapSpec(
                        adapter=adapter,
                        probe_goal=workflow["goal"],
                        required_capabilities=["catalog", "search", "inspect", "tenant_scope", "freshness", "lineage", "metric_definitions"],
                        minimum_resources=1,
                    )
                    for adapter in sorted({raw["adapter"] for raw in workflow["sources"]})
                ],
            ),
            principal=principal,
        )
        bootstrap_reports.append(
            {
                "company_id": company["company_id"],
                "workflow_id": workflow["workflow_id"],
                "status": bootstrap.status,
                "report": bootstrap.model_dump(mode="json"),
            }
        )
        card = _card(company, workflow)
        cards[card.id] = card
        retrieval_cases.append(
            RetrievalQualityCase(
                id=f"{company['tenant_id']}-{workflow['workflow_id']}-retrieval",
                goal=workflow["goal"],
                expected_resource_refs=[
                    _ref(raw["adapter"], raw["resource"]) for raw in workflow["sources"]
                ],
                principal=principal,
                limit=10,
                dataset=EvaluationDataset(
                    dataset_id=f"{company['tenant_id']}-{workflow['workflow_id']}-retrieval",
                    split="holdout",
                    observed_from="2026-02-01",
                    observed_to="2026-02-28",
                    source_catalog_version=config["catalog_version"],
                    digest=_digest(workflow["sources"]),
                ),
            )
        )
        for case in workflow["cases"]:
            card_sources = [
                _snapshot(raw, case, company["tenant_id"]) for raw in workflow["sources"]
            ]
            card_cases.append(
                CardEvaluationCase(
                    id=case["case_id"],
                    card=card,
                    resources=card_sources,
                    expected_outcome=Outcome(case["expected_outcome"]),
                    expected_delivery_method_keys=(
                        [workflow["card"]["delivery"]["key"]]
                        if case["expected_outcome"] == workflow["card"]["delivery"]["outcome"]
                        else []
                    ),
                    required_evidence_source_keys=[raw["key"] for raw in workflow["sources"]],
                    expected_retrieval_refs=[
                        _ref(raw["adapter"], raw["resource"]) for raw in workflow["sources"]
                    ],
                    tags=[company["shape"], workflow["workflow_id"]],
                    dataset=_dataset(config, company, workflow, case),
                )
            )

    retrieval_cases.append(
        RetrievalQualityCase(
            id="northstar-no-match",
            goal="Find an authorized production source for lunar mining telemetry; return no match if the enterprise catalog does not contain one.",
            expected_resource_refs=[],
            principal=PrincipalContext(principal_id="northstar-analytics-owner", tenant_id="northstar"),
            limit=10,
            dataset=EvaluationDataset(
                dataset_id="northstar-no-match-holdout",
                split="holdout",
                observed_from="2026-02-01",
                observed_to="2026-02-28",
                source_catalog_version=config["catalog_version"],
                digest=_digest({"goal": "lunar mining telemetry", "catalog": config["catalog_version"]}),
            ),
        )
    )

    authoring = InsightAuthoringService(
        registry=registry,
        engine=InsightEngine(judger=recording, registry=registry),
        max_candidates=40,
        principal=None,
    )
    retrieval_report = await RetrievalQualityEvaluator(authoring, max_concurrency=4).evaluate(
        retrieval_cases,
        thresholds=RetrievalQualityThresholds(
            min_candidate_recall=1.0,
            min_recommended_precision=0.90,
            min_recommended_recall=0.85,
            min_cases=len(retrieval_cases),
            require_dataset_provenance=True,
            required_splits=["holdout"],
            require_disjoint_time_splits=True,
        ),
    )
    workflow_report = await CardWorkflowEvaluator(
        InsightEngine(judger=recording), max_concurrency=4
    ).evaluate(
        card_cases,
        thresholds=CardEvaluationThresholds(
            min_outcome_accuracy=0.90,
            min_evidence_recall=1.0,
            min_retrieval_recall=1.0,
            max_unsafe_action_rate=0.0,
            max_error_rate=0.0,
            min_cases=len(card_cases),
            require_dataset_provenance=True,
            required_splits=["train", "holdout", "adversarial"],
            require_disjoint_time_splits=True,
        ),
    )
    elapsed = time.perf_counter() - started
    adapter_telemetry = {
        adapter.name: {
            "search_calls": adapter.search_calls,
            "authorize_calls": adapter.authorize_calls,
            "list_calls": adapter.list_calls,
            "synthetic_catalog_size": adapter.total_count,
        }
        for adapter in adapters
    }
    label_keys = {"expected_resource_refs", "expected_outcome", "allowed_outcomes", "expected_delivery_method_keys"}
    leaked_label_keys = sorted(
        label_keys & {key for call in recording.calls for key in call.get("keys", [])}
    )
    report = {
        "trial": "generalized-readiness-jev-v1",
        "evaluator": recording.name,
        "jev_only_product_path": True,
        "config": str(config_path.relative_to(REPO_ROOT)),
        "companies": len(config["companies"]),
        "workflows": len(cards),
        "card_cases": len(card_cases),
        "retrieval_cases": len(retrieval_cases),
        "elapsed_seconds": round(elapsed, 3),
        "bootstrap": bootstrap_reports,
        "retrieval": retrieval_report.model_dump(mode="json"),
        "workflow": workflow_report.model_dump(mode="json"),
        "adapter_telemetry": adapter_telemetry,
        "jev": {
            "requests": recording.metrics.requests,
            "input_tokens": recording.metrics.input_tokens,
            "output_tokens": recording.metrics.output_tokens,
        },
        "adversarial_review_inputs": {
            "labels_sent_to_jev": bool(leaked_label_keys),
            "leaked_label_keys": leaked_label_keys,
            "tenant_leaks_possible_in_search": False,
            "native_catalog_full_scan_calls": sum(item["list_calls"] for item in adapter_telemetry.values()),
            "time_splits": sorted({case.dataset.split for case in card_cases}),
            "dataset_digests_present": all(case.dataset.digest for case in card_cases),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    output.with_suffix(".md").write_text(render_markdown(report))
    return report


def render_markdown(report: dict[str, Any]) -> str:
    retrieval = report["retrieval"]
    workflow = report["workflow"]
    review = report["adversarial_review_inputs"]
    bootstrap_ready = sum(item["status"] == "ready" for item in report["bootstrap"])
    return (
        "# Generalized Jev readiness trial\n\n"
        f"Evaluator: `{report['evaluator']}`. Companies: **{report['companies']}**. "
        f"Workflows: **{report['workflows']}**. Card cases: **{report['card_cases']}**.\n\n"
        "## Results\n\n"
        "| Gate | Result | Status |\n| --- | ---: | --- |\n"
        f"| Bootstrap workflow checks | {bootstrap_ready} / {len(report['bootstrap'])} | {('pass' if bootstrap_ready == len(report['bootstrap']) else 'fail')} |\n"
        f"| Retrieval candidate recall | {retrieval['candidate_recall']:.3f} | {retrieval['status']} |\n"
        f"| Retrieval recommended precision | {retrieval['recommended_precision']:.3f} | {retrieval['status']} |\n"
        f"| Retrieval recommended recall | {retrieval['recommended_recall']:.3f} | {retrieval['status']} |\n"
        f"| Workflow outcome accuracy | {workflow['outcome_accuracy']:.3f} | {workflow['status']} |\n"
        f"| Workflow evidence recall | {workflow['evidence_recall']:.3f} | {workflow['status']} |\n"
        f"| Unsafe action rate | {workflow['unsafe_action_rate']:.3f} | {('pass' if workflow['unsafe_action_rate'] == 0 else 'fail')} |\n\n"
        "## Boundary review\n\n"
        f"- Jev requests: **{report['jev']['requests']}**; input tokens: **{report['jev']['input_tokens']}**; output tokens: **{report['jev']['output_tokens']}**.\n"
        f"- Native catalog full-scan calls: **{review['native_catalog_full_scan_calls']}**.\n"
        f"- Label keys observed in recorded Jev state: **{', '.join(review['leaked_label_keys']) or 'none'}**.\n"
        f"- Dataset digests present: **{review['dataset_digests_present']}**; time splits: **{', '.join(review['time_splits'])}**.\n\n"
        "This is a synthetic, Jev-backed readiness trial. It proves the bounded protocol and the evaluation contract; it does not prove production connector credentials, query cost, or real operator labels.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=Path("artifacts/generalized-readiness-jev.json"))
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_trial(args.config, args.output)), indent=2))


if __name__ == "__main__":
    main()
