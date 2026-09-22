"""Run a higher-scale, Jev-only Northstar Outfitters mock trial.

This is evaluation code, not product policy.  It expands the editable Northstar
company catalog into a repeatable organization-shaped workload:

* 12 configured analytical domains and 24 generated owner personas;
* the existing 40-person curator/analyst/operations/executive/comms role graph;
* seven workflow states, including stale, failed, incomplete, ambiguous, and
  definition-mismatch evidence;
* 168 owner-authored workflows across disjoint train, validation, holdout, and
  adversarial time partitions;
* a virtual 100k-resource native catalog per adapter with materialized decoys;
* Jev-ranked retrieval and Jev workflow judgments, with labels kept outside the
  state sent to Jev.

The trial deliberately keeps the SignalWeave boundary small.  It does not ask
Jev to invent SQL, permissions, recipients, or actions.  Source adapters bound
and authorize candidates, code owns execution and safety gates, and Jev supplies
typed semantic judgments over the bounded evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluations.enterprise_trial import generate_fixture, load_config
from evaluations.generalized_readiness_trial import NativeCatalogAdapter, RecordingJev
from evaluations.northstar_corporation_trial import (
    DEFAULT_CORPORATION_CONFIG,
    build_agent_roster,
    load_corporation_config,
)
from signalweave.bootstrap import AdapterBootstrapSpec, BootstrapManifest, BootstrapService
from signalweave.engine import InsightEngine
from signalweave.evaluation import (
    CardEvaluationCase,
    CardEvaluationThresholds,
    CardWorkflowEvaluator,
    EvaluationDataset,
)
from signalweave.models import (
    DeliveryMethod,
    InsightCard,
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
DEFAULT_BASE_CONFIG = REPO_ROOT / "evaluations" / "data" / "northstar-company.json"
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "northstar-scale" / "report.json"
DEFAULT_VARIANTS = (
    "corroborated_notify",
    "explained_ignore",
    "contradictory_investigate",
    "stale_escalation",
    "definition_mismatch",
    "missing_baseline",
    "source_failure",
)

SPLIT_BY_VARIANT = {
    "corroborated_notify": "train",
    "explained_ignore": "train",
    "contradictory_investigate": "validation",
    "stale_escalation": "validation",
    "definition_mismatch": "holdout",
    "missing_baseline": "adversarial",
    "source_failure": "adversarial",
}

PERIOD_BY_SPLIT = {
    "train": ("2026-01-01", "2026-01-31"),
    "validation": ("2026-03-01", "2026-03-31"),
    "holdout": ("2026-05-01", "2026-05-31"),
    "adversarial": ("2026-07-01", "2026-07-31"),
}

ADAPTER_NAMES = ("superset", "sql", "airflow", "table", "incident", "calendar")


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _ref(adapter: str, resource: str) -> str:
    return f"{adapter}|{resource}"


def _slug(value: str) -> str:
    return "-".join("".join(c.lower() if c.isalnum() else " " for c in value).split())


def build_scale_config(base_config: dict[str, Any]) -> dict[str, Any]:
    """Derive a larger owner roster from the editable Northstar domain catalog."""
    config = deepcopy(base_config)
    config["company"] = {
        **config["company"],
        "id": "northstar-outfitters-scale",
        "name": "Northstar Outfitters Co. — scaled mock enterprise",
        "description": (
            "A generated Northstar operating model with domain owners, cross-functional "
            "operators, and executive routing over a shared analytical catalog."
        ),
        "seed": 20260920,
    }
    config["task_variants"] = list(DEFAULT_VARIANTS)
    personas: list[dict[str, Any]] = []
    for domain in config["domains"]:
        domain_id = str(domain["id"])
        domain_name = str(domain["name"])
        primary_metric = str(domain["metrics"][0])
        personas.extend(
            [
                {
                    "id": f"{domain_id}-portfolio-lead",
                    "name": f"{domain_name} Portfolio Lead",
                    "technical_literacy": "low",
                    "domain": domain_id,
                    "role_goal": (
                        f"Decide whether a material movement in {primary_metric} "
                        f"deserves {domain_name} leadership attention."
                    ),
                },
                {
                    "id": f"{domain_id}-operations-analyst",
                    "name": f"{domain_name} Operations Analyst",
                    "technical_literacy": "medium",
                    "domain": domain_id,
                    "role_goal": (
                        f"Diagnose changes in {primary_metric} and distinguish an operating "
                        "issue from stale, failed, or incomparable evidence."
                    ),
                },
            ]
        )
    config["personas"] = personas
    return config


def _decision_guidance(variant: str, domain: str, primary: str, context: str) -> str:
    """Create the human policy boundary from the task's owner-authored state."""
    base = (
        f"Use {domain} owner context. Treat the primary {primary} source as the anchor and "
        f"{context} as related evidence; do not infer causation from correlation alone. "
    )
    if variant == "corroborated_notify":
        return base + (
            "Ignore ordinary movement. Notify the approved owner only when the primary "
            "movement is material and fresh related evidence corroborates it. Investigate "
            "if evidence conflicts; escalate if trust or freshness fails."
        )
    if variant == "explained_ignore":
        return base + (
            "Ignore movement explained by the expected operating pattern. Investigate "
            "when the explanation is incomplete; do not notify from movement alone."
        )
    if variant == "contradictory_investigate":
        return base + (
            "Investigate before notification when the primary movement is material but the "
            "related evidence is contradictory or ambiguous. Do not create an automatic alert."
        )
    if variant == "stale_escalation":
        return base + (
            "Escalate the data-trust issue to the approved owner when refresh is overdue. "
            "Do not interpret stale evidence as a business movement."
        )
    if variant == "definition_mismatch":
        return base + (
            "Investigate when definitions, populations, or grains do not match. Do not notify "
            "from directionally related but incomparable sources."
        )
    if variant == "missing_baseline":
        return base + (
            "Return insufficient_data when a comparable baseline is missing. Do not notify or "
            "investigate from an ungrounded movement."
        )
    if variant == "source_failure":
        return base + (
            "Return insufficient_data when the source fails or returns no trustworthy observation. "
            "Do not create a business notification from an adapter error."
        )
    raise ValueError(f"unsupported variant: {variant}")


