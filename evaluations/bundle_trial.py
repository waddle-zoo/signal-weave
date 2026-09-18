"""Live Jev trial for dynamic evidence-bundle expansion.

The human-approved anchor is supplied independently of Jev. The expected related
source is used only after the request to score retrieval; it is never included in
the card, goal, or Jev state. This measures the new retrieval seam rather than the
downstream insight decision.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from evaluations.discovery_trial import CatalogAdapter, build_cases
from signalweave.engine import InsightEngine
from signalweave.models import InsightCard, RetrievalMode, SourceRef
from signalweave.onboarding import InsightAuthoringService
from signalweave.sources import SourceRegistry
from signalweave.typesafe_adapter import JevJudger, load_api_key


async def run_trial(count: int, output: Path) -> dict[str, Any]:
    cases, resources = build_cases(count)
    key = load_api_key()
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE is required")
    judger = JevJudger(api_key=key)
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for case in cases:
        adapters = [
            CatalogAdapter(
                name,
                [resource for resource in resources if resource.adapter == name],
            )
            for name in sorted({resource.adapter for resource in resources})
        ]
        registry = SourceRegistry(adapters, authorized_tenants=[case.tenant_id])
        service = InsightAuthoringService(
            registry=registry,
            engine=InsightEngine(judger=judger, registry=registry),
            max_candidates=48,
            related_source_limit=4,
        )
        anchor_ref, expected_related_ref = case.expected_refs
        anchor = next(
            resource
            for resource in resources
            if f"{resource.adapter}|{resource.resource}" == anchor_ref
        )
        card = InsightCard(
            id=f"bundle-{case.case_id}",
            title=f"{case.case_id} context",
            what_to_watch=case.goal,
            why_watch="Use the approved anchor and related evidence to decide what needs attention.",
            sources=[
                SourceRef(
                    key="human-anchor",
                    adapter=anchor.adapter,
                    resource=anchor.resource,
                    label=anchor.title,
                )
            ],
            retrieval_mode=RetrievalMode.EXPAND,
        )
        bundle = await service.resolve_bundle(card)
        related_refs = [match.ref for match in bundle.related_matches]
        rows.append(
            {
                "case_id": case.case_id,
                "tenant_id": case.tenant_id,
                "anchor_ref": anchor_ref,
                "expected_related_ref": expected_related_ref,
                "related_refs": related_refs,
                "expected_related_selected": expected_related_ref in related_refs,
                "anchor_preserved": bundle.anchor_source_keys == ["human-anchor"]
                and bundle.selected_sources[0].resource == anchor.resource,
                "wrong_tenant_returned": any(
                    match.contract.tenant_id != case.tenant_id
                    for match in bundle.related_matches + bundle.omitted_matches
                ),
                "selected_limit_respected": len(bundle.related_matches)
                <= service.related_source_limit,
                "truncated": bundle.truncated,
                "warnings": bundle.warnings,
            }
        )
    elapsed = time.perf_counter() - started
    report = {
        "evaluator": judger.name,
        "cases": len(rows),
        "resources_before_auth_filter": len(resources),
        "expected_related_selected": sum(row["expected_related_selected"] for row in rows),
        "anchor_preserved": sum(row["anchor_preserved"] for row in rows),
        "wrong_tenant_returned": sum(row["wrong_tenant_returned"] for row in rows),
        "selected_limit_respected": sum(row["selected_limit_respected"] for row in rows),
        "requests": judger.metrics.requests,
        "input_tokens": judger.metrics.input_tokens,
        "output_tokens": judger.metrics.output_tokens,
        "elapsed_seconds": round(elapsed, 3),
        "labels_sent_to_jev": False,
        "human_anchor_supplied_to_jev": True,
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    output.with_suffix(".md").write_text(
        "# SignalWeave evidence-bundle trial\n\n"
        f"Evaluator: `{judger.name}`; cases: **{len(rows)}**; resources before auth filtering: **{len(resources)}**.\n\n"
        "| Metric | Result |\n| --- | ---: |\n"
        f"| Expected related source selected | {report['expected_related_selected']} / {len(rows)} |\n"
        f"| Human anchor preserved | {report['anchor_preserved']} / {len(rows)} |\n"
        f"| Wrong-tenant sources returned | {report['wrong_tenant_returned']} / {len(rows)} |\n"
        f"| Related-source limit respected | {report['selected_limit_respected']} / {len(rows)} |\n\n"
        "The human anchor was provided before retrieval. Expected related refs were "
        "generated independently and were not sent to Jev.\n"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=24)
    parser.add_argument("--output", type=Path, default=Path("artifacts/bundle-trial.json"))
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_trial(args.cases, args.output)), indent=2))


if __name__ == "__main__":
    main()
