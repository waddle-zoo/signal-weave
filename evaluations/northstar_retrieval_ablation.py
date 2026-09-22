"""Bounded Jev ablation for generalized related-source retrieval.

The trial tests the retrieval problem, not Jev as a cold-start reasoner. Each
variant uses the same adapter-owned candidate set and one Jev request. The
request returns typed probabilities for overall relevance and four reusable
source roles. Offline evaluator labels are used only after the request to
compare bundle assembly policies:

* ``goal_only``: rank by the broad monitoring goal;
* ``anchor_aware``: rank relatedness with the human-approved anchor and graph
  context;
* ``role_aware``: assemble a bundle with explicit corroboration, diagnostic,
  quality, and owner coverage.

This is exploratory evaluation code. It does not change the production
retrieval policy until the results are reviewed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluations.northstar_scale_trial import (
    DEFAULT_BASE_CONFIG,
    _build_cases,
    _descriptors_and_records,
    _ref,
    _slug,
    build_scale_fixtures,
)
from signalweave.models import ContextFact, ContextSnapshot, ResourceDescriptor
from signalweave.retrieval import resource_ref
from signalweave.sources import SourceRegistry
from signalweave.typesafe_adapter import JudgerMetrics, load_api_key

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "northstar-retrieval-ablation" / "report.json"

ROLE_NAMES = ("related", "diagnostic", "quality", "owner")
ROLE_THRESHOLD = 0.60
GOAL_LIMIT = 10
ROLE_TOP_K = 2


def _descriptor_payload(resource: ResourceDescriptor) -> dict[str, Any]:
    return {
        "ref": resource_ref(resource),
        "adapter": resource.adapter,
        "resource": resource.resource,
        "kind": resource.kind,
        "title": resource.title,
        "description": resource.description,
        "metadata": resource.metadata,
        "contract": resource.contract.model_dump(mode="json"),
    }


def _graph_context(
    descriptors: list[ResourceDescriptor], anchor_ref: str, domain: str
) -> ContextSnapshot:
    """Build context only from adapter-published lineage, never evaluator labels."""
    facts: list[ContextFact] = []
    for descriptor in descriptors:
        ref = resource_ref(descriptor)
        if ref == anchor_ref:
            continue
        if anchor_ref not in set(descriptor.contract.lineage):
            continue
        facts.append(
            ContextFact(
                fact_id=f"lineage-{_slug(ref)}",
                subject_ref=ref,
                relation="published_context_for",
                object_ref=anchor_ref,
                statement=(
                    f"{descriptor.title} publishes governed {descriptor.adapter} context "
                    f"for the {domain} operating anchor."
                ),
                provenance=["northstar-owner-context-v1", "adapter-lineage"],
            )
        )
    return ContextSnapshot(
        provider="northstar-owner-context",
        version="northstar-owner-context-v1",
        facts=facts,
    )


def _anchor_descriptor(
    descriptors: list[ResourceDescriptor], anchor_ref: str
) -> ResourceDescriptor:
    for descriptor in descriptors:
        if resource_ref(descriptor) == anchor_ref:
            return descriptor
    raise AssertionError(f"human-curated anchor is missing from catalog: {anchor_ref}")


def _question_set(candidate_count: int):
    from typesafe_sdk import Noul

    questions: dict[str, Any] = {}
    for index in range(candidate_count):
        questions[f"global_{index}"] = Noul(
            instructions=(
                f"Judge candidates[{index}] against cold_start_goal only. Do not use "
                "anchor_context or graph_context. Is this source materially useful to "
                "answer the overall monitoring goal, rather than merely sharing words?"
            ),
            criteria={
                "true": "It contains a signal or evidence that materially helps answer the overall goal.",
                "false": "It is unrelated, redundant, too vague, or only shares vocabulary.",
            },
        )
        questions[f"related_{index}"] = Noul(
            instructions=(
                f"Judge candidates[{index}] against anchored_goal, anchor_context, and "
                "graph_context. Is it a useful related source for corroboration or broader "
                "operating context around the human-approved anchor?"
            ),
            criteria={
                "true": "The source has a meaningful relationship to the anchor or graph context and could strengthen the evidence bundle.",
                "false": "The source has no demonstrated relationship to the anchor or is only a lexical match.",
            },
        )
        questions[f"diagnostic_{index}"] = Noul(
            instructions=(
                f"Judge candidates[{index}] for the diagnostic role in anchored_goal. "
                "Could it help explain why the primary signal moved?"
            ),
            criteria={
                "true": "It could supply a plausible driver, dependency, deployment, incident, or cross-system explanation.",
                "false": "It does not provide explanatory evidence for the monitored signal.",
            },
        )
        questions[f"quality_{index}"] = Noul(
            instructions=(
                f"Judge candidates[{index}] for the quality role in anchored_goal. "
                "Could it qualify freshness, completeness, definition, comparability, or trust?"
            ),
            criteria={
                "true": "It can validate or disqualify the trustworthiness of the primary evidence.",
                "false": "It cannot meaningfully qualify data quality or comparability.",
            },
        )
        questions[f"owner_{index}"] = Noul(
            instructions=(
                f"Judge candidates[{index}] for the owner role in anchored_goal. "
                "Could it identify an accountable team or delivery context?"
            ),
            criteria={
                "true": "It contains explicit ownership or routing context connected to the anchor.",
                "false": "It does not establish an accountable owner or delivery route.",
            },
        )
    return questions


def _scores(response: Any, candidates: list[ResourceDescriptor]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for index, resource in enumerate(candidates):
        ref = resource_ref(resource)
        result[ref] = {
            "global": float(response.nouls[f"global_{index}"].noul),
            "related": float(response.nouls[f"related_{index}"].noul),
            "diagnostic": float(response.nouls[f"diagnostic_{index}"].noul),
            "quality": float(response.nouls[f"quality_{index}"].noul),
            "owner": float(response.nouls[f"owner_{index}"].noul),
        }
    return result


def _select_bundles(
    candidates: list[ResourceDescriptor],
    scores: dict[str, dict[str, float]],
    anchor_ref: str,
) -> dict[str, list[str]]:
    refs = [resource_ref(resource) for resource in candidates]

    def top_by(signal: str, limit: int) -> list[str]:
        return [
            ref
            for ref in sorted(refs, key=lambda item: (-scores[item][signal], item))
            if ref != anchor_ref
        ][:limit]

    goal_only = top_by("global", GOAL_LIMIT)
    anchor_aware = top_by("related", GOAL_LIMIT)
    role_aware: list[str] = []
    for role in ROLE_NAMES:
        role_selected = 0
        for ref in sorted(refs, key=lambda item: (-scores[item][role], item)):
            if ref == anchor_ref or ref in role_aware:
                continue
            if scores[ref][role] < ROLE_THRESHOLD:
                break
            role_aware.append(ref)
            role_selected += 1
            if role_selected >= ROLE_TOP_K:
                break
    return {
        "goal_only": [anchor_ref, *goal_only],
        "anchor_aware": [anchor_ref, *anchor_aware],
        "role_aware": [anchor_ref, *role_aware],
    }


def _bundle_metrics(
    selected: list[str],
    *,
    expected_anchor: str,
    expected_group: set[str],
    acceptable: set[str],
) -> dict[str, Any]:
    selected_set = set(selected)
    group_hit = selected_set & expected_group
    return {
        "selected_count": len(selected),
        "expected_anchor_selected": expected_anchor in selected_set,
        "required_group_recall": len(group_hit) / len(expected_group) if expected_group else 1.0,
        "required_group_hits": sorted(group_hit),
        "acceptable_precision": (
            len(selected_set & acceptable) / len(selected_set) if selected_set else 0.0
        ),
        "unexpected_selected_refs": sorted(selected_set - acceptable),
    }


class LiveAblationJev:
    def __init__(self, api_key: str, timeout: float | None = None) -> None:
        from typesafe_sdk import AsyncTypeSafeClient

        self.client_type = AsyncTypeSafeClient
        self.api_key = api_key
        self.timeout = timeout or float(os.getenv("TYPESAFE_TIMEOUT_SECONDS", "30"))
        self.metrics = JudgerMetrics()

    async def judge(
        self,
        *,
        cold_start_goal: str,
        anchored_goal: str,
        anchor: ResourceDescriptor,
        context: ContextSnapshot,
        candidates: list[ResourceDescriptor],
    ) -> dict[str, dict[str, float]]:
        state = {
            "cold_start_goal": cold_start_goal,
            "anchored_goal": anchored_goal,
            "anchor_context": [_descriptor_payload(anchor)],
            "graph_context": context.model_dump(mode="json"),
            "candidates": [_descriptor_payload(resource) for resource in candidates],
        }
        questions = _question_set(len(candidates))
        async with self.client_type(api_key=self.api_key, timeout=self.timeout) as client:
            response = await client.system_one(state=state, questions=questions)
        self.metrics.record(response)
        return _scores(response, candidates)


def _representative_cases(retrieval_cases: list[Any]) -> list[Any]:
    """Bound live usage to one case per messy variant."""
    selected_cases = []
    seen_variants: set[str] = set()
    for retrieval_case in retrieval_cases:
        variant = retrieval_case.tags[-1]
        if "no-match" in retrieval_case.tags or variant in seen_variants:
            continue
        selected_cases.append(retrieval_case)
        seen_variants.add(variant)
    return selected_cases


async def run_trial(
    *,
    output: str | Path = DEFAULT_OUTPUT,
    decoys_per_adapter: int = 300,
    virtual_catalog_size: int = 100_000,
) -> dict[str, Any]:
    config, fixtures, _roster = build_scale_fixtures(DEFAULT_BASE_CONFIG)
    tenant_id = "northstar-outfitters"
    adapters, _records, catalog_stats = _descriptors_and_records(
        fixtures,
        decoys_per_adapter=decoys_per_adapter,
        virtual_catalog_size=virtual_catalog_size,
        tenant_id=tenant_id,
    )
    registry = SourceRegistry(adapters)
    _workflow_cases, retrieval_cases, _cards = _build_cases(
        config, fixtures, tenant_id=tenant_id
    )
    descriptor_map = {
        resource_ref(descriptor): descriptor
        for adapter in adapters
        for descriptor in adapter._descriptors
    }
    variants: list[dict[str, Any]] = []
    key = load_api_key()
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE is required")
    judger = LiveAblationJev(key)
    started = time.perf_counter()

    for retrieval_case in _representative_cases(retrieval_cases):
        variant = retrieval_case.tags[-1]
        domain = retrieval_case.tags[1]
        anchor_ref = _ref("superset", f"dashboard:northstar-scale-anchor-{_slug(domain)}")
        anchor = _anchor_descriptor(list(descriptor_map.values()), anchor_ref)
        catalog = await registry.search_resources(
            retrieval_case.goal,
            limit=48,
            authorized_tenants=[tenant_id],
        )
        # Keep the Jev candidate set fixed across all policies. Anchors are
        # always human-approved; adding the anchor does not give the policies
        # access to evaluator labels.
        candidate_map = {resource_ref(resource): resource for resource in catalog.resources}
        candidate_map[anchor_ref] = anchor
        candidates = [candidate_map[ref] for ref in sorted(candidate_map)]
        context = _graph_context(candidates, anchor_ref, domain)
        anchored_goal = (
            f"{retrieval_case.goal}\nHuman-approved anchor: {anchor.title}. "
            "Use the anchor and graph context to assemble related evidence."
        )
        scores = await judger.judge(
            cold_start_goal=retrieval_case.goal,
            anchored_goal=anchored_goal,
            anchor=anchor,
            context=context,
            candidates=candidates,
        )
        selected = _select_bundles(candidates, scores, anchor_ref)
        expected_group = set(retrieval_case.required_resource_groups[0])
        acceptable = set(retrieval_case.acceptable_resource_refs) | {anchor_ref}
        variants.append(
            {
                "variant": variant,
                "domain": domain,
                "goal": retrieval_case.goal,
                "anchor_ref": anchor_ref,
                "candidate_count": len(candidates),
                "catalog_total_count": catalog.total_count,
                "catalog_strategy": catalog.strategy,
                "graph_fact_count": len(context.facts),
                "scores": scores,
                "bundles": {
                    name: {
                        "refs": refs,
                        **_bundle_metrics(
                            refs,
                            expected_anchor=anchor_ref,
                            expected_group=expected_group,
                            acceptable=acceptable,
                        ),
                    }
                    for name, refs in selected.items()
                },
            }
        )
    elapsed = time.perf_counter() - started
    strategy_summary: dict[str, dict[str, float]] = {}
    for strategy in ("goal_only", "anchor_aware", "role_aware"):
        metrics = [item["bundles"][strategy] for item in variants]
        strategy_summary[strategy] = {
            "mean_required_group_recall": sum(item["required_group_recall"] for item in metrics)
            / len(metrics),
            "mean_acceptable_precision": sum(item["acceptable_precision"] for item in metrics)
            / len(metrics),
            "full_group_cases": sum(item["required_group_recall"] == 1.0 for item in metrics),
            "anchor_cases": sum(item["expected_anchor_selected"] for item in metrics),
            "mean_selected_count": sum(item["selected_count"] for item in metrics) / len(metrics),
        }
    report = {
        "trial": "northstar-retrieval-ablation-jev-only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluator": "jev-latest",
        "jev_only": True,
        "policy": {
            "candidate_pool_fixed": True,
            "candidate_pool_limit": 48,
            "goal_limit": GOAL_LIMIT,
            "role_threshold": ROLE_THRESHOLD,
            "role_top_k": ROLE_TOP_K,
            "roles": list(ROLE_NAMES),
        },
        "scale": {
            "company": config["company"],
            "variant_count": len(variants),
            "variants": [item["variant"] for item in variants],
            "catalog": catalog_stats,
        },
        "strategy_summary": strategy_summary,
        "variants": variants,
        "jev": {
            "requests": judger.metrics.requests,
            "input_tokens": judger.metrics.input_tokens,
            "output_tokens": judger.metrics.output_tokens,
            "questions_per_request": len(_question_set(len(variants[0]["scores"])))
            if variants
            else 0,
        },
        "runtime": {"elapsed_seconds": round(elapsed, 3)},
        "evaluation_boundary": (
            "Expected resource groups, acceptable refs, and variant names are used only "
            "after Jev returns. The request contains goals, human-approved anchor metadata, "
            "adapter descriptors, and lineage-derived graph context."
        ),
        "limitations": [
            "This is seven representative Northstar variants, not a production customer replay.",
            "The role-aware policy is an evaluation candidate, not a committed product threshold.",
            "Graph context is lineage-derived; richer ownership and incident edges need separate adapters.",
        ],
    }
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Northstar retrieval ablation",
        "",
        "A single Jev request per messy variant compares three bundle policies over the same adapter-owned candidate set.",
        "",
        "| Strategy | Mean group recall | Mean acceptable precision | Full-group cases | Mean selected |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, metrics in report["strategy_summary"].items():
        lines.append(
            f"| {name} | {metrics['mean_required_group_recall']:.3f} | "
            f"{metrics['mean_acceptable_precision']:.3f} | {metrics['full_group_cases']}/"
            f"{report['scale']['variant_count']} | {metrics['mean_selected_count']:.1f} |"
        )
    lines.extend(
        [
            "",
            f"Jev requests: **{report['jev']['requests']}**; input tokens: **{report['jev']['input_tokens']:,}**; output tokens: **{report['jev']['output_tokens']:,}**.",
            "",
            "## Interpretation",
            "",
            "Goal-only ranking measures cold-start relevance. Anchor-aware ranking measures whether the same evidence is related to a human-approved starting point. Role-aware assembly tests whether a compact bundle can cover distinct evidence jobs without sending every same-domain source downstream.",
            "",
            "The labels are evaluator-only and are not part of the Jev state. This trial therefore measures a retrieval and bundle-assembly design, not Jev's ability to invent missing business context.",
            "",
        ]
    )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--decoys-per-adapter", type=int, default=300)
    parser.add_argument("--virtual-catalog-size", type=int, default=100_000)
    return parser


async def _main(args: argparse.Namespace) -> None:
    report = await run_trial(
        output=args.output,
        decoys_per_adapter=args.decoys_per_adapter,
        virtual_catalog_size=args.virtual_catalog_size,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(_main(_parser().parse_args()))