def build_scale_fixtures(
    base_config_path: str | Path = DEFAULT_BASE_CONFIG,
    *,
    seeds: dict[str, int] | None = None,
    output_dir: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Build disjoint-time Northstar fixtures from company config, not scenarios."""
    base = load_config(base_config_path)
    config = build_scale_config(base)
    seeds = seeds or {
        "train": 20260920,
        "validation": 20260921,
        "holdout": 20260922,
        "adversarial": 20260923,
    }
    fixtures: dict[str, dict[str, Any]] = {}
    for split, seed in seeds.items():
        fixtures[split] = generate_fixture(
            config,
            output_path=(Path(output_dir) / f"fixture-{split}.json") if output_dir else None,
            seed=seed,
            namespace="northstar-scale",
        )
    corporation = load_corporation_config(DEFAULT_CORPORATION_CONFIG)
    roster = build_agent_roster(corporation, base)
    return config, fixtures, roster


def _contract_from_record(record: dict[str, Any], tenant_id: str) -> ResourceContract:
    descriptor = record["descriptor"]
    metadata = descriptor.get("metadata", {})
    snapshot = record.get("snapshot", {})
    observations = snapshot.get("observations", [])
    metric_names = sorted(
        {
            str(observation.get("metric", ""))
            for observation in observations
            if observation.get("metric")
        }
        | {
            str(chart.get("metric", ""))
            for chart in metadata.get("charts", [])
            if chart.get("metric")
        }
    )
    status = str(metadata.get("data_state", "fresh"))
    source_status = {
        "fresh": "healthy",
        "delayed": "healthy",
        "stale": "stale",
        "partial": "ambiguous",
        "missing_baseline": "ambiguous",
        "ambiguous": "ambiguous",
        "failure": "failed",
    }.get(status, "healthy")
    lineage = []
    if metadata.get("linked_dashboard"):
        lineage.append(f"superset|dashboard:{metadata['linked_dashboard']}")
    return ResourceContract(
        tenant_id=tenant_id,
        domain=str(metadata.get("domain", "unknown")),
        scope="Northstar production analytics",
        metric_names=metric_names,
        population=f"{metadata.get('domain', 'enterprise')} published operating population",
        grain="day x region x channel",
        freshness_sla_hours=24.0,
        lineage=lineage,
        roles=(
            ["primary"]
            if descriptor.get("kind") == "dashboard"
            else ["quality"]
            if descriptor.get("adapter") == "airflow"
            else ["diagnostic"]
        ),
        source_status=source_status,
        authorized=True,
    )


def _descriptors_and_records(
    fixtures: dict[str, dict[str, Any]],
    *,
    decoys_per_adapter: int,
    virtual_catalog_size: int,
    tenant_id: str,
) -> tuple[list[NativeCatalogAdapter], dict[tuple[str, str], dict[str, Any]], dict[str, int]]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    descriptors_by_adapter: dict[str, list[ResourceDescriptor]] = {}
    for fixture in fixtures.values():
        for record in fixture["resources"]:
            descriptor_raw = record["descriptor"]
            identity = (str(descriptor_raw["adapter"]), str(descriptor_raw["resource"]))
            if identity in records:
                continue
            records[identity] = record
            # Scenario resources are dated replay observations for the workflow
            # evaluator, not separate catalog assets an onboarding search should
            # discover. Keep them in ``records`` for the workflow snapshots but
            # keep the retrieval catalog focused on stable production assets.
            if "scenario-northstar-scale" in str(descriptor_raw["resource"]):
                continue
            descriptor = ResourceDescriptor.model_validate(descriptor_raw).model_copy(
                update={"contract": _contract_from_record(record, tenant_id)}
            )
            descriptors_by_adapter.setdefault(descriptor.adapter, []).append(descriptor)

    domain_names = sorted(
        {
            descriptor.contract.domain
            for descriptors in descriptors_by_adapter.values()
            for descriptor in descriptors
        }
    )
    for adapter, descriptors in sorted(descriptors_by_adapter.items()):
        for index in range(decoys_per_adapter):
            domain = domain_names[index % len(domain_names)]
            descriptor = ResourceDescriptor(
                adapter=adapter,
                resource=f"decoy:{adapter}:archived-{index:05d}",
                kind="archived_asset",
                title=f"Archived {domain} operating view {index:05d}",
                description=(
                    "Retired sandbox or legacy asset. It may share vocabulary with a "
                    "current dashboard but is not a current source of truth."
                ),
                metadata={"decoy": True, "retention": "legacy"},
                contract=ResourceContract(
                    tenant_id=tenant_id,
                    domain=domain,
                    scope="Northstar legacy analytics",
                    metric_names=[],
                    grain="unknown",
                    freshness_sla_hours=24.0,
                    roles=["unknown"],
                    source_status="healthy",
                ),
            )
            descriptors.append(descriptor)

    # A real onboarding workflow normally begins with a human-curated dashboard
    # or saved query, then expands to related evidence.  Keep those anchors
    # stable across the seven replay states; the state-specific scenario assets
    # above are for workflow judging, not seven different dashboards.
    for domain in domain_names:
        domain_descriptors = [
            descriptor
            for descriptors in descriptors_by_adapter.values()
            for descriptor in descriptors
            if descriptor.contract.domain == domain
            and not descriptor.metadata.get("decoy")
        ]
        metric_names = sorted(
            {
                metric
                for descriptor in domain_descriptors
                for metric in descriptor.contract.metric_names
            }
        )
        anchor_contract = ResourceContract(
            tenant_id=tenant_id,
            domain=domain,
            scope="Northstar human-curated production analytics",
            metric_names=metric_names,
            population=f"{domain} published operating population",
            grain="day x region x channel",
            freshness_sla_hours=24.0,
            lineage=[f"datahub|dataset:northstar-{domain}"],
            roles=["primary"],
            source_status="healthy",
        )
        anchor_descriptor = ResourceDescriptor(
            adapter="superset",
            resource=f"dashboard:northstar-scale-anchor-{domain}",
            kind="dashboard",
            title=f"Northstar {domain} operating dashboard",
            description=(
                f"Human-curated Northstar {domain} dashboard anchor for the operating "
                "card; contains governed charts and links to related evidence."
            ),
            metadata={"anchor": True, "owner_team": f"{domain} operations"},
            contract=anchor_contract,
        )
        descriptors_by_adapter.setdefault("superset", []).append(anchor_descriptor)

    # The generated workflow states exercise six cross-system adapters. Give
    # each one a stable, governed context surface so retrieval can follow the
    # card's related metric instead of matching on adapter names alone.
    domain_metrics: dict[str, list[str]] = {}
    for domain in domain_names:
        domain_metrics[domain] = sorted(
            {
                metric
                for descriptors in descriptors_by_adapter.values()
                for descriptor in descriptors
                if descriptor.contract.domain == domain
                and not descriptor.metadata.get("decoy")
                for metric in descriptor.contract.metric_names
            }
        )
    context_adapters = {
        "superset": ("dashboard", "primary"),
        "sql": ("query", "diagnostic"),
        "airflow": ("dag", "quality"),
        "table": ("table", "quality"),
        "incident": ("incident", "owner"),
        "calendar": ("calendar", "quality"),
    }
    for adapter, (kind, role) in context_adapters.items():
        descriptors = descriptors_by_adapter.setdefault(adapter, [])
        for domain in domain_names:
            resource = f"{kind}:northstar-scale-{domain}-context"
            metric_names = [*domain_metrics.get(domain, []), "operating context"]
            descriptors.append(
                ResourceDescriptor(
                    adapter=adapter,
                    resource=resource,
                    kind=kind,
                    title=f"Northstar {domain} governed context",
                    description=(
                        f"Governed {adapter} context for {domain} operating analysis; "
                        f"covers {', '.join(domain_metrics.get(domain, []))} and is used "
                        "to qualify dashboard evidence."
                    ),
                    metadata={"context_source": True},
                    contract=ResourceContract(
                        tenant_id=tenant_id,
                        domain=domain,
                        scope="Northstar production operating context",
                        metric_names=metric_names,
                        population=f"{domain} operating population",
                        grain="day",
                        freshness_sla_hours=24.0,
                        lineage=[f"superset|dashboard:northstar-scale-anchor-{domain}"],
                        roles=[role],
                        source_status="healthy",
                    ),
                )
            )

    adapters = [
        NativeCatalogAdapter(
            adapter,
            descriptors,
            max(virtual_catalog_size, len(descriptors)),
        )
        for adapter, descriptors in sorted(descriptors_by_adapter.items())
    ]
    return adapters, records, {
        "materialized_descriptors": sum(len(item) for item in descriptors_by_adapter.values()),
        "virtual_catalog_size_per_adapter": virtual_catalog_size,
        "adapter_count": len(adapters),
    }


def _source_refs(task: dict[str, Any]) -> list[SourceRef]:
    return [SourceRef.model_validate(source) for source in task["source_refs"]]


def _snapshot_for_task(
    task: dict[str, Any],
    records: dict[tuple[str, str], dict[str, Any]],
    tenant_id: str,
) -> list[ResourceSnapshot]:
    snapshots: list[ResourceSnapshot] = []
    for source in task["source_refs"]:
        identity = (str(source["adapter"]), str(source["resource"]))
        record = records[identity]
        snapshots.append(
            ResourceSnapshot.model_validate(record["snapshot"]).model_copy(
                update={"contract": _contract_from_record(record, tenant_id)}
            )
        )
    return snapshots


def _card(task: dict[str, Any], *, tenant_id: str, domain: str, variant: str) -> InsightCard:
    brief = task["brief"]
    sources = _source_refs(task)
    if len(sources) > 1:
        # The first source is the human-selected anchor. Related context can
        # corroborate or diagnose it, but a missing primary baseline must still
        # fail closed even when the related source has a usable number.
        sources[1] = sources[1].model_copy(update={"required": False})
    methods = [DeliveryMethod.model_validate(method) for method in brief["delivery_context"]]
    primary = str(brief["watch_for"][0]).split(" moves", 1)[0]
    context = str(brief["watch_for"][1]).split(" corroborates", 1)[0]
    if variant == "stale_escalation":
        context = "upstream refresh health"
    guidance = _decision_guidance(variant, domain, primary, context)
    return InsightCard(
        id=f"northstar-scale-{task['id']}",
        title=str(brief["title"]),
        what_to_watch=str(brief["what_to_watch"]),
        why_watch=str(brief["why_watch"]),
        watch_for=list(brief["watch_for"]),
        questions=list(brief["questions"]),
        decision_guidance=guidance,
        sources=sources,
        comparison_windows=list(brief["comparison_windows"]),
        action_confidence_threshold=0.70,
        owner=f"{tenant_id}-owner",
        delivery_methods=methods,
        investigation_mode="none",
        principal_id=f"{tenant_id}-analytics-owner",
        principal_tenant=tenant_id,
    )


def _dataset(
    config: dict[str, Any],
    task: dict[str, Any],
    split: str,
    snapshots: list[ResourceSnapshot],
) -> EvaluationDataset:
    observed_from, observed_to = PERIOD_BY_SPLIT[split]
    return EvaluationDataset(
        dataset_id=f"northstar-scale-{split}-{task['id']}",
        split=split,
        observed_from=observed_from,
        observed_to=observed_to,
        source_catalog_version="northstar-scale-catalog-v1",
        context_version="northstar-owner-context-v1",
        digest=_digest(
            {
                "company": config["company"]["id"],
                "task": task["id"],
                "variant": task["variant"],
                "split": split,
                "snapshots": [snapshot.model_dump(mode="json") for snapshot in snapshots],
            }
        ),
    )


def _domain_for_task(task: dict[str, Any]) -> str:
    return str(task["brief"].get("domain", "enterprise"))


def _stable_context_ref(adapter: str, domain: str) -> str:
    kind = {
        "superset": "dashboard",
        "sql": "query",
        "airflow": "dag",
        "table": "table",
        "incident": "incident",
        "calendar": "calendar",
    }.get(adapter, adapter)
    return _ref(adapter, f"{kind}:northstar-scale-{_slug(domain)}-context")


def _build_cases(
    config: dict[str, Any],
    fixtures: dict[str, dict[str, Any]],
    *,
    tenant_id: str,
) -> tuple[list[CardEvaluationCase], list[RetrievalQualityCase], dict[str, InsightCard]]:
    cards: dict[str, InsightCard] = {}
    workflow_cases: list[CardEvaluationCase] = []
    retrieval_cases: list[RetrievalQualityCase] = []
    principal = PrincipalContext(
        principal_id=f"{tenant_id}-analytics-owner",
        tenant_id=tenant_id,
        scopes=["analytics:read", "signalweave:evaluate"],
        authorization_source="northstar-scale-trial-gateway",
    )
    for split, fixture in fixtures.items():
        tasks = fixture["tasks"]
        records = {
            (str(record["descriptor"]["adapter"]), str(record["descriptor"]["resource"])): record
            for record in fixture["resources"]
        }
        for task in tasks:
            variant = str(task["variant"])
            if SPLIT_BY_VARIANT[variant] != split:
                continue
            snapshots = _snapshot_for_task(task, records, tenant_id)
            card = _card(task, tenant_id=tenant_id, domain=_domain_for_task(task), variant=variant)
            cards[card.id] = card
            refs = [
                _ref(str(source["adapter"]), str(source["resource"]))
                for source in task["source_refs"]
            ]
            retrieval_expected = [
                _ref(
                    "superset",
                    f"dashboard:northstar-scale-anchor-{_slug(_domain_for_task(task))}",
                )
            ]
            primary_domain = _domain_for_task(task)
            context_domain = (
                snapshots[1].contract.domain if len(snapshots) > 1 else primary_domain
            )
            acceptable_refs = set(retrieval_expected)
            required_context_group = {
                _stable_context_ref(adapter, context_domain)
                for adapter in ADAPTER_NAMES
            }
            for domain in {primary_domain, context_domain}:
                acceptable_refs.add(
                    _ref(
                        "superset",
                        f"dashboard:northstar-scale-anchor-{_slug(domain)}",
                    )
                )
                acceptable_refs.update(
                    _stable_context_ref(adapter, domain)
                    for adapter in ADAPTER_NAMES
                )
            dataset = _dataset(config, task, split, snapshots)
            workflow_cases.append(
                CardEvaluationCase(
                    id=f"{task['id']}-{split}",
                    card=card,
                    resources=snapshots,
                    expected_outcome=Outcome(task["expected_outcome"]),
                    allowed_outcomes=(
                        [Outcome(task["expected_outcome"]), Outcome.INVESTIGATE]
                        if Outcome(task["expected_outcome"])
                        in {Outcome.NOTIFY, Outcome.ESCALATE, Outcome.INSUFFICIENT_DATA}
                        else [Outcome(task["expected_outcome"])]
                    ),
                    expected_delivery_method_keys=list(task["expected_delivery_methods"]),
                    required_evidence_source_keys=[snapshot.source_key for snapshot in snapshots],
                    expected_retrieval_refs=refs,
                    tags=["northstar", _domain_for_task(task), variant],
                    dataset=dataset,
                )
            )
            retrieval_cases.append(
                RetrievalQualityCase(
                    id=f"retrieval-{task['id']}-{split}",
                    goal=(
                        f"{task['goal']} Source hints: "
                        + "; ".join(str(hint) for hint in task["brief"].get("source_hints", []))
                        + f". Related context domain: {context_domain}."
                    ),
                    expected_resource_refs=retrieval_expected,
                    acceptable_resource_refs=sorted(acceptable_refs),
                    required_resource_groups=[sorted(required_context_group)],
                    limit=10,
                    principal=principal,
                    tags=["northstar", _domain_for_task(task), variant],
                    dataset=dataset.model_copy(
                        update={"dataset_id": f"retrieval-{dataset.dataset_id}"}
                    ),
                )
            )
    retrieval_cases.append(
        RetrievalQualityCase(
            id="retrieval-northstar-no-match",
            goal=(
                "Find a Northstar production source for lunar mining telemetry. "
                "Return no match if the authorized enterprise catalog contains none."
            ),
            expected_resource_refs=[],
            limit=10,
            principal=principal,
            tags=["northstar", "no-match"],
            dataset=EvaluationDataset(
                dataset_id="retrieval-northstar-no-match",
                split="holdout",
                observed_from=PERIOD_BY_SPLIT["holdout"][0],
                observed_to=PERIOD_BY_SPLIT["holdout"][1],
                source_catalog_version="northstar-scale-catalog-v1",
                context_version="northstar-owner-context-v1",
                digest=_digest({"goal": "lunar mining telemetry"}),
            ),
        )
    )
    return workflow_cases, retrieval_cases, cards


def _role_assignments(tasks: list[CardEvaluationCase], roster: list[dict[str, Any]]) -> dict[str, Any]:
    groups = Counter(agent["group"] for agent in roster)
    assignments: list[dict[str, str]] = []
    operations = [agent for agent in roster if agent["group"] == "enterprise_operations"]
    executives = [agent for agent in roster if agent["group"] == "executives"]
    communications = [agent for agent in roster if agent["group"] == "communications"]
    for index, case in enumerate(tasks):
        domain = case.tags[1] if len(case.tags) > 1 else "enterprise"
        domain_slug = _slug(domain)
        assignments.append(
            {
                "case_id": case.id,
                "curator_id": f"domain-curator-{domain_slug}",
                "analyst_id": f"domain-analyst-{domain_slug}",
                "operations_id": operations[index % len(operations)]["id"],
                "executive_id": executives[index % len(executives)]["id"],
                "communications_id": communications[index % len(communications)]["id"],
            }
        )
    return {
        "role_agents": len(roster),
        "role_groups": dict(groups),
        "workflow_role_assignments": len(assignments),
        "simulated_handoffs": sum(
            1
            for assignment, case in zip(assignments, tasks, strict=True)
            if case.expected_outcome in {Outcome.NOTIFY, Outcome.ESCALATE, Outcome.INVESTIGATE}
        ),
        "assignments_sample": assignments[:10],
    }


def _load_reused_workflow_evidence(
    path: str | Path,
    *,
    workflow_cases: list[CardEvaluationCase],
    cards: dict[str, InsightCard],
    config: dict[str, Any],
    roster: list[dict[str, Any]],
    source_adapters: set[str],
) -> dict[str, Any]:
    """Load a previously approved live workflow report after strict identity checks.

    Retrieval-only retries must not silently combine a new fixture population with
    old workflow evidence.  This check keeps the expensive workflow judgments
    reusable while requiring the generated company, cards, splits, variants, and
    source boundary to be identical.
    """

    report_path = Path(path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    workflow = payload.get("workflow")
    scale = payload.get("scale", {})
    failures: list[str] = []
    expected_dataset_ids = sorted(case.dataset.dataset_id for case in workflow_cases)
    expected_card_ids = sorted(cards)
    expected_variants = dict(Counter(case.tags[-1] for case in workflow_cases))
    expected_outcomes = dict(Counter(case.expected_outcome.value for case in workflow_cases))

    if payload.get("evaluator") != "jev-latest":
        failures.append("reused report evaluator is not Jev")
    if payload.get("jev_only_product_path") is not True:
        failures.append("reused report is not marked Jev-only")
    if not isinstance(workflow, dict):
        failures.append("reused report has no workflow report")
        workflow = {}
    if workflow.get("status") != "approved":
        failures.append("reused workflow report is not approved")
    if workflow.get("case_count") != len(workflow_cases):
        failures.append("reused workflow case count does not match this fixture")
    if workflow.get("error_rate") != 0.0:
        failures.append("reused workflow report contains evaluation errors")
    if sorted(workflow.get("dataset_ids", [])) != expected_dataset_ids:
        failures.append("reused workflow dataset IDs do not match this fixture")
    if sorted(workflow.get("card_ids", [])) != expected_card_ids:
        failures.append("reused workflow card IDs do not match this fixture")
    if sorted(workflow.get("splits", [])) != sorted(PERIOD_BY_SPLIT):
        failures.append("reused workflow time splits do not match this fixture")
    if scale.get("company") != config["company"]:
        failures.append("reused workflow company identity does not match")
    if scale.get("domains") != len(config["domains"]):
        failures.append("reused workflow domain count does not match")
    if scale.get("owner_personas") != len(config["personas"]):
        failures.append("reused workflow persona count does not match")
    if scale.get("role_agents") != len(roster):
        failures.append("reused workflow role roster does not match")
    if scale.get("workflow_case_count") != len(workflow_cases):
        failures.append("reused workflow scale count does not match")
    if scale.get("variant_counts") != expected_variants:
        failures.append("reused workflow variants do not match")
    if scale.get("expected_outcome_counts") != expected_outcomes:
        failures.append("reused workflow outcome distribution does not match")
    if set(scale.get("source_adapters", [])) != source_adapters:
        failures.append("reused workflow source adapter boundary does not match")
    if failures:
        raise ValueError(
            f"refusing reused workflow evidence from {report_path}: "
            + "; ".join(failures)
        )
    return {
        "workflow": workflow,
        "source_report": payload,
        "source_path": str(report_path),
    }


async def run_trial(
    *,
    output: str | Path = DEFAULT_OUTPUT,
    base_config_path: str | Path = DEFAULT_BASE_CONFIG,
    fixture_dir: str | Path | None = None,
    decoys_per_adapter: int = 300,
    virtual_catalog_size: int = 100_000,
    max_concurrency: int = 12,
    retrieval_only: bool = False,
    reuse_workflow_report: str | Path | None = None,
) -> dict[str, Any]:
    if decoys_per_adapter < 0:
        raise ValueError("decoys_per_adapter must be non-negative")
    if virtual_catalog_size < 1:
        raise ValueError("virtual_catalog_size must be positive")
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be positive")
    if retrieval_only and reuse_workflow_report is None:
        raise ValueError("retrieval_only requires reuse_workflow_report")
    if not retrieval_only and reuse_workflow_report is not None:
        raise ValueError("reuse_workflow_report requires retrieval_only")

    config, fixtures, roster = build_scale_fixtures(
        base_config_path,
        output_dir=fixture_dir,
    )
    tenant_id = "northstar-outfitters"
    adapters, records, catalog_stats = _descriptors_and_records(
        fixtures,
        decoys_per_adapter=decoys_per_adapter,
        virtual_catalog_size=virtual_catalog_size,
        tenant_id=tenant_id,
    )
    registry = SourceRegistry(adapters, max_concurrency=max_concurrency)
    key = load_api_key()
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE is required")
    recording = RecordingJev(JevJudger(api_key=key))
    engine = InsightEngine(judger=recording)
    workflow_cases, retrieval_cases, cards = _build_cases(
        config, fixtures, tenant_id=tenant_id
    )
    principal = PrincipalContext(
        principal_id=f"{tenant_id}-analytics-owner",
        tenant_id=tenant_id,
        scopes=["analytics:read", "signalweave:evaluate"],
        authorization_source="northstar-scale-trial-gateway",
    )
    source_adapters = {source.adapter for case in workflow_cases for source in case.card.sources}

    bootstrap_started = time.perf_counter()
    adapters_by_name = {adapter.name: adapter for adapter in adapters}
    bootstrap = await BootstrapService(registry).assess(
        BootstrapManifest(
            tenant_id=tenant_id,
            name="Northstar Outfitters scaled source boundary",
            adapters=[
                AdapterBootstrapSpec(
                    adapter=name,
                    probe_goal=(
                        "Find a Northstar production analytical source for the "
                        "domain monitoring workflow."
                    ),
                    required_capabilities=[
                        "catalog",
                        "search",
                        "inspect",
                        "tenant_scope",
                        "freshness",
                        "lineage",
                        "metric_definitions",
                    ],
                    minimum_resources=1,
                    allow_paginated_search=True,
                )
                for name in sorted(adapters_by_name)
            ],
        ),
        principal=principal,
    )
    bootstrap_elapsed = time.perf_counter() - bootstrap_started

    started = time.perf_counter()
    authoring = InsightAuthoringService(
        registry=registry,
        engine=engine,
        max_candidates=40,
        principal=principal,
    )
    retrieval_report = await RetrievalQualityEvaluator(
        authoring, max_concurrency=max_concurrency
    ).evaluate(
        retrieval_cases,
        thresholds=RetrievalQualityThresholds(
            min_candidate_recall=1.0,
            min_recommended_precision=0.90,
            min_recommended_recall=0.90,
            min_required_group_recall=1.0,
            max_error_rate=0.0,
            min_cases=len(retrieval_cases),
            require_dataset_provenance=True,
            required_splits=list(PERIOD_BY_SPLIT),
            max_unauthorized_refs=0,
            require_disjoint_time_splits=True,
        ),
    )
    workflow_evidence: dict[str, Any] | None = None
    if retrieval_only:
        workflow_evidence = _load_reused_workflow_evidence(
            reuse_workflow_report,
            workflow_cases=workflow_cases,
            cards=cards,
            config=config,
            roster=roster,
            source_adapters=source_adapters,
        )
        workflow_report = workflow_evidence["workflow"]
    else:
        workflow_model = await CardWorkflowEvaluator(
            engine, max_concurrency=max_concurrency
        ).evaluate(
            workflow_cases,
            thresholds=CardEvaluationThresholds(
                min_outcome_accuracy=0.90,
                min_evidence_recall=1.0,
                min_retrieval_recall=1.0,
                max_unsafe_action_rate=0.0,
                max_error_rate=0.0,
                min_cases=len(workflow_cases),
                require_dataset_provenance=True,
                required_splits=list(PERIOD_BY_SPLIT),
                require_disjoint_time_splits=True,
            ),
        )
        workflow_report = workflow_model.model_dump(mode="json")
    elapsed = time.perf_counter() - started

    call_keys = [key for call in recording.calls for key in call.get("keys", [])]
    label_keys = {
        "expected_resource_refs",
        "expected_outcome",
        "allowed_outcomes",
        "expected_delivery_method_keys",
        "required_evidence_source_keys",
    }
    adapter_telemetry = {
        adapter.name: {
            "search_calls": adapter.search_calls,
            "authorize_calls": adapter.authorize_calls,
            "list_calls": adapter.list_calls,
            "materialized_descriptor_count": len(adapter._descriptors),
            "virtual_catalog_size": adapter.total_count,
        }
        for adapter in adapters
    }
    outcome_counts = Counter(case.expected_outcome.value for case in workflow_cases)
    variant_counts = Counter(case.tags[-1] for case in workflow_cases)
    reused_review_inputs = (
        workflow_evidence["source_report"].get("adversarial_review_inputs", {})
        if workflow_evidence
        else {}
    )
    current_leaked_label_keys = sorted(set(call_keys) & label_keys)
    leaked_label_keys = sorted(
        set(current_leaked_label_keys)
        | set(reused_review_inputs.get("leaked_label_keys", []))
    )
    report = {
        "trial": "northstar-outfitters-scaled-jev-only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluator": recording.name,
        "jev_only_product_path": True,
        "company": config["company"],
        "scale": {
            "domains": len(config["domains"]),
            "owner_personas": len(config["personas"]),
            "role_agents": len(roster),
            "workflow_count": len(cards),
            "workflow_case_count": len(workflow_cases),
            "retrieval_case_count": len(retrieval_cases),
            "source_adapters": sorted(source_adapters),
            "expected_outcome_counts": dict(outcome_counts),
            "variant_counts": dict(variant_counts),
            "catalog": catalog_stats,
        },
        "roles": _role_assignments(workflow_cases, roster),
        "bootstrap": {
            "elapsed_seconds": round(bootstrap_elapsed, 3),
            "report": bootstrap.model_dump(mode="json"),
        },
        "retrieval": retrieval_report.model_dump(mode="json"),
        "workflow": workflow_report,
        "jev": {
            "requests": retrieval_report.jev_requests + workflow_report.get("jev_requests", 0),
            "input_tokens": retrieval_report.jev_input_tokens + workflow_report.get("jev_input_tokens", 0),
            "output_tokens": retrieval_report.jev_output_tokens + workflow_report.get("jev_output_tokens", 0),
            "recorded_calls": len(recording.calls),
            "live_recorded_calls": len(recording.calls),
            "reused_workflow_recorded_calls": (
                int(workflow_report.get("jev_requests", 0)) if retrieval_only else 0
            ),
            "requests_per_retrieval_case": round(
                retrieval_report.jev_requests / len(retrieval_cases), 3
            )
            if retrieval_cases
            else 0.0,
            "requests_per_workflow_case": round(
                workflow_report.get("jev_requests", 0) / len(workflow_cases), 3
            )
            if workflow_cases
            else 0.0,
        },
        "runtime": {
            "evaluation_elapsed_seconds": round(elapsed, 3),
            "max_concurrency": max_concurrency,
            "source_adapter_names": sorted(adapters_by_name),
        },
        "evidence_provenance": {
            "mode": (
                "retrieval-only-with-reused-workflow"
                if retrieval_only
                else "full-live-jev"
            ),
            "retrieval": "live-jev",
            "workflow": (
                "reused-approved-live-jev"
                if retrieval_only
                else "live-jev"
            ),
            "reused_workflow_report": (
                workflow_evidence["source_path"] if workflow_evidence else None
            ),
        },
        "adversarial_review_inputs": {
            "labels_sent_to_jev": bool(leaked_label_keys)
            or bool(reused_review_inputs.get("labels_sent_to_jev")),
            "leaked_label_keys": leaked_label_keys,
            "native_catalog_full_scan_calls": sum(
                item["list_calls"] for item in adapter_telemetry.values()
            ),
            "native_search_calls": sum(
                item["search_calls"] for item in adapter_telemetry.values()
            ),
            "native_authorize_calls": sum(
                item["authorize_calls"] for item in adapter_telemetry.values()
            ),
            "candidate_pool_bound": 40,
            "dataset_splits": sorted({case.dataset.split for case in workflow_cases}),
            "dataset_digests_present": all(case.dataset.digest for case in workflow_cases),
            "principal_tenant": tenant_id,
        },
        "limitations": [
            "Northstar source rows and owner labels are generated fixtures, not production customer data.",
            "The 40 role agents and delivery acknowledgements are simulated; external destinations remain disabled.",
            "Virtual catalog size is enforced at the adapter boundary; only bounded search candidates are materialized.",
            "This establishes a serious shadow-trial gate, not a claim that every enterprise workflow is automatically safe.",
        ],
    }
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    bootstrap = report["bootstrap"]["report"]
    retrieval = report["retrieval"]
    workflow = report["workflow"]
    review = report["adversarial_review_inputs"]
    return "\n".join(
        [
            "# Northstar Outfitters scaled Jev-only mock trial",
            "",
            f"Generated: `{report['generated_at']}`. Evaluator: `{report['evaluator']}`.",
            "",
            "## Workload",
            "",
            f"- **{report['scale']['role_agents']}** simulated role agents across **{report['scale']['domains']}** domains and **{report['scale']['owner_personas']}** owner personas.",
            f"- **{report['scale']['workflow_case_count']}** workflow cases and **{report['scale']['retrieval_case_count']}** retrieval cases across four disjoint time splits.",
            f"- **{report['scale']['catalog']['virtual_catalog_size_per_adapter']:,}** virtual resources per adapter; **{report['scale']['catalog']['materialized_descriptors']:,}** bounded descriptors materialized for the trial.",
            "",
            "## Gates",
            "",
            "| Gate | Result | Status |",
            "| --- | ---: | --- |",
            f"| Bootstrap adapters ready | {sum(item['status'] == 'ready' for item in bootstrap['adapters'])}/{len(bootstrap['adapters'])} | {bootstrap['status']} |",
            f"| Retrieval candidate recall | {retrieval['candidate_recall']:.3f} | {retrieval['status']} |",
            f"| Retrieval recommended precision | {retrieval['recommended_precision']:.3f} | {retrieval['status']} |",
            f"| Retrieval recommended recall | {retrieval['recommended_recall']:.3f} | {retrieval['status']} |",
            f"| Workflow outcome accuracy | {workflow['outcome_accuracy']:.3f} | {workflow['status']} |",
            f"| Workflow evidence recall | {workflow['evidence_recall']:.3f} | {workflow['status']} |",
            f"| Unsafe automatic action rate | {workflow['unsafe_action_rate']:.3f} | {'pass' if workflow['unsafe_action_rate'] == 0 else 'fail'} |",
            f"| Workflow error rate | {workflow['error_rate']:.3f} | {'pass' if workflow['error_rate'] == 0 else 'fail'} |",
            "",
            "## Jev and scale evidence",
            "",
            f"- Jev requests: **{report['jev']['requests']:,}**; input tokens: **{report['jev']['input_tokens']:,}**; output tokens: **{report['jev']['output_tokens']:,}**.",
            f"- Evaluation wall time: **{report['runtime']['evaluation_elapsed_seconds']}s** at concurrency **{report['runtime']['max_concurrency']}**.",
            f"- Native search calls: **{review['native_search_calls']:,}**; native authorization calls: **{review['native_authorize_calls']:,}**; full catalog scans: **{review['native_catalog_full_scan_calls']}**.",
            f"- Labels in recorded Jev state: **{', '.join(review['leaked_label_keys']) or 'none'}**.",
            "",
            "## Boundary",
            "",
            "SignalWeave supplies bounded, authorized evidence and applies the owner-authored card contract. Jev ranks candidates and returns typed judgments. Code owns source inspection, freshness/error gates, configured delivery, and the promotion thresholds. The trial does not contact Slack, email, or incident systems.",
            "",
            "The report is evidence for a staged Northstar shadow deployment, not proof that generated labels equal production truth. The next step after this gate is a real owner-labeled replay with delivery disabled.",
            "",
        ]
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-config", type=Path, default=DEFAULT_BASE_CONFIG)
    parser.add_argument("--fixture-dir", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--decoys-per-adapter", type=int, default=300)
    parser.add_argument("--virtual-catalog-size", type=int, default=100_000)
    parser.add_argument("--max-concurrency", type=int, default=12)
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="run live Jev retrieval only and reuse a matching approved workflow report",
    )
    parser.add_argument(
        "--reuse-workflow-report",
        type=Path,
        help="approved full-trial JSON to reuse with --retrieval-only",
    )
    return parser


async def _main(args: argparse.Namespace) -> None:
    report = await run_trial(
        output=args.output,
        base_config_path=args.base_config,
        fixture_dir=args.fixture_dir,
        decoys_per_adapter=args.decoys_per_adapter,
        virtual_catalog_size=args.virtual_catalog_size,
        max_concurrency=args.max_concurrency,
        retrieval_only=args.retrieval_only,
        reuse_workflow_report=args.reuse_workflow_report,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(_main(_parser().parse_args()))
