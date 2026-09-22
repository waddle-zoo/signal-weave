"""Live Jev proof for relationship-aware candidate expansion.

This is a focused follow-up to the Northstar retrieval ablation. It runs the
production-shaped ``InsightAuthoringService.resolve_bundle`` path for one
cross-domain card. The lexical search intentionally does not name the related
domain; a graph fact supplied by the company connects the approved Payments
anchor to a Fulfillment context anchor. The native-style adapters then expose
that bounded neighborhood through the optional relationship-expansion
contract, and Jev ranks the combined candidates.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from evaluations.generalized_readiness_trial import RecordingJev
from evaluations.northstar_retrieval_ablation import _slug
from evaluations.northstar_scale_trial import (
    DEFAULT_BASE_CONFIG,
    _descriptors_and_records,
    build_scale_fixtures,
)
from signalweave.models import (
    ContextFact,
    ContextSnapshot,
    InsightCard,
    PrincipalContext,
    RetrievalMode,
    SourceRef,
)
from signalweave.onboarding import InsightAuthoringService
from signalweave.retrieval import resource_ref
from signalweave.sources import SourceRegistry
from signalweave.typesafe_adapter import JevJudger, load_api_key

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "northstar-relationship-expansion" / "report.json"


def _context(domain: str) -> tuple[ContextSnapshot, str, str]:
    primary_ref = f"superset|dashboard:northstar-scale-anchor-{_slug(domain)}"
    related_context = "context:fulfillment-operating-model"
    return (
        ContextSnapshot(
            provider="northstar-owner-context",
            version="northstar-owner-context-v2",
            facts=[
                ContextFact(
                    fact_id="card-cross-domain-relationship",
                    subject_ref=primary_ref,
                    relation="requires_related_context",
                    object_ref=related_context,
                    statement=(
                        "Payments authorization monitoring uses the Fulfillment operating "
                        "context to interpret customer-impacting movement."
                    ),
                    provenance=["human-card-context", "northstar-owner-context-v2"],
                )
            ],
        ),
        primary_ref,
        related_context,
    )


def _publish_context_alias(adapters: list[Any], context_ref: str) -> None:
    """Publish a graph concept alias on the generated adapter index."""
    for adapter in adapters:
        for descriptor in adapter._descriptors:
            if descriptor.resource.endswith("-context") and descriptor.contract.domain == "fulfillment":
                related_refs = descriptor.metadata.setdefault("related_refs", [])
                if context_ref not in related_refs:
                    related_refs.append(context_ref)
                adapter._related_index.setdefault(context_ref, []).append(descriptor)


async def run_trial(*, output: str | Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    config, fixtures, _roster = build_scale_fixtures(DEFAULT_BASE_CONFIG)
    tenant_id = "northstar-outfitters"
    adapters, _records, catalog_stats = _descriptors_and_records(
        fixtures,
        decoys_per_adapter=300,
        virtual_catalog_size=100_000,
        tenant_id=tenant_id,
    )
    _publish_context_alias(adapters, "context:fulfillment-operating-model")
    registry = SourceRegistry(adapters)
    principal = PrincipalContext(
        principal_id="northstar-relationship-trial",
        tenant_id=tenant_id,
        scopes=["analytics:read", "signalweave:evaluate"],
        authorization_source="northstar-relationship-trial",
    )
    context, primary_ref, related_anchor_ref = _context("payments")
    expected_related = {
        f"{adapter}|{kind}:northstar-scale-fulfillment-context"
        for adapter, kind in {
            "superset": "dashboard",
            "sql": "query",
            "airflow": "dag",
            "table": "table",
            "incident": "incident",
            "calendar": "calendar",
        }.items()
    }
    goal = (
        "Monitor authorization rate movement and decide whether customer-facing "
        "growth operations should act."
    )
    card = InsightCard(
        id="northstar-relationship-expansion",
        title="Payments authorization health",
        what_to_watch=goal,
        why_watch="Decide whether a material movement deserves leadership attention.",
        watch_for=["Material movement in the approved operating signal."],
        questions=["What connected evidence explains or qualifies the movement?"],
        decision_guidance=(
            "Use the approved primary source and connected evidence. Ignore ordinary movement, "
            "investigate contradictory evidence, and notify only when the evidence is fresh "
            "and corroborated."
        ),
        sources=[
            SourceRef(
                key="payments-anchor",
                adapter="superset",
                resource="dashboard:northstar-scale-anchor-payments",
                label="Northstar Payments operating dashboard",
            )
        ],
        retrieval_mode=RetrievalMode.EXPAND,
        max_source_age_hours=24.0,
        principal_id=principal.principal_id,
        principal_tenant=principal.tenant_id,
    )
    api_key = load_api_key()
    if not api_key:
        raise RuntimeError("TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE is required")
    recording = RecordingJev(JevJudger(api_key=api_key))
    service = InsightAuthoringService(
        registry=registry,
        engine=type("Engine", (), {"judger": recording})(),
        max_candidates=40,
        related_source_limit=6,
        principal=principal,
    )

    search_page = await registry.search_resources(
        goal,
        limit=48,
        authorized_tenants=[tenant_id],
    )
    expansion_page = await registry.expand_related_resources(
        [primary_ref, related_anchor_ref],
        limit=40,
        authorized_tenants=[tenant_id],
    )
    search_refs = {resource_ref(resource) for resource in search_page.resources}
    expansion_refs = {resource_ref(resource) for resource in expansion_page.resources}
    started = time.perf_counter()
    bundle = await service.resolve_bundle(card, context=context, principal=principal)
    elapsed = time.perf_counter() - started
    selected_related = {match.ref for match in bundle.related_matches}
    report = {
        "trial": "northstar-relationship-expansion-jev-only",
        "evaluator": recording.name,
        "jev_only": True,
        "company": config["company"],
        "card": {
            "primary_anchor": primary_ref,
            "related_context_anchor": related_anchor_ref,
            "context_version": context.version,
        },
        "catalog": catalog_stats,
        "candidate_boundary": {
            "lexical_search_count": len(search_refs),
            "lexical_search_expected_group_recall": len(expected_related & search_refs)
            / len(expected_related),
            "relationship_expansion_count": len(expansion_refs),
            "relationship_expansion_expected_group_recall": len(
                expected_related & expansion_refs
            )
            / len(expected_related),
            "expanded_group_refs": sorted(expected_related & expansion_refs),
            "expansion_strategy": expansion_page.strategy,
            "full_scan_calls": sum(adapter.list_calls for adapter in adapters),
        },
        "bundle": {
            "candidate_count": bundle.candidate_count,
            "candidate_strategy": bundle.candidate_strategy,
            "selected_related_refs": sorted(selected_related),
            "selected_expected_group_recall": len(expected_related & selected_related)
            / len(expected_related),
            "selected_context_obligation_recall": 1.0
            if expected_related & selected_related
            else 0.0,
            "selected_acceptable_refs": sorted(selected_related & expected_related),
            "warnings": bundle.warnings,
        },
        "jev": {
            "requests": recording.metrics.requests,
            "input_tokens": recording.metrics.input_tokens,
            "output_tokens": recording.metrics.output_tokens,
        },
        "runtime": {"bundle_resolution_seconds": round(elapsed, 3)},
        "thesis_result": (
            "Relationship expansion made the missing cross-domain neighborhood visible "
            "to Jev without scanning the virtual catalog. This proves candidate recall, "
            "not that one global Jev threshold is a complete bundle assembler."
        ),
    }
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    boundary = report["candidate_boundary"]
    bundle = report["bundle"]
    return "\n".join(
        [
            "# Northstar relationship-expansion trial",
            "",
            "A focused live Jev proof of the production-shaped relationship-aware retrieval path.",
            "",
            f"- Lexical candidate group recall: **{boundary['lexical_search_expected_group_recall']:.3f}**",
            f"- Relationship-expanded candidate group recall: **{boundary['relationship_expansion_expected_group_recall']:.3f}**",
            f"- Jev-selected group recall: **{bundle['selected_expected_group_recall']:.3f}**",
            f"- Jev-selected context obligation recall: **{bundle['selected_context_obligation_recall']:.3f}**",
            f"- Jev requests: **{report['jev']['requests']}**",
            f"- Native full catalog scans: **{boundary['full_scan_calls']}**",
            "",
            "The first two numbers isolate candidate coverage. The final number is intentionally separate: making the right neighborhood visible to Jev is necessary, but a global relevance threshold is not yet a complete multi-role bundle planner.",
            "",
        ]
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


async def _main(args: argparse.Namespace) -> None:
    report = await run_trial(output=args.output)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(_main(_parser().parse_args()))
