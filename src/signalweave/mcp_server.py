from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from .bootstrap import BootstrapManifest, BootstrapService
from .evaluation import (
    CardEvaluationCase,
    CardEvaluationThresholds,
    CardWorkflowEvaluator,
)
from .models import (
    CertificationRecord,
    ContextSnapshot,
    DecisionFeedback,
    DecisionFeedbackKind,
    DecisionReceipt,
    DeliveryMethod,
    InsightCard,
    InsightCardStatus,
    InvestigationMode,
    MetricQueryCard,
    OnboardingCorrection,
    OnboardingCorrectionKind,
    Outcome,
    PrincipalContext,
    QueryCardStatus,
    ReceiptStatus,
    RetrievalMode,
    SourceRef,
)
from .onboarding import InsightAuthoringService, proposal_summary
from .query_planner import QueryWindow, compile_query, plan_query
from .retrieval_quality import (
    RetrievalQualityCase,
    RetrievalQualityEvaluator,
    RetrievalQualityThresholds,
)
from .runtime import Runtime, build_runtime
from .store import (
    InMemoryCertificationReportStore,
    InMemoryDecisionFeedbackStore,
    InMemoryDecisionReceiptStore,
    JsonMetricQueryCardStore,
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "insight"


def _evaluation_fingerprint(
    card: InsightCard,
    *,
    actor: str,
    context: ContextSnapshot | None,
) -> str:
    payload = {
        "card_id": card.id,
        "card_version": card.version,
        "actor": actor or "mcp-client",
        "context": (
            context.model_dump(mode="json", exclude={"captured_at"}) if context else None
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_mcp(
    runtime: Runtime | None = None,
    *,
    principal_resolver: Callable[[Context], PrincipalContext] | None = None,
) -> FastMCP:
    runtime = runtime or build_runtime()
    authoring = InsightAuthoringService(
        runtime.sources, runtime.engine, principal=runtime.principal
    )
    metric_query_store = runtime.metric_query_store or JsonMetricQueryCardStore(
        os.getenv("METRIC_QUERY_CARD_STORE", "data/metric-query-cards.json")
    )
    decision_receipts = runtime.decision_receipts or InMemoryDecisionReceiptStore()
    decision_feedback = runtime.decision_feedback or InMemoryDecisionFeedbackStore()
    certification_reports = runtime.certification_reports or InMemoryCertificationReportStore()
    idempotency_locks: dict[str, asyncio.Lock] = {}
    mcp = FastMCP("signal-weave")

    def request_principal(ctx: Context | None) -> PrincipalContext | None:
        """Resolve a trusted gateway principal without accepting tool input as identity."""
        if principal_resolver is None:
            return runtime.principal
        if ctx is None:
            raise RuntimeError(
                "request-scoped principal resolution requires an MCP request context"
            )
        principal = principal_resolver(ctx)
        if principal is None:
            raise RuntimeError("the identity gateway did not provide a principal")
        return principal

    def assert_card_scope(card: InsightCard, principal: PrincipalContext | None) -> None:
        if principal is None:
            return
        if card.principal_tenant != principal.tenant_id:
            raise ValueError(
                "insight card is outside the authenticated principal tenant; "
                "rediscover or create it under the current principal"
            )

    def get_scoped_card(card_id: str, principal: PrincipalContext | None) -> InsightCard:
        card = runtime.card_store.get_card(card_id)
        assert_card_scope(card, principal)
        return card

    async def context_for_card(
        card: InsightCard,
        context: ContextSnapshot | None,
        principal: PrincipalContext | None,
    ) -> ContextSnapshot | None:
        """Resolve trusted deployment context without trusting tool payloads."""
        if context is not None:
            return context
        provider = runtime.context_provider or runtime.engine.context_provider
        if provider is None:
            return None
        try:
            resources = await runtime.sources.resolve(
                card.sources,
                authorized_tenants=[principal.tenant_id] if principal else None,
            )
            return await provider.get_context(card, resources)
        except Exception as error:  # noqa: BLE001 - context is visible but optional
            return ContextSnapshot(
                provider=provider.name,
                version="unavailable",
                trust="unverified",
                warnings=[f"Context provider failed: {type(error).__name__}: {error}"],
            )

    def persist_certification(
        *,
        kind: str,
        subject_id: str,
        tenant_id: str,
        subject_version: str,
        report: dict[str, Any],
    ) -> CertificationRecord:
        report_id = str(report.get("evaluation_id") or report.get("manifest_name") or uuid4().hex)
        record = CertificationRecord(
            report_id=f"{kind}:{subject_id}:{report_id}:{uuid4().hex[:12]}",
            kind=kind,  # type: ignore[arg-type]
            subject_id=subject_id,
            tenant_id=tenant_id,
            subject_version=subject_version,
            status=str(report.get("status", "blocked")),  # type: ignore[arg-type]
            dataset_ids=[str(item) for item in report.get("dataset_ids", [])],
            input_digest=str(report.get("input_digest", "")),
            label_digest=str(report.get("label_digest", "")),
            report=report,
        )
        certification_reports.save(record)
        return record

    def append_onboarding_review(
        card: InsightCard, review: Any
    ) -> InsightCard:
        history = [*card.onboarding_review_history, review][-20:]
        return card.model_copy(
            update={
                "onboarding_review": review,
                "onboarding_review_history": history,
            }
        )

    async def prepare_insight_card(
        card: InsightCard,
        context: ContextSnapshot | None = None,
        *,
        principal: PrincipalContext | None = None,
    ) -> tuple[InsightCard, Any]:
        """Resolve optional related sources without mutating the stored card."""
        bundle = await authoring.resolve_bundle(card, context, principal=principal)
        expanded = card
        if [source.model_dump(mode="json") for source in bundle.selected_sources] != [
            source.model_dump(mode="json") for source in card.sources
        ]:
            expanded = card.model_copy(
                update={"sources": bundle.selected_sources, "compiled_plan": None}
            )
        return expanded, bundle

    async def evaluate_approved_card_once(
        card_id: str,
        *,
        idempotency_key: str | None,
        actor: str,
        context: ContextSnapshot | None = None,
        principal: PrincipalContext | None = None,
    ) -> dict[str, Any]:
        card = runtime.card_store.get_card(card_id)
        assert_card_scope(card, principal)
        if card.status != InsightCardStatus.APPROVED:
            raise ValueError(
                f"Insight card {card_id} is a draft; simulate it, then approve it before evaluation"
            )
        key = (idempotency_key or f"manual:{card_id}:{uuid4().hex}").strip()
        if not key:
            raise ValueError("idempotency_key must not be empty")
        context = await context_for_card(card, context, principal)
        fingerprint = _evaluation_fingerprint(card, actor=actor, context=context)
        existing = decision_receipts.get_by_idempotency_key(key)
        if existing is not None:
            if existing.request_fingerprint and existing.request_fingerprint != fingerprint:
                raise ValueError(
                    "idempotency key is already bound to a different card, actor, version, "
                    "or context"
                )
            if existing.status == ReceiptStatus.PREPARED:
                raise ValueError("idempotency key is already being evaluated; retry shortly")
            return {
                "receipt": existing.model_copy(update={"status": ReceiptStatus.REPLAYED}).model_dump(
                    mode="json"
                ),
                "replayed": True,
                "result": existing.result,
            }
        prepared = DecisionReceipt(
            receipt_id=f"receipt-{uuid4().hex}",
            idempotency_key=key,
            request_fingerprint=fingerprint,
            card_id=card.id,
            card_version=card.version,
            actor=actor or "mcp-client",
            context_provider=context.provider if context else None,
            context_version=context.version if context else None,
            status=ReceiptStatus.PREPARED,
        )
        if not decision_receipts.claim(prepared):
            existing = decision_receipts.get_by_idempotency_key(key)
            if existing is not None and existing.request_fingerprint and existing.request_fingerprint != fingerprint:
                raise ValueError(
                    "idempotency key is already bound to a different card, actor, version, "
                    "or context"
                )
            if existing is not None and existing.status == ReceiptStatus.PREPARED:
                raise ValueError("idempotency key is already being evaluated; retry shortly")
            if existing is None:
                raise RuntimeError("unable to claim idempotency key")
            return {
                "receipt": existing.model_copy(update={"status": ReceiptStatus.REPLAYED}).model_dump(
                    mode="json"
                ),
                "replayed": True,
                "result": existing.result,
            }
        try:
            evaluation_card, bundle = await prepare_insight_card(
                card, context, principal=principal
            )
            run = await runtime.engine.evaluate(
                evaluation_card, context_override=context, principal=principal
            )
            evaluated_result = run.result.model_copy(update={"retrieval": bundle})
            result = evaluated_result.model_dump(mode="json")
        except Exception as error:  # noqa: BLE001 - persist failed claims for replay safety
            decision_receipts.save(
                prepared.model_copy(
                    update={
                        "status": ReceiptStatus.FAILED,
                        "outcome": Outcome.INSUFFICIENT_DATA,
                        "result": {"error": f"{type(error).__name__}: {error}"},
                    }
                )
            )
            raise
        receipt = prepared.model_copy(
            update={
                "status": ReceiptStatus.DELIVERY_DISABLED,
                "outcome": run.result.outcome,
                "delivery_enabled": False,
                "delivery_method_keys": [method.key for method in run.result.delivery_methods],
                "result": result,
            }
        )
        decision_receipts.save(receipt)
        return {
            "receipt": receipt.model_dump(mode="json"),
            "replayed": False,
            "card": run.card.model_dump(mode="json"),
            "retrieval": bundle.model_dump(mode="json"),
            "resources": [resource.model_dump(mode="json") for resource in run.resources],
            "plan": run.plan.model_dump(mode="json"),
            "result": result,
        }

    async def evaluate_approved_card(
        card_id: str,
        *,
        idempotency_key: str | None,
        actor: str,
        context: ContextSnapshot | None = None,
        principal: PrincipalContext | None = None,
    ) -> dict[str, Any]:
        key = (idempotency_key or f"manual:{card_id}:{uuid4().hex}").strip()
        if not key:
            raise ValueError("idempotency_key must not be empty")
        lock = idempotency_locks.setdefault(key, asyncio.Lock())
        async with lock:
            return await evaluate_approved_card_once(
                card_id,
                idempotency_key=key,
                actor=actor,
                context=context,
                principal=principal,
            )

    async def selected_query_sources(selected_sources: list[dict[str, Any]]) -> list[SourceRef]:
        if not selected_sources:
            raise ValueError("metric query cards require at least one selected source")
        catalog = {
            f"{resource.adapter}|{resource.resource}": resource
            for resource in await runtime.sources.list_resources()
        }
        refs: list[SourceRef] = []
        for index, item in enumerate(selected_sources):
            ref = str(item.get("ref") or "")
            if "|" not in ref:
                adapter = str(item.get("adapter") or "")
                resource = str(item.get("resource") or "")
                ref = f"{adapter}|{resource}"
            descriptor = catalog.get(ref)
            if descriptor is None:
                raise ValueError(f"selected metric source is not in the authorized catalog: {ref}")
            adapter, _, resource = ref.partition("|")
            refs.append(
                SourceRef(
                    key=str(item.get("key") or f"source-{index + 1}-{_slug(resource)}"),
                    adapter=adapter,
                    resource=resource,
                    label=str(item.get("label") or descriptor.title),
                    parameters=item.get("parameters") or {},
                    required=bool(item.get("required", True)),
                )
            )
        return refs

    @mcp.tool()
    async def list_resources(
        adapter: str | None = None, ctx: Context | None = None
    ) -> list[dict[str, Any]]:
        """List safe, inspectable resources exposed by installed source adapters."""
        principal = request_principal(ctx)
        resources = await runtime.sources.list_resources(
            adapter,
            authorized_tenants=[principal.tenant_id] if principal else None,
        )
        return [resource.model_dump(mode="json") for resource in resources]

    @mcp.tool()
    async def inspect_resource(
        adapter: str,
        resource: str,
        label: str | None = None,
        parameters: dict[str, Any] | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Inspect one source resource without making an insight decision."""
        source = SourceRef(
            key=f"inspect-{_slug(adapter)}-{_slug(resource)}",
            adapter=adapter,
            resource=resource,
            label=label or resource,
            parameters=parameters or {},
        )
        principal = request_principal(ctx)
        snapshot = await runtime.sources.inspect(
            source,
            authorized_tenants=[principal.tenant_id] if principal else None,
        )
        return snapshot.model_dump(mode="json")

    @mcp.tool()
    async def discover_insight_sources(
        goal: str,
        adapter: str | None = None,
        limit: int = 10,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Find bounded, Jev-ranked source candidates for an insight goal."""
        discovery = await authoring.discover(
            goal,
            adapter=adapter,
            limit=limit,
            principal=request_principal(ctx),
        )
        return discovery.model_dump(mode="json")

    @mcp.tool()
    async def assess_bootstrap(
        manifest: dict[str, Any], ctx: Context | None = None
    ) -> dict[str, Any]:
        """Check whether installed adapters are ready for bounded card onboarding.

        The caller supplies real probe goals and capability requirements. This
        performs read-only catalog and sample-inspection checks; it does not
        import data, create cards, or change adapter permissions.
        """
        principal = request_principal(ctx)
        bootstrap_manifest = BootstrapManifest.model_validate(manifest)
        report = await BootstrapService(runtime.sources).assess(
            bootstrap_manifest, principal=principal
        )
        payload = report.model_dump(mode="json")
        record = persist_certification(
            kind="bootstrap",
            subject_id=bootstrap_manifest.tenant_id,
            tenant_id=bootstrap_manifest.tenant_id,
            subject_version=bootstrap_manifest.name,
            report=payload,
        )
        return {**payload, "certification_report_id": record.report_id}

    @mcp.tool()
    async def evaluate_card_workflow(
        card_id: str,
        cases: list[dict[str, Any]],
        thresholds: dict[str, Any] | None = None,
        max_concurrency: int = 8,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Replay one stored card against owner-labeled snapshots before promotion.

        Each case contains ``id``, ``resources``, ``expected_outcome`` and any
        optional evidence/retrieval labels. Labels stay in the evaluator and
        are never included in the Jev state. Historical snapshots are supplied
        by the caller; production delivery is not performed by this tool.
        """
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        if not cases:
            raise ValueError("at least one labeled evaluation case is required")
        parsed_cases = [
            CardEvaluationCase.model_validate({**case, "card": card}) for case in cases
        ]
        report = await CardWorkflowEvaluator(
            runtime.engine, max_concurrency=max_concurrency
        ).evaluate(
            parsed_cases,
            thresholds=(
                CardEvaluationThresholds.model_validate(thresholds)
                if thresholds is not None
                else None
            ),
        )
        payload = report.model_dump(mode="json")
        record = persist_certification(
            kind="card_workflow",
            subject_id=card.id,
            tenant_id=card.principal_tenant or (principal.tenant_id if principal else "deployment"),
            subject_version=str(card.version),
            report=payload,
        )
        return {**payload, "certification_report_id": record.report_id}

    @mcp.tool()
    async def evaluate_retrieval_quality(
        cases: list[dict[str, Any]],
        thresholds: dict[str, Any] | None = None,
        max_concurrency: int = 8,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Measure adapter candidate recall and Jev source recommendations.

        ``expected_resource_refs`` are evaluator-only owner labels. They are
        never copied into the discovery goal or candidate state sent to Jev.
        """
        principal = request_principal(ctx)
        if not cases:
            raise ValueError("at least one labeled retrieval case is required")
        principal_payload = principal.model_dump(mode="json") if principal else None
        parsed_cases = [
            RetrievalQualityCase.model_validate({**case, "principal": principal_payload})
            for case in cases
        ]
        report = await RetrievalQualityEvaluator(
            authoring, max_concurrency=max_concurrency
        ).evaluate(
            parsed_cases,
            thresholds=(
                RetrievalQualityThresholds.model_validate(thresholds)
                if thresholds is not None
                else None
            ),
        )
        payload = report.model_dump(mode="json")
        record = persist_certification(
            kind="retrieval_quality",
            subject_id="retrieval-catalog",
            tenant_id=principal.tenant_id if principal else "deployment",
            subject_version=principal.tenant_id if principal else "deployment",
            report=payload,
        )
        return {**payload, "certification_report_id": record.report_id}

    @mcp.tool()
    def get_certification_report(
        report_id: str, ctx: Context | None = None
    ) -> dict[str, Any]:
        """Return one durable bootstrap or evaluation report by ID."""
        record = certification_reports.get(report_id)
        principal = request_principal(ctx)
        if principal is not None and record.tenant_id != principal.tenant_id:
            raise ValueError("certification report is outside the authenticated principal tenant")
        return record.model_dump(mode="json")

    @mcp.tool()
    def list_certification_reports(
        subject_id: str | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        """List durable certification evidence for an optional card or tenant."""
        principal = request_principal(ctx)
        records = certification_reports.list(subject_id=subject_id)
        if principal is not None:
            records = [record for record in records if record.tenant_id == principal.tenant_id]
        return {
            "reports": [record.model_dump(mode="json") for record in records],
            "count": len(records),
        }

    @mcp.tool()
    def get_enterprise_readiness(ctx: Context | None = None) -> dict[str, Any]:
        """Summarize the tenant's bootstrap, card, and certification gates.

        This is an evidence index for a caller-owned UI or agent, not a claim
        that SignalWeave is enterprise-ready. A clean result means the tenant
        has the minimum proof to begin a controlled shadow deployment.
        """
        principal = request_principal(ctx)
        tenant_id = principal.tenant_id if principal else "deployment"
        records = certification_reports.list()
        if principal is not None:
            records = [record for record in records if record.tenant_id == tenant_id]
        cards = [
            card
            for card in runtime.card_store.list_cards()
            if principal is None or card.principal_tenant == tenant_id
        ]

        def latest(*, kind: str, subject_id: str | None = None) -> CertificationRecord | None:
            matching = [
                record
                for record in records
                if record.kind == kind
                and (subject_id is None or record.subject_id == subject_id)
            ]
            return max(matching, key=lambda record: record.created_at) if matching else None

        gates: list[dict[str, str]] = []
        bootstrap = latest(kind="bootstrap", subject_id=tenant_id)
        if bootstrap is None:
            gates.append(
                {
                    "code": "bootstrap-certification-missing",
                    "severity": "blocked",
                    "message": "No source-boundary bootstrap report exists for this tenant.",
                }
            )
        elif bootstrap.status != "approved" and bootstrap.report.get("status") != "ready":
            gates.append(
                {
                    "code": "bootstrap-needs-review",
                    "severity": "blocked" if bootstrap.status == "blocked" else "review",
                    "message": f"Bootstrap report is {bootstrap.status}; resolve its warnings or blockers.",
                }
            )

        if not cards:
            gates.append(
                {
                    "code": "no-cards",
                    "severity": "review",
                    "message": "Create and review at least one insight card before shadow deployment.",
                }
            )

        card_summaries: list[dict[str, Any]] = []
        for card in sorted(cards, key=lambda item: item.id):
            review_status = (
                card.onboarding_review.readiness_status
                if card.onboarding_review is not None
                else "missing"
            )
            workflow = latest(kind="card_workflow", subject_id=card.id)
            summary = {
                "card_id": card.id,
                "version": card.version,
                "status": card.status.value,
                "onboarding_status": review_status,
                "workflow_certification": (
                    {
                        "report_id": workflow.report_id,
                        "status": workflow.status,
                        "created_at": workflow.created_at.isoformat(),
                    }
                    if workflow
                    else None
                ),
            }
            card_summaries.append(summary)
            if review_status == "blocked":
                gates.append(
                    {
                        "code": "card-onboarding-blocked",
                        "severity": "blocked",
                        "message": f"Card {card.id} has blocking onboarding conditions.",
                    }
                )
            elif card.status != InsightCardStatus.APPROVED or review_status != "ready_for_approval":
                gates.append(
                    {
                        "code": "card-needs-approval",
                        "severity": "review",
                        "message": f"Card {card.id} is not approved for shadow evaluation.",
                    }
                )
            if workflow is None:
                gates.append(
                    {
                        "code": "workflow-certification-missing",
                        "severity": "review",
                        "message": f"Card {card.id} has no owner-labeled workflow certification.",
                    }
                )
            elif workflow.status != "approved":
                gates.append(
                    {
                        "code": "workflow-certification-needs-review",
                        "severity": "review",
                        "message": f"Card {card.id} workflow certification is {workflow.status}.",
                    }
                )

        retrieval = latest(kind="retrieval_quality", subject_id="retrieval-catalog")
        if retrieval is None:
            gates.append(
                {
                    "code": "retrieval-certification-missing",
                    "severity": "review",
                    "message": "No tenant retrieval-quality certification exists.",
                }
            )
        elif retrieval.status != "approved":
            gates.append(
                {
                    "code": "retrieval-certification-needs-review",
                    "severity": "review",
                    "message": f"Retrieval certification is {retrieval.status}.",
                }
            )

        status = (
            "blocked"
            if any(gate["severity"] == "blocked" for gate in gates)
            else "needs_review"
            if gates
            else "ready_for_shadow"
        )
        return {
            "tenant_id": tenant_id,
            "status": status,
            "context_provider": {
                "configured": runtime.context_provider is not None
                or runtime.engine.context_provider is not None,
            },
            "source_adapters": runtime.sources.adapter_names(),
            "bootstrap": bootstrap.model_dump(mode="json") if bootstrap else None,
            "cards": card_summaries,
            "retrieval_certification": retrieval.model_dump(mode="json") if retrieval else None,
            "gates": gates,
        }

    @mcp.tool()
    async def propose_insight_card(
        what_to_watch: str,
        why_watch: str,
        watch_for: list[str] | None = None,
        questions: list[str] | None = None,
        decision_guidance: str | None = None,
        selected_sources: list[dict[str, Any]] | None = None,
        adapter: str | None = None,
        limit: int = 10,
        title: str | None = None,
        comparison_windows: list[str] | None = None,
        delivery_methods: list[dict[str, Any]] | None = None,
        action_confidence_threshold: float = 0.70,
        owner: str | None = None,
        max_source_age_hours: float | None = 24.0,
        retrieval_mode: str = "expand",
        investigation_mode: str = "bounded",
        max_investigation_sources: int = 3,
        investigation_threshold: float = 0.60,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Propose and save a draft free-form insight card.

        ``selected_sources`` contains refs returned by
        ``discover_insight_sources``; each item may also provide adapter
        parameters such as Superset chart IDs. The result is a draft until a
        human or policy service approves it.
        """
        proposal = await authoring.propose(
            what_to_watch,
            why_watch,
            watch_for=watch_for,
            questions=questions,
            decision_guidance=decision_guidance,
            selected_sources=selected_sources,
            adapter=adapter,
            limit=limit,
            title=title,
            comparison_windows=comparison_windows,
            delivery_methods=[
                DeliveryMethod.model_validate(method) for method in (delivery_methods or [])
            ],
            action_confidence_threshold=action_confidence_threshold,
            owner=owner,
            max_source_age_hours=max_source_age_hours,
            retrieval_mode=RetrievalMode(retrieval_mode),
            investigation_mode=InvestigationMode(investigation_mode),
            max_investigation_sources=max_investigation_sources,
            investigation_threshold=investigation_threshold,
            principal=request_principal(ctx),
        )
        stored_card = proposal.card.model_copy(update={"compiled_plan": proposal.plan})
        runtime.card_store.save_card(stored_card)
        proposal = proposal.model_copy(update={"card": stored_card})
        return {
            "proposal": proposal.model_dump(mode="json"),
            "summary": proposal_summary(proposal),
        }

    @mcp.tool()
    async def draft_insight_card(
        title: str,
        what_to_watch: str,
        why_watch: str,
        sources: list[dict[str, Any]],
        watch_for: list[str] | None = None,
        questions: list[str] | None = None,
        decision_guidance: str | None = None,
        delivery_methods: list[dict[str, Any]] | None = None,
        card_id: str | None = None,
        comparison_windows: list[str] | None = None,
        action_confidence_threshold: float = 0.70,
        owner: str | None = None,
        max_source_age_hours: float | None = 24.0,
        retrieval_mode: str = "fixed",
        investigation_mode: str = "none",
        max_investigation_sources: int = 3,
        investigation_threshold: float = 0.60,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Draft a card over explicit source resources; no push is sent."""
        if not sources:
            raise ValueError("at least one source reference is required")
        principal = request_principal(ctx)
        source_refs = [SourceRef.model_validate(source) for source in sources]
        card = InsightCard(
            id=card_id or f"card-{_slug(title)}",
            title=title,
            what_to_watch=what_to_watch,
            why_watch=why_watch,
            watch_for=watch_for or [],
            questions=questions or [],
            decision_guidance=(decision_guidance or "").strip(),
            sources=source_refs,
            comparison_windows=comparison_windows
            or ["previous_period", "trailing_4_period_average"],
            delivery_methods=[
                DeliveryMethod.model_validate(method) for method in (delivery_methods or [])
            ],
            action_confidence_threshold=action_confidence_threshold,
            owner=owner,
            max_source_age_hours=max_source_age_hours,
            retrieval_mode=RetrievalMode(retrieval_mode),
            investigation_mode=InvestigationMode(investigation_mode),
            max_investigation_sources=max_investigation_sources,
            investigation_threshold=investigation_threshold,
            principal_id=principal.principal_id if principal else None,
            principal_tenant=principal.tenant_id if principal else None,
        )
        plan = await runtime.engine.compile(card)
        card = card.model_copy(update={"compiled_plan": plan})
        runtime.card_store.save_card(card)
        return {
            "card": card.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
            "status": card.status.value,
        }

    @mcp.tool()
    async def propose_metric_query_card(
        question: str,
        why: str,
        selected_sources: list[dict[str, Any]],
        requested_dimensions: list[str] | None = None,
        requested_time_grain: str | None = None,
        title: str | None = None,
        card_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a draft plain-language metric card over approved definitions.

        Jev selects a catalog definition and any requested semantic dimensions;
        code then stores the typed plan. SQL is emitted only by
        ``compile_metric_query_card`` with an explicit bounded time window.
        """
        if not question.strip() or not why.strip():
            raise ValueError("question and why are required")
        source_refs = await selected_query_sources(selected_sources)
        selector = getattr(runtime.engine.judger, "select_metric_plan", None)
        if not callable(selector):
            raise RuntimeError("the configured Jev judger does not support metric planning")
        plan = await plan_query(
            registry=runtime.sources,
            selector=runtime.engine.judger,
            goal=f"{question.strip()}\nPurpose: {why.strip()}",
            source_refs=source_refs,
            requested_dimensions=requested_dimensions,
            requested_time_grain=requested_time_grain,
        )
        card_title = (title or question.strip().rstrip("."))[:200] or "Metric query"
        card = MetricQueryCard(
            id=card_id or f"metric-{_slug(card_title)}-{uuid4().hex[:8]}",
            title=card_title,
            question=question,
            why=why,
            sources=source_refs,
            requested_dimensions=requested_dimensions or [],
            requested_time_grain=requested_time_grain,
            query_plan=plan,
        )
        metric_query_store.save_card(card)
        return {"card": card.model_dump(mode="json"), "status": card.status.value}

    @mcp.tool()
    def compile_metric_query_card(
        card_id: str,
        window_start: str,
        window_end: str,
    ) -> dict[str, Any]:
        """Compile a stored metric card into deterministic, bounded SQL."""
        card = metric_query_store.get_card(card_id)
        if card.query_plan is None:
            raise ValueError("metric query card has no approved metric plan")
        compiled = compile_query(card.query_plan, QueryWindow(window_start, window_end))
        return {
            "status": "preview" if card.status == QueryCardStatus.DRAFT else "approved",
            "card": card.model_dump(mode="json"),
            "compiled_query": compiled.model_dump(mode="json"),
        }

    @mcp.tool()
    def approve_metric_query_card(card_id: str, actor: str = "mcp-client") -> dict[str, Any]:
        """Approve a metric card for a caller-owned Trino or SQL executor."""
        card = metric_query_store.get_card(card_id)
        if card.query_plan is None:
            raise ValueError("metric query card needs a resolved metric plan before approval")
        approved = metric_query_store.set_card_status(card_id, QueryCardStatus.APPROVED)
        approved = approved.model_copy(
            update={"approved_by": actor, "approved_at": datetime.now(timezone.utc)}
        )
        metric_query_store.save_card(approved)
        return {"status": approved.status.value, "card": approved.model_dump(mode="json")}

    @mcp.tool()
    def list_metric_query_cards(status: str | None = None) -> dict[str, Any]:
        """List stored metric query cards for a UI or agent."""
        selected_status = QueryCardStatus(status) if status else None
        cards = [
            card
            for card in metric_query_store.list_cards()
            if selected_status is None or card.status == selected_status
        ]
        return {"cards": [card.model_dump(mode="json") for card in cards], "count": len(cards)}

    @mcp.tool()
    def get_metric_query_card(card_id: str) -> dict[str, Any]:
        """Return one stored metric query card."""
        return metric_query_store.get_card(card_id).model_dump(mode="json")

    @mcp.tool()
    async def evaluate_insight_card(
        card_id: str,
        idempotency_key: str | None = None,
        actor: str = "mcp-client",
        context: dict[str, Any] | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Evaluate an approved card, optionally with a versioned external context view."""
        context_snapshot = (
            ContextSnapshot.model_validate(context).model_copy(update={"trust": "unverified"})
            if context
            else None
        )
        return await evaluate_approved_card(
            card_id,
            idempotency_key=idempotency_key,
            actor=actor,
            context=context_snapshot,
            principal=request_principal(ctx),
        )

    @mcp.tool()
    async def resolve_insight_sources(
        card_id: str,
        context: dict[str, Any] | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Preview the bounded Jev-ranked evidence bundle for a stored card."""
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        context_snapshot = (
            ContextSnapshot.model_validate(context).model_copy(update={"trust": "unverified"})
            if context
            else None
        )
        if context_snapshot is None:
            context_snapshot = await context_for_card(card, None, principal)
        bundle = await authoring.resolve_bundle(
            card, context_snapshot, principal=principal
        )
        return {
            "card": card.model_dump(mode="json"),
            "bundle": bundle.model_dump(mode="json"),
        }

    @mcp.tool()
    async def review_insight_card(
        card_id: str,
        adapter: str | None = None,
        limit: int = 10,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Review a draft's source coverage before a human approves it.

        This is an onboarding review, not an automatic policy change. It shows
        bounded Jev-ranked candidates, why they were surfaced, and which
        recommendations the draft omitted so a client-owned UI or agent can ask
        for confirmation or revise the card.
        """
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        review = await authoring.review(
            card,
            adapter=adapter,
            limit=limit,
            principal=principal,
        )
        card = append_onboarding_review(card, review)
        runtime.card_store.save_card(card)
        return {
            "card": card.model_dump(mode="json"),
            "review": review.model_dump(mode="json"),
        }

    @mcp.tool()
    async def simulate_insight_card(
        card_id: str,
        context: dict[str, Any] | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Evaluate a draft without treating the result as an approved push action."""
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        context_snapshot = (
            ContextSnapshot.model_validate(context).model_copy(update={"trust": "unverified"})
            if context
            else None
        )
        if context_snapshot is None:
            context_snapshot = await context_for_card(card, None, principal)
        evaluation_card, bundle = await prepare_insight_card(
            card, context_snapshot, principal=principal
        )
        run = await runtime.engine.evaluate(
            evaluation_card,
            context_override=context_snapshot,
            principal=principal,
        )
        result = run.result.model_copy(update={"retrieval": bundle})
        return {
            "status": "preview",
            "delivery_enabled": False,
            "card": run.card.model_dump(mode="json"),
            "resources": [resource.model_dump(mode="json") for resource in run.resources],
            "plan": run.plan.model_dump(mode="json"),
            "retrieval": bundle.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
        }

    @mcp.tool()
    def record_insight_card_correction(
        card_id: str,
        kind: str,
        source_ref: str | None = None,
        note: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Record caller-owned onboarding feedback without changing card policy.

        An external agent or knowledge graph can consume this append-only signal
        on a later onboarding attempt. SignalWeave does not silently alter the
        selected sources, thresholds, or delivery policy from feedback alone.
        """
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        correction = OnboardingCorrection(
            correction_id=f"correction-{uuid4().hex}",
            card_id=card.id,
            card_version=card.version,
            kind=OnboardingCorrectionKind(kind),
            source_ref=source_ref,
            note=note.strip(),
            principal_id=principal.principal_id if principal else None,
            principal_tenant=principal.tenant_id if principal else None,
        )
        updated = card.model_copy(
            update={"onboarding_corrections": [*card.onboarding_corrections, correction]}
        )
        runtime.card_store.save_card(updated)
        return {
            "status": "recorded",
            "correction": correction.model_dump(mode="json"),
            "card": updated.model_dump(mode="json"),
        }

    @mcp.tool()
    def record_decision_feedback(
        idempotency_key: str,
        kind: str,
        expected_outcome: str | None = None,
        expected_delivery_method_keys: list[str] | None = None,
        note: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Append an operator label to a completed decision receipt.

        Feedback is caller-owned evaluation data. It never changes a card,
        thresholds, Jev state, or delivery policy automatically.
        """
        principal = request_principal(ctx)
        key = idempotency_key.strip()
        if not key:
            raise ValueError("idempotency_key must not be empty")
        receipt = decision_receipts.get_by_idempotency_key(key)
        if receipt is None:
            raise ValueError("unknown decision receipt for idempotency_key")
        if receipt.status == ReceiptStatus.PREPARED:
            raise ValueError("decision is not complete; feedback can be recorded after evaluation")
        card = get_scoped_card(receipt.card_id, principal)
        feedback = DecisionFeedback(
            feedback_id=f"feedback-{uuid4().hex}",
            receipt_id=receipt.receipt_id,
            idempotency_key=receipt.idempotency_key,
            card_id=card.id,
            card_version=card.version,
            kind=DecisionFeedbackKind(kind),
            expected_outcome=Outcome(expected_outcome) if expected_outcome else None,
            expected_delivery_method_keys=expected_delivery_method_keys or [],
            note=note.strip(),
            actor=principal.principal_id if principal else "mcp-client",
            principal_tenant=principal.tenant_id if principal else None,
            context_provider=receipt.context_provider,
            context_version=receipt.context_version,
        )
        decision_feedback.save(feedback)
        return {
            "status": "recorded",
            "feedback": feedback.model_dump(mode="json"),
            "receipt_id": receipt.receipt_id,
        }

    @mcp.tool()
    def list_decision_feedback(
        card_id: str | None = None,
        idempotency_key: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Read caller-owned labels for a card or one decision receipt."""
        principal = request_principal(ctx)
        if idempotency_key:
            receipt = decision_receipts.get_by_idempotency_key(idempotency_key.strip())
            if receipt is None:
                raise ValueError("unknown decision receipt for idempotency_key")
            scoped_card = get_scoped_card(receipt.card_id, principal)
            if card_id and card_id != scoped_card.id:
                raise ValueError("card_id does not match the decision receipt")
            card_id = scoped_card.id
            feedback = decision_feedback.list(idempotency_key=receipt.idempotency_key)
        elif card_id:
            scoped_card = get_scoped_card(card_id, principal)
            feedback = decision_feedback.list(card_id=scoped_card.id)
        else:
            if principal is not None:
                raise ValueError("card_id or idempotency_key is required for a scoped request")
            feedback = decision_feedback.list()
        return {
            "feedback": [item.model_dump(mode="json") for item in feedback],
            "count": len(feedback),
        }

    @mcp.tool()
    async def approve_insight_card(
        card_id: str,
        actor: str = "mcp-client",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Approve a draft card for later scheduler or webhook evaluation."""
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        if not card.sources:
            raise ValueError("an insight card needs at least one selected source before approval")
        onboarding_review = await authoring.review(card, principal=principal)
        if onboarding_review.readiness_status != "ready_for_approval":
            codes = ", ".join(blocker.code.value for blocker in onboarding_review.blockers)
            raise ValueError(
                "insight card is not ready for approval; resolve onboarding blockers: "
                + (codes or "human review required")
            )
        card = append_onboarding_review(card, onboarding_review)
        if card.compiled_plan is None:
            plan = await runtime.engine.compile(card)
            card = card.model_copy(update={"compiled_plan": plan})
        runtime.card_store.save_card(card)
        approved = runtime.card_store.set_card_status(card_id, InsightCardStatus.APPROVED)
        approved = approved.model_copy(
            update={"approved_by": actor, "approved_at": datetime.now(timezone.utc)}
        )
        runtime.card_store.save_card(approved)
        return {
            "status": approved.status.value,
            "card": approved.model_dump(mode="json"),
            "onboarding_review": onboarding_review.model_dump(mode="json"),
        }

    @mcp.tool()
    def list_insight_cards(
        status: str | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        """List stored cards for a client-owned UI or agent."""
        principal = request_principal(ctx)
        selected_status = InsightCardStatus(status) if status else None
        cards = [
            card
            for card in runtime.card_store.list_cards()
            if principal is None or card.principal_tenant == principal.tenant_id
            if selected_status is None or card.status == selected_status
        ]
        return {
            "cards": [card.model_dump(mode="json") for card in cards],
            "count": len(cards),
        }

    @mcp.tool()
    def get_insight_card(
        card_id: str, ctx: Context | None = None
    ) -> dict[str, Any]:
        """Return one stored insight card by its stable ID."""
        principal = request_principal(ctx)
        return get_scoped_card(card_id, principal).model_dump(mode="json")

    @mcp.resource("insight://catalog")
    def insight_catalog(ctx: Context | None = None) -> str:
        """Human-readable catalog for an MCP client."""
        principal = request_principal(ctx)
        return json.dumps(
            {
                "cards": [
                    card.model_dump(mode="json")
                    for card in runtime.card_store.list_cards()
                    if principal is None or card.principal_tenant == principal.tenant_id
                ]
            },
            indent=2,
        )

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> JSONResponse:
        """Small liveness endpoint for a container or scheduler."""
        return JSONResponse(
            {
                "status": "ok",
                "service": "signal-weave",
                "source_adapters": runtime.sources.adapter_names(),
            }
        )

    @mcp.custom_route("/webhooks/evaluate", methods=["POST"])
    async def evaluate_webhook(request: Request) -> JSONResponse:
        """Push-triggered card evaluation endpoint for schedulers and source alerts."""
        expected_token = os.getenv("PUSH_WEBHOOK_TOKEN")
        if not expected_token:
            return JSONResponse(
                {"error": "push webhook authentication is not configured"}, status_code=503
            )
        if request.headers.get("authorization") != f"Bearer {expected_token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            max_body_bytes = int(os.getenv("SIGNALWEAVE_MAX_HTTP_BODY_BYTES", "1048576"))
        except ValueError:
            max_body_bytes = 1048576
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                return JSONResponse({"error": "invalid content-length"}, status_code=400)
            if declared_length > max_body_bytes:
                return JSONResponse({"error": "request body is too large"}, status_code=413)
        body = await request.body()
        if len(body) > max_body_bytes:
            return JSONResponse({"error": "request body is too large"}, status_code=413)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return JSONResponse({"error": "request body must be valid JSON"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "request body must be a JSON object"}, status_code=400)
        card_id = payload.get("card_id")
        if not card_id:
            return JSONResponse({"error": "card_id is required"}, status_code=400)
        idempotency_key = payload.get("idempotency_key") or request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return JSONResponse(
                {"error": "idempotency_key is required for push evaluation"}, status_code=400
            )
        actor = str(request.headers.get("X-SignalWeave-Actor") or "webhook")
        try:
            context = (
                ContextSnapshot.model_validate(payload["context"]).model_copy(
                    update={"trust": "unverified"}
                )
                if payload.get("context")
                else None
            )
            result = await evaluate_approved_card(
                card_id,
                idempotency_key=str(idempotency_key),
                actor=actor,
                context=context,
            )
        except (KeyError, ValueError) as error:
            message = str(error)
            status_code = 409 if "draft" in message or "already being evaluated" in message else 404
            return JSONResponse({"error": str(error)}, status_code=status_code)
        return JSONResponse(result)

    return mcp


# The CLI constructs the server after resolving the runtime and credentials. Keeping module import
# side-effect free lets tests inspect the MCP factory without requiring a production API key.
