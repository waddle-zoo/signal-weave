"""Run a small Jev-only Amazon DocumentDB performance monitoring trial.

The fixture models the boundary a real deployment would use: CloudWatch owns
normalized metrics, while deployment, incident, runbook, and ownership systems
provide related context. Jev ranks a bounded expansion bundle and judges the
resulting typed evidence. Expected labels remain evaluator-only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from evaluations.generalized_readiness_trial import RecordingJev
from signalweave.engine import InsightEngine
from signalweave.models import (
    CatalogSearchPage,
    ContextSnapshot,
    InsightCard,
    PrincipalContext,
    ResourceDescriptor,
    ResourceSnapshot,
    RetrievalMode,
    SourceRef,
)
from signalweave.onboarding import InsightAuthoringService
from signalweave.sources import SourceRegistry
from signalweave.typesafe_adapter import JevJudger, load_api_key

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = REPO_ROOT / "evaluations" / "data" / "documentdb-performance.json"
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "documentdb-performance" / "report.json"


class DocumentDBFixtureAdapter:
    """Native-style bounded adapter over one editable DocumentDB fixture."""

    def __init__(self, name: str, records: list[dict[str, Any]]) -> None:
        self.name = name
        self._descriptors = {
            str(record["descriptor"]["resource"]): ResourceDescriptor.model_validate(
                record["descriptor"]
            )
            for record in records
        }
        self._snapshots = {
            str(record["snapshot"]["resource"]): ResourceSnapshot.model_validate(
                record["snapshot"]
            )
            for record in records
        }
        self.search_calls = 0
        self.authorize_calls = 0
        self.list_calls = 0

    async def list_resources(self) -> list[ResourceDescriptor]:
        self.list_calls += 1
        return list(self._descriptors.values())

    async def search_resources(
        self,
        query: str,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> CatalogSearchPage:
        del query, cursor
        self.search_calls += 1
        resources = list(self._descriptors.values())[:limit]
        return CatalogSearchPage(
            resources=resources,
            total_count=len(self._descriptors),
            has_more=len(resources) < len(self._descriptors),
            provider=f"{self.name}-native-index",
            strategy="native-index",
        )

    async def authorize(
        self,
        source: SourceRef,
        *,
        authorized_tenants: Iterable[str] | None = None,
    ) -> ResourceDescriptor | None:
        self.authorize_calls += 1
        descriptor = self._descriptors.get(source.resource)
        if descriptor is None:
            return None
        allowed = set(authorized_tenants or [])
        if allowed and descriptor.contract.tenant_id not in allowed:
            return None
        return descriptor

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        snapshot = self._snapshots[source.resource]
        return snapshot.model_copy(update={"source_key": source.key})


def load_fixture(path: str | Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported DocumentDB fixture schema")
    return payload


def _build_registry(fixture: dict[str, Any]) -> tuple[SourceRegistry, list[DocumentDBFixtureAdapter]]:
    records_by_adapter: dict[str, list[dict[str, Any]]] = {}
    for record in fixture["resources"]:
        records_by_adapter.setdefault(str(record["descriptor"]["adapter"]), []).append(record)
    adapters = [
        DocumentDBFixtureAdapter(name, records_by_adapter[name])
        for name in sorted(records_by_adapter)
    ]
    return SourceRegistry(adapters), adapters


async def run_trial(
    *,
    fixture_path: str | Path = DEFAULT_FIXTURE,
    output: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    fixture = load_fixture(fixture_path)
    key = load_api_key()
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE is required")

    registry, adapters = _build_registry(fixture)
    principal = PrincipalContext.model_validate(fixture["principal"])
    recording = RecordingJev(JevJudger(api_key=key))
    engine = InsightEngine(judger=recording, registry=registry)
    authoring = InsightAuthoringService(
        registry=registry,
        engine=engine,
        max_candidates=40,
        related_source_limit=6,
        principal=principal,
    )
    card = InsightCard.model_validate(fixture["card"])
    context = ContextSnapshot.model_validate(fixture["context"])

    started = time.perf_counter()
    bundle = await authoring.resolve_bundle(card, context=context, principal=principal)
    expanded_card = card.model_copy(
        update={
            "sources": bundle.selected_sources,
            "retrieval_mode": RetrievalMode.FIXED,
        }
    )
    resources = await registry.resolve(
        expanded_card.sources,
        authorized_tenants=[principal.tenant_id],
    )
    run = await engine.evaluate(
        expanded_card,
        resources=resources,
        context_override=context,
        principal=principal,
    )
    elapsed = time.perf_counter() - started

    expected_related = set(fixture["expected_related_refs"])
    selected_related = {match.ref for match in bundle.related_matches}
    missing_related = sorted(expected_related - selected_related)
    related_recall = (
        len(expected_related & selected_related) / len(expected_related)
        if expected_related
        else 1.0
    )
    label_keys = {"expected_outcome", "expected_related_refs", "missing_related"}
    call_keys = [key for call in recording.calls for key in call.get("keys", [])]
    telemetry = {
        adapter.name: {
            "search_calls": adapter.search_calls,
            "authorize_calls": adapter.authorize_calls,
            "full_scan_calls": adapter.list_calls,
        }
        for adapter in adapters
    }
    result = run.result
    report = {
        "trial": "documentdb-performance-jev-only",
        "fixture": str(Path(fixture_path)),
        "evaluator": recording.name,
        "company_boundary": fixture["tenant_id"],
        "card": {
            "id": card.id,
            "anchor_sources": [source.key for source in card.sources],
            "expanded_sources": [source.key for source in expanded_card.sources],
        },
        "retrieval": {
            "candidate_count": bundle.candidate_count,
            "candidate_limit": bundle.candidate_limit,
            "candidate_strategy": bundle.candidate_strategy,
            "selected_related_refs": sorted(selected_related),
            "expected_related_refs": sorted(expected_related),
            "missing_related_refs": missing_related,
            "related_source_recall": related_recall,
            "evaluator": bundle.evaluator,
            "warnings": bundle.warnings,
        },
        "workflow": {
            "expected_outcome": fixture["expected_outcome"],
            "actual_outcome": result.outcome.value,
            "outcome_matches": result.outcome.value == fixture["expected_outcome"],
            "confidence": result.confidence,
            "probabilities": result.probabilities,
            "summary": result.summary,
            "rationale": result.rationale,
            "source_keys": result.source_keys,
            "observation_count": len(result.observations),
            "evidence_count": len(result.evidence),
            "evidence_findings": [item.model_dump(mode="json") for item in result.evidence_findings],
        },
        "jev": {
            "requests": recording.metrics.requests,
            "input_tokens": recording.metrics.input_tokens,
            "output_tokens": recording.metrics.output_tokens,
            "methods": [call["method"] for call in recording.calls],
        },
        "runtime": {"elapsed_seconds": round(elapsed, 3)},
        "adapter_telemetry": telemetry,
        "adversarial_review_inputs": {
            "labels_sent_to_jev": bool(set(call_keys) & label_keys),
            "leaked_label_keys": sorted(set(call_keys) & label_keys),
            "native_full_scan_calls": sum(item["full_scan_calls"] for item in telemetry.values()),
            "authorized_tenant": principal.tenant_id,
        },
        "limitations": [
            "CloudWatch, deployment, incident, runbook, and ownership records are synthetic fixtures.",
            "The card is human-authored; this trial tests retrieval and typed execution, not card authoring.",
            "Delivery is represented in the typed result but external notification is disabled.",
        ],
    }
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    retrieval = report["retrieval"]
    workflow = report["workflow"]
    review = report["adversarial_review_inputs"]
    return "\n".join(
        [
            "# DocumentDB performance Jev-only trial",
            "",
            "This trial models CloudWatch metrics plus deployment, incident, runbook, and ownership context.",
            "",
            f"- Related-source recall: **{retrieval['related_source_recall']:.3f}**",
            f"- Outcome: **{workflow['actual_outcome']}** (expected `{workflow['expected_outcome']}`)",
            f"- Confidence: **{workflow['confidence'] if workflow['confidence'] is not None else 'none'}**",
            f"- Jev calls: **{report['jev']['requests']}**",
            f"- Full catalog scans: **{review['native_full_scan_calls']}**",
            f"- Label leakage: **{', '.join(review['leaked_label_keys']) or 'none'}**",
            "",
            "## Retrieved context",
            "",
            *[f"- `{ref}`" for ref in retrieval["selected_related_refs"]],
            "",
            "## Typed judgment",
            "",
            workflow["summary"],
            "",
            workflow["rationale"],
            "",
        ]
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


async def _main(args: argparse.Namespace) -> None:
    report = await run_trial(fixture_path=args.fixture, output=args.output)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(_main(_parser().parse_args()))
