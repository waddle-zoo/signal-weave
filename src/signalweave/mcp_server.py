from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import uuid4

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field, StrictBool
from starlette.requests import Request
from starlette.responses import JSONResponse

from .bootstrap import BootstrapManifest, BootstrapService
from .engine import EvaluationPayloadError
from .evaluation import (
    CardEvaluationCase,
    CardEvaluationThresholds,
    CardWorkflowEvaluator,
    WorkflowCaseInput,
    card_acceptance_digest,
    has_current_evidence_admission_policy,
)
from .getting_started import GuideTask, getting_started
from .models import (
    CardDeliveryMethods,
    CertificationRecord,
    ComparisonWindows,
    ContextSnapshot,
    DecisionFeedback,
    DecisionFeedbackKind,
    DecisionReceipt,
    DeliveryMethod,
    EvidenceRequirementKey,
    InsightCard,
    InsightCardStatus,
    InvestigationMode,
    InvestigationQuestions,
    MetricQueryCard,
    OnboardingBlockerCode,
    OnboardingCorrection,
    OnboardingCorrectionKind,
    Outcome,
    PrincipalContext,
    QueryCardStatus,
    ReceiptStatus,
    RetrievalMode,
    SourceRef,
    WatchConditions,
)
from .numeric_conditions import NumericCondition
from .onboarding import (
    InsightAuthoringService,
    SelectedSourceInput,
    bind_numeric_condition_requirements,
    proposal_summary,
    resolve_comparison_windows,
)
from .query_planner import QueryWindow, compile_query, plan_query
from .reporting import build_investigation_report, render_investigation_report
from .retrieval_quality import (
    RetrievalQualityCase,
    RetrievalQualityEvaluator,
    RetrievalQualityThresholds,
)
from .runtime import Runtime, build_runtime, load_deployment_secret
from .store import (
    InMemoryCertificationReportStore,
    InMemoryDecisionFeedbackStore,
    InMemoryDecisionReceiptStore,
    JsonMetricQueryCardStore,
)
from .typesafe_adapter import JevPayloadError


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "insight"


def _evaluation_fingerprint(
    card: InsightCard,
    *,
    actor: str,
    context: ContextSnapshot | None,
    parent_receipt_id: str | None = None,
    workflow_step_key: str | None = None,
) -> str:
    payload = {
        "card_id": card.id,
        "card_version": card.version,
        "actor": actor or "mcp-client",
        "parent_receipt_id": parent_receipt_id,
        "workflow_step_key": workflow_step_key,
        "principal_tenant": card.principal_tenant,
        # Version numbers are useful audit labels but are not an integrity
        # boundary by themselves. Include the executable card contract so a
        # same-version overwrite cannot replay a receipt for different policy.
        "execution_payload": card.execution_payload(),
        "context": (
            context.model_dump(mode="json", exclude={"captured_at"}) if context else None
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evaluation_card(card: InsightCard) -> dict[str, Any]:
    """Keep active policy; authoring history remains available through get_insight_card."""
    return card.model_dump(
        mode="json",
        exclude={"onboarding_review", "onboarding_review_history", "onboarding_corrections", "compiled_plan"},
    )


CARD_AUTHORING_GUIDANCE = (
    "\n\nAuthoring guidance: use the minimal business fields accepted by draft_insight_card, "
    "propose_insight_card, or onboard_insight_card; do not copy a stored InsightCard, "
    "plan, review, or history object back as authoring input. Preserve the normal technical "
    "defaults unless an operator explicitly changes them: the default action confidence "
    "threshold is 0.70, a model-support floor rather than an accuracy guarantee, and a "
    "threshold of 1.0 may prevent automation. Keep fixed source references and operator "
    "profiles as provided; do not invent bounded expansion or investigation. Treat each "
    "SourceRef and its parameters as authoritative: reuse exact approved declarations and "
    "returned evidence; never reconstruct, rename, or invent keys or parameters. Keep the owner's intent "
    "free-form. Map every owner-requested delivery rule to its outcome and exact destination, "
    "not only the setup examples; outcomes meant to stay silent need no delivery entry. "
    "Never invent a recipient; ask for missing expected cases when an intended route is not covered. "
    "Passing partial examples is not proof of the whole policy. "
    "For recurring analytical reports, inspect existing source definitions and comparisons first; "
    "draft the smallest investigation preserving the business intent, then use "
    "preview_investigation_report to show the first actual report. Resolve missing definitions, "
    "unsupported questions, partial populations and conflicting measurements before proposing "
    "unattended reporting. Reuse existing trusted SQL and metric definitions, but verify them "
    "against source results. Ask only material unresolved business questions. Do not equate "
    "differently defined nearby metrics with a conflict in the selected metric. "
    "Compare definitions within the same intended population and metric; clarify ambiguous owner "
    "wording before making it a recurring condition. A complete report "
    "means its bounded evidence checks passed, not that the full business policy is certified. "
    "For threshold rules, distinguish a current level, signed between-period change in units, relative "
    "change, and a segment's contribution to that change. Do not silently choose among them. "
    "For exact numerical boundaries over available analytical comparisons, add numeric_conditions "
    "bound to the inspected source, comparison key, measurement and exact unit; let code perform "
    "those comparisons. Rates use fractions (12% is 0.12); do not infer a unit conversion. "
    "numeric_conditions are optional: when no applicable analytical comparison exists, "
    "leave them empty and keep the owner's complete rule in decision_guidance. Never invent "
    "a comparison key or confuse a declared requirement with available source evidence. "
    "Leave absolute=false for directional increases or decreases. absolute=true compares "
    "magnitude in BOTH directions; it is not a synonym for a change measured in units. "
    "Keep the owner's action policy in decision_guidance. Numeric checks do not select actions, "
    "and incomplete matching reports stay unknown. Do not duplicate numerical checks as "
    "required semantic watch items merely to restate the policy. A required watch/question is "
    "an unconditional evidence prerequisite; speculative details need explicit owner review "
    "as advisory or should be omitted. "
    "Instructions about how to write a report (for example, avoid causal claims) belong in "
    "follow_up_guidance, not watch_for: writing instructions are not observable evidence. "
    "watch_for and questions may be empty when the policy requires no separate semantic assessment. "
    "evidence_requirements maps only existing one-based watch:N or question:N slots to booleans. "
    "Review counterexamples such as a large but unchanged level, offsetting segment changes, "
    "a threshold-boundary case, and missing population coverage. Derive expected actions from "
    "the owner's policy independently of the model's answers; surface disagreements for review. "
    "Test other periods and negative cases with independent expectations before enabling "
    "unattended delivery. If only current evidence is available, capture one owner-labeled "
    "current case or preview it; do not invent historical snapshots. Owner approval without "
    "full acceptance remains unassessed and is suitable only for caller-managed shadow review. "
    "Never infer causation from a contribution breakdown. Scheduling, final "
    "narrative generation and delivery remain with the caller-owned agent."
)


def create_mcp(
    runtime: Runtime | None = None,
    *,
    principal_resolver: Callable[[Context], PrincipalContext] | None = None,
    http_principal_resolver: Callable[[], PrincipalContext] | None = None,
    auth_settings: Any | None = None,
    token_verifier: Any | None = None,
    require_principal: bool = False,
) -> FastMCP:
    runtime = runtime or build_runtime()
    if require_principal and runtime.principal is None and principal_resolver is None:
        raise RuntimeError(
            "the HTTP MCP server requires a deployment or request principal; "
            "use stdio for an intentionally unscoped local process"
        )
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
    mcp = FastMCP(
        "signal-weave",
        instructions=(
            "New users: call get_signalweave_guide first for the query, report or monitor path. "
            "SignalWeave saves and repeats reviewed investigations using TypeSafe Jev. "
            "Start with the user's business question, not a JSON form: use "
            "onboard_insight_card to discover sources and propose a draft. Read its "
            "setup_questions and review blockers. Inspect the proposed sources; ask "
            "the owner only for unresolved metric definitions, comparison periods, "
            "materiality rules, or notification destinations. Never invent those answers. "
            "Keep one-time setup questions separate from recurring analytical questions. "
            "After the owner answers, preserve the answer as policy or source meaning, "
            "not as an unanswered check on every run. Match each requested outcome to "
            "its exact delivery_methods entry; prose cannot supply a missing route. "
            "Preserve the owner's rules in decision_guidance and required source "
            "contracts. watch_for and questions are required evidence checks by default, "
            "not a generic analysis checklist. Use evidence_requirements with exact one-based "
            "question:N or watch:N keys and false only for owner-reviewed advisory details. "
            "False is not conditional applicability and never waives a required source. "
            "Review the effective requirements; follow_up_guidance cannot change them. Simulate the "
            "draft and show the owner the selected sources, "
            "calculations, uncertainties, and intended routes before requesting explicit "
            "approval. Before claiming onboarding is tested, replay owner-labeled setup examples "
            "with evaluate_card_workflow(acceptance_outcomes=[the owner's intended outcomes]). "
            "Choose examples covering actionable, quiet, and missing-evidence situations under "
            "the owner's policy (these need not map to three different outcomes), exact delivery keys and "
            "expected_delivery_destinations, plus required evidence and retrieval references. "
            "Labels come from the owner, never from the model's result. Inspect failed cases' "
            "evidence_plan and workflow; repair missing source context or an unintended required "
            "check, not thresholds or expected answers. Repeat on the revised card. Supply the "
            "passing certification_report_id as workflow_report_id when approving for certified use. "
            "If historical cases are unavailable, do not invent them. With explicit owner "
            "authorization, approve_insight_card without workflow_report_id authorizes only "
            "an unassessed card for caller-managed, delivery-disabled shadow evaluation; it "
            "does not certify or authorize unattended delivery. Record that limitation. A successful "
            "preview or policy-only review is not an acceptance test. Only call approve_insight_card after explicit owner approval; tool access "
            "is not approval. Similar catalog titles are not automatically the same metric. "
            "If the owner confirms a bounded source selection despite duplicate titles or "
            "omitted suggestions, use a fixed card with investigation_mode=none, call "
            "review_insight_card, and pass that review's source_selection_fingerprint "
            "and the owner's source_selection_reason to approve_insight_card. This does "
            "not override missing definitions, unhealthy sources or permissions. "
            "For repeat runs, reuse the approved card instead of "
            "recreating it. Use a stable idempotency key for retries and a new key for "
            "new observations. Return the evidence, numerical analysis, limitations, "
            "and workflow handoff. Correlation and accounting contributions are not "
            "proof of causation. SignalWeave does not schedule runs or send messages; "
            "your agent or scheduler owns those actions. Selected evidence is sent "
            "to TypeSafe; local installation is not offline inference."
            + CARD_AUTHORING_GUIDANCE
        ),
        auth=auth_settings,
        token_verifier=token_verifier,
    )

    def request_principal(ctx: Context | None) -> PrincipalContext | None:
        """Resolve a trusted gateway principal without accepting tool input as identity."""
        if principal_resolver is None:
            if require_principal and runtime.principal is None:
                raise RuntimeError("the identity gateway did not provide a principal")
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

    def assert_metric_card_scope(
        card: MetricQueryCard, principal: PrincipalContext | None
    ) -> None:
        if principal is None:
            return
        if card.principal_tenant != principal.tenant_id:
            raise ValueError(
                "metric query card is outside the authenticated principal tenant; "
                "rediscover or create it under the current principal"
            )

    def get_scoped_metric_card(
        card_id: str, principal: PrincipalContext | None
    ) -> MetricQueryCard:
        card = metric_query_store.get_card(card_id)
        assert_metric_card_scope(card, principal)
        return card

    def assert_evaluation_case_scope(
        cases: list[CardEvaluationCase], principal: PrincipalContext | None
    ) -> None:
        if principal is None:
            return
        for case in cases:
            foreign = [
                f"{resource.adapter}|{resource.resource}"
                for resource in case.resources
                if resource.contract.tenant_id != principal.tenant_id
                or not resource.contract.authorized
            ]
            if foreign:
                raise ValueError(
                    "evaluation case contains resources outside the authenticated principal "
                    f"tenant: {', '.join(sorted(foreign))}"
                )

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
        parent_receipt_id: str | None = None,
        workflow_step_key: str | None = None,
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
        parent_id = parent_receipt_id.strip() if parent_receipt_id else None
        step_key = workflow_step_key.strip() if workflow_step_key else None
        if step_key and not parent_id:
            raise ValueError("workflow_step_key requires parent_receipt_id")
        if parent_id:
            parent = decision_receipts.get_by_receipt_id(parent_id)
            if parent is None:
                raise ValueError("parent_receipt_id does not identify a decision receipt")
            if parent.card_id != card.id:
                raise ValueError("parent_receipt_id belongs to a different insight card")
        context = await context_for_card(card, context, principal)
        fingerprint = _evaluation_fingerprint(
            card,
            actor=actor,
            context=context,
            parent_receipt_id=parent_id,
            workflow_step_key=step_key,
        )
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
                    mode="json", exclude={"result"}
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
            parent_receipt_id=parent_id,
            workflow_step_key=step_key,
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
                    mode="json", exclude={"result"}
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
            report = build_investigation_report(run.card, evaluated_result, run.resources)
            result["report"] = report.model_dump(mode="json")
            result["report_markdown"] = render_investigation_report(report)
        except Exception as error:  # noqa: BLE001 - persist failed claims for replay safety
            failure: dict[str, Any] = {"error": f"{type(error).__name__}: {error}"}
            if isinstance(error, (EvaluationPayloadError, JevPayloadError)):
                failure["jev_payload_budget"] = {
                    "stage": error.stage,
                    "observed_bytes": error.observed_bytes,
                    "budget_bytes": error.budget_bytes,
                    "status": "exceeded",
                }
            decision_receipts.save(
                prepared.model_copy(
                    update={
                        "status": ReceiptStatus.FAILED,
                        "outcome": Outcome.INSUFFICIENT_DATA,
                        "result": failure,
                    }
                )
            )
            raise
        receipt = prepared.model_copy(
            update={
                "delivery_mode": "shadow",
                "status": ReceiptStatus.DELIVERY_DISABLED,
                "outcome": run.result.outcome,
                "delivery_enabled": False,
                "delivery_method_keys": [method.key for method in run.result.delivery_methods],
                "result": result,
            }
        )
        decision_receipts.save(receipt)
        return {
            "receipt": receipt.model_dump(mode="json", exclude={"result"}),
            "replayed": False,
            "card": _evaluation_card(run.card),
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
        parent_receipt_id: str | None = None,
        workflow_step_key: str | None = None,
    ) -> dict[str, Any]:
        key = (idempotency_key or f"manual:{card_id}:{uuid4().hex}").strip()
        if not key:
            raise ValueError("idempotency_key must not be empty")
        lock = idempotency_locks.setdefault(key, asyncio.Lock())
        async with lock:
            response = await evaluate_approved_card_once(
                card_id,
                idempotency_key=key,
                actor=actor,
                context=context,
                principal=principal,
                parent_receipt_id=parent_receipt_id,
                workflow_step_key=workflow_step_key,
            )
            if "error" not in response["result"]:
                if "report" in response["result"]:
                    response["report"] = response["result"]["report"]
                    response["report_markdown"] = response["result"]["report_markdown"]
                else:
                    # Do not fabricate a historical report using today's card
                    # or renderer. The original decision remains readable.
                    response["report_unavailable_reason"] = (
                        "This receipt has no archived investigation report. "
                        "Use a new run key to evaluate current evidence."
                    )
            return response

    async def selected_query_sources(
        selected_sources: list[dict[str, Any]],
        principal: PrincipalContext | None,
    ) -> list[SourceRef]:
        if not selected_sources:
            raise ValueError("metric query cards require at least one selected source")
        catalog = {
            f"{resource.adapter}|{resource.resource}": resource
            for resource in await runtime.sources.list_resources(
                authorized_tenants=[principal.tenant_id] if principal else None
            )
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

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})
    def get_signalweave_guide(
        task: GuideTask = "start", ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Start here: help a person query, report on, or monitor their existing BI.

        Returns the supported tool sequence, what to ask the owner, and where to
        stop. No source access, paid inference, approval, scheduling or delivery.
        """
        request_principal(ctx)
        return getting_started(task)

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
        cases: Annotated[list[WorkflowCaseInput], Field(min_length=1, max_length=500)],
        thresholds: dict[str, Any] | None = None,
        max_concurrency: int = 8,
        acceptance_outcomes: list[Outcome] | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Replay one stored card against owner-labeled snapshots before promotion.

        Each case contains ``id``, ``expected_outcome`` and either exact
        ``resources`` snapshots or ``capture_current_sources=true`` to fetch
        this card's selected sources. Current capture can execute source queries;
        use it only within the owner's query budget. At most one case can capture
        current evidence. It is NOT historical or full-policy acceptance.
        Copy snapshot objects unchanged; resource strings are not snapshots.
        Optional evidence/retrieval labels stay in the evaluator and
        are never included in the Jev state. Historical snapshots are supplied
        by the caller; production delivery is not performed by this tool.
        Set acceptance_outcomes to the owner's intended dispositions to test
        onboarding with strict behavioral coverage and exact endpoint labels.
        This is empirical evidence, not human authorization or causal proof.
        """
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        if not cases:
            raise ValueError("at least one labeled evaluation case is required")
        inputs = [WorkflowCaseInput.model_validate(case) for case in cases]
        current_case_ids = [case.id for case in inputs if case.capture_current_sources]
        if len(current_case_ids) > 1:
            raise ValueError("At most one current-source case is allowed; supply distinct historical snapshots for other cases.")
        if current_case_ids and acceptance_outcomes is not None:
            raise ValueError("Current-source capture is a shadow check, not acceptance certification; supply independent historical snapshots for acceptance_outcomes.")
        # Validate ALL inputs before a source query or inference is attempted.
        parsed_cases = [
            CardEvaluationCase.model_validate({
                **case.model_dump(exclude={"capture_current_sources", "resources"}),
                "resources": case.resources or [], "card": card,
            }) for case in inputs
        ]
        assert_evaluation_case_scope(parsed_cases, principal)
        parsed_thresholds = CardEvaluationThresholds.model_validate(thresholds) if thresholds is not None else None
        evaluator = CardWorkflowEvaluator(runtime.engine, max_concurrency=max_concurrency, principal=principal)
        for input_case, parsed in zip(inputs, parsed_cases, strict=True):
            if input_case.capture_current_sources:
                parsed.resources = await runtime.sources.resolve(
                    card.sources, authorized_tenants=[principal.tenant_id] if principal else None,
                )
        assert_evaluation_case_scope(parsed_cases, principal)
        report = await evaluator.evaluate(
            parsed_cases,
            thresholds=parsed_thresholds,
            acceptance_outcomes=acceptance_outcomes,
        )
        payload = report.model_dump(mode="json")
        if current_case_ids:
            payload["current_source_case_ids"] = current_case_ids
            if payload["status"] == "approved":
                payload["status"] = "shadow"
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
            policy_current = bool(workflow and has_current_evidence_admission_policy(workflow.report))
            acceptance_current = bool(
                workflow and workflow.report.get("acceptance_passed") is True
                and workflow.report.get("card_execution_digests", {}).get(card.id) == card_acceptance_digest(card)
            )
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
                        "subject_version": workflow.subject_version,
                        "stale": workflow.subject_version != str(card.version) or not policy_current,
                        "evidence_admission_policy_current": policy_current,
                        "acceptance_current": acceptance_current,
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
            elif workflow.subject_version != str(card.version):
                gates.append(
                    {
                        "code": "workflow-certification-stale",
                        "severity": "blocked",
                        "message": (
                            f"Card {card.id} is version {card.version}, but its latest "
                            f"workflow certification covers version {workflow.subject_version}. "
                            "Replay the certification set before shadow evaluation."
                        ),
                    }
                )
            elif not policy_current:
                gates.append({
                    "code": "workflow-admission-policy-stale",
                    "severity": "blocked",
                    "message": (
                        f"Card {card.id} certification predates the current evidence admission policy. "
                        "Review required versus advisory checks and replay certification; the old audit is retained."
                    ),
                })
            elif workflow.status != "approved":
                gates.append(
                    {
                        "code": "workflow-certification-needs-review",
                        "severity": "review",
                        "message": f"Card {card.id} workflow certification is {workflow.status}.",
                    }
                )
            elif not acceptance_current:
                gates.append({
                    "code": "workflow-acceptance-missing-or-stale",
                    "severity": "review",
                    "message": f"Card {card.id} needs a passing acceptance replay of its current "
                               "policy, sources, plan and destinations. A preview or partial "
                               "certification does not prove onboarding works.",
                })

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
        watch_for: WatchConditions | None = None,
        questions: InvestigationQuestions | None = None,
        numeric_conditions: list[NumericCondition] | None = None,
        evidence_requirements: dict[EvidenceRequirementKey, StrictBool] | None = None,
        decision_guidance: str | None = None,
        follow_up_guidance: str | None = None,
        selected_sources: list[SelectedSourceInput] | None = None,
        adapter: str | None = None,
        limit: int = 10,
        title: str | None = None,
        comparison_windows: ComparisonWindows | None = None,
        delivery_methods: CardDeliveryMethods | None = None,
        action_confidence_threshold: Annotated[
            float,
            Field(
                ge=0.0,
                le=1.0,
                description=(
                    "Model-support floor for automatic action, not an accuracy guarantee. "
                    "The normal default is 0.70; 1.0 may prevent automation."
                ),
            ),
        ] = 0.70,
        owner: str | None = None,
        max_source_age_hours: float | None = 24.0,
        retrieval_mode: Annotated[
            RetrievalMode,
            Field(
                description=(
                    "Retrieval scope: fixed uses the selected source references as provided; "
                    "expand allows additional authorized sources when the adapter registry "
                    "supports bounded related-source retrieval."
                )
            ),
        ] = RetrievalMode.EXPAND,
        investigation_mode: Annotated[
            InvestigationMode,
            Field(
                description=(
                    "Investigation scope: none disables follow-up; bounded enables bounded "
                    "follow-up investigation and requires a live SourceRegistry."
                )
            ),
        ] = InvestigationMode.BOUNDED,
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
            numeric_conditions=numeric_conditions,
            evidence_requirements=evidence_requirements,
            decision_guidance=decision_guidance,
            follow_up_guidance=follow_up_guidance,
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
            "proposal": proposal.model_dump(mode="json", exclude={"card": {
                "onboarding_review", "onboarding_review_history", "onboarding_corrections", "compiled_plan"
            }}),
            "summary": proposal_summary(proposal),
        }

    @mcp.tool()
    async def onboard_insight_card(
        what_to_watch: str,
        why_watch: str,
        watch_for: WatchConditions | None = None,
        questions: InvestigationQuestions | None = None,
        numeric_conditions: list[NumericCondition] | None = None,
        evidence_requirements: dict[EvidenceRequirementKey, StrictBool] | None = None,
        decision_guidance: str | None = None,
        follow_up_guidance: str | None = None,
        selected_sources: list[SelectedSourceInput] | None = None,
        adapter: str | None = None,
        limit: int = 10,
        title: str | None = None,
        comparison_windows: ComparisonWindows | None = None,
        delivery_methods: CardDeliveryMethods | None = None,
        action_confidence_threshold: Annotated[
            float,
            Field(
                ge=0.0,
                le=1.0,
                description=(
                    "Model-support floor for automatic action, not an accuracy guarantee. "
                    "The normal default is 0.70; 1.0 may prevent automation."
                ),
            ),
        ] = 0.70,
        owner: str | None = None,
        max_source_age_hours: float | None = 24.0,
        retrieval_mode: Annotated[
            RetrievalMode,
            Field(
                description=(
                    "Retrieval scope: fixed uses the selected source references as provided; "
                    "expand allows additional authorized sources when the adapter registry "
                    "supports bounded related-source retrieval."
                )
            ),
        ] = RetrievalMode.EXPAND,
        investigation_mode: Annotated[
            InvestigationMode,
            Field(
                description=(
                    "Investigation scope: none disables follow-up; bounded enables bounded "
                    "follow-up investigation and requires a live SourceRegistry."
                )
            ),
        ] = InvestigationMode.BOUNDED,
        max_investigation_sources: int = 3,
        investigation_threshold: float = 0.60,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Onboard one free-form card in a single human-reviewable call.

        This is an ergonomic wrapper around the same Jev-backed proposal path;
        it never approves a card, sends a push, or accepts identity from tool
        arguments. The response is shaped for a caller-owned UI or agent:
        draft card, bounded discovery, typed plan, blockers, questions, and the
        exact next action needed to reach approval.
        """
        result = await propose_insight_card(
            what_to_watch=what_to_watch,
            why_watch=why_watch,
            watch_for=watch_for,
            questions=questions,
            numeric_conditions=numeric_conditions,
            evidence_requirements=evidence_requirements,
            decision_guidance=decision_guidance,
            follow_up_guidance=follow_up_guidance,
            selected_sources=selected_sources,
            adapter=adapter,
            limit=limit,
            title=title,
            comparison_windows=comparison_windows,
            delivery_methods=delivery_methods,
            action_confidence_threshold=action_confidence_threshold,
            owner=owner,
            max_source_age_hours=max_source_age_hours,
            retrieval_mode=retrieval_mode,
            investigation_mode=investigation_mode,
            max_investigation_sources=max_investigation_sources,
            investigation_threshold=investigation_threshold,
            ctx=ctx,
        )
        proposal = result["proposal"]
        review = proposal["onboarding_review"]
        if review["readiness_status"] == "blocked":
            next_action = "answer_setup_questions"
        elif review["readiness_status"] == "needs_human_review":
            next_action = "review_candidate_sources"
        else:
            next_action = "simulate_then_approve"
        return {
            "status": review["readiness_status"],
            "next_action": next_action,
            "approval_required": True,
            "delivery_enabled": False,
            "card": proposal["card"],
            "plan": proposal["plan"],
            "discovery": proposal["discovery"],
            "review": review,
            "setup_questions": proposal["setup_questions"],
            "summary": result["summary"],
        }

    @mcp.tool()
    async def draft_insight_card(
        title: str,
        what_to_watch: str,
        why_watch: str,
        sources: list[SourceRef],
        watch_for: WatchConditions | None = None,
        questions: InvestigationQuestions | None = None,
        numeric_conditions: list[NumericCondition] | None = None,
        evidence_requirements: dict[EvidenceRequirementKey, StrictBool] | None = None,
        decision_guidance: str | None = None,
        follow_up_guidance: str | None = None,
        delivery_methods: CardDeliveryMethods | None = None,
        comparison_windows: ComparisonWindows | None = None,
        action_confidence_threshold: Annotated[
            float,
            Field(
                ge=0.0,
                le=1.0,
                description=(
                    "Model-support floor for automatic action, not an accuracy guarantee. "
                    "The normal default is 0.70; 1.0 may prevent automation."
                ),
            ),
        ] = 0.70,
        owner: str | None = None,
        max_source_age_hours: float | None = 24.0,
        retrieval_mode: Annotated[
            RetrievalMode,
            Field(
                description=(
                    "Retrieval scope: fixed uses the selected source references as provided; "
                    "expand allows additional authorized sources when the adapter registry "
                    "supports bounded related-source retrieval."
                )
            ),
        ] = RetrievalMode.FIXED,
        investigation_mode: Annotated[
            InvestigationMode,
            Field(
                description=(
                    "Investigation scope: none disables follow-up; bounded enables bounded "
                    "follow-up investigation and requires a live SourceRegistry."
                )
            ),
        ] = InvestigationMode.NONE,
        max_investigation_sources: int = 3,
        investigation_threshold: float = 0.60,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Draft a card over explicit source resources; no push is sent.

        Use the minimal business fields described in ``CARD_AUTHORING_GUIDANCE``;
        returned storage objects are not draft inputs.
        """
        if not sources:
            raise ValueError("at least one source reference is required")
        principal = request_principal(ctx)
        source_refs = [SourceRef.model_validate(source) for source in sources]
        numeric_conditions = [
            NumericCondition.model_validate(condition)
            for condition in (numeric_conditions or [])
        ]
        source_refs = bind_numeric_condition_requirements(source_refs, numeric_conditions)
        contracts = {}
        if comparison_windows is None:
            for source in source_refs:
                descriptor = await runtime.sources.authorize(
                    source, authorized_tenants=[principal.tenant_id] if principal else None,
                )
                if descriptor is not None:
                    contracts[f"{source.adapter}|{source.resource}"] = descriptor.contract
        card = InsightCard(
            id=f"card-{_slug(title)}-{uuid4().hex[:12]}",
            title=title,
            what_to_watch=what_to_watch,
            why_watch=why_watch,
            watch_for=watch_for or [],
            questions=questions or [],
            numeric_conditions=numeric_conditions,
            evidence_requirements=evidence_requirements or {},
            decision_guidance=(decision_guidance or "").strip(),
            follow_up_guidance=(follow_up_guidance or "").strip(),
            sources=source_refs,
            comparison_windows=resolve_comparison_windows(comparison_windows, source_refs, contracts),
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
            "card": _evaluation_card(card),
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
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Create a draft plain-language metric card over approved definitions.

        Jev selects a catalog definition and any requested semantic dimensions;
        code then stores the typed plan. SQL is emitted only by
        ``compile_metric_query_card`` with an explicit bounded time window.
        """
        if not question.strip() or not why.strip():
            raise ValueError("question and why are required")
        principal = request_principal(ctx)
        source_refs = await selected_query_sources(selected_sources, principal)
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
            id=f"metric-{_slug(card_title)}-{uuid4().hex[:12]}",
            title=card_title,
            question=question,
            why=why,
            sources=source_refs,
            requested_dimensions=requested_dimensions or [],
            requested_time_grain=requested_time_grain,
            query_plan=plan,
            principal_id=principal.principal_id if principal else None,
            principal_tenant=principal.tenant_id if principal else None,
        )
        metric_query_store.save_card(card)
        return {"card": card.model_dump(mode="json"), "status": card.status.value}

    @mcp.tool()
    def compile_metric_query_card(
        card_id: str,
        window_start: str,
        window_end: str,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Compile a stored metric card into deterministic, bounded SQL."""
        card = get_scoped_metric_card(card_id, request_principal(ctx))
        if card.query_plan is None:
            raise ValueError("metric query card has no approved metric plan")
        compiled = compile_query(card.query_plan, QueryWindow(window_start, window_end))
        return {
            "status": "preview" if card.status == QueryCardStatus.DRAFT else "approved",
            "card": card.model_dump(mode="json"),
            "compiled_query": compiled.model_dump(mode="json"),
        }

    @mcp.tool()
    def approve_metric_query_card(
        card_id: str, actor: str = "mcp-client", ctx: Context | None = None
    ) -> dict[str, Any]:
        """Approve a metric card for a caller-owned Trino or SQL executor."""
        principal = request_principal(ctx)
        card = get_scoped_metric_card(card_id, principal)
        if card.query_plan is None:
            raise ValueError("metric query card needs a resolved metric plan before approval")
        approved = metric_query_store.set_card_status(card_id, QueryCardStatus.APPROVED)
        approved = approved.model_copy(
            update={
                "approved_by": principal.principal_id if principal else actor,
                "approved_at": datetime.now(timezone.utc),
            }
        )
        metric_query_store.save_card(approved)
        return {"status": approved.status.value, "card": approved.model_dump(mode="json")}

    @mcp.tool()
    def list_metric_query_cards(
        status: str | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        """List stored metric query cards for a UI or agent."""
        principal = request_principal(ctx)
        selected_status = QueryCardStatus(status) if status else None
        cards = [
            card
            for card in metric_query_store.list_cards()
            if principal is None or card.principal_tenant == principal.tenant_id
            if selected_status is None or card.status == selected_status
        ]
        return {"cards": [card.model_dump(mode="json") for card in cards], "count": len(cards)}

    @mcp.tool()
    def get_metric_query_card(
        card_id: str, ctx: Context | None = None
    ) -> dict[str, Any]:
        """Return one stored metric query card."""
        return get_scoped_metric_card(card_id, request_principal(ctx)).model_dump(mode="json")

    @mcp.tool()
    async def evaluate_insight_card(
        card_id: str,
        idempotency_key: str | None = None,
        actor: str = "mcp-client",
        context: ContextSnapshot | None = None,
        parent_receipt_id: str | None = None,
        workflow_step_key: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Run an approved card in delivery-disabled shadow mode.

        The result is Jev-backed and durable. SignalWeave never sends the
        configured delivery methods; a caller-owned scheduler or agent may
        inspect the receipt and decide what to do next.
        """
        principal = request_principal(ctx)
        trusted_actor = principal.principal_id if principal else actor
        context_snapshot = (
            ContextSnapshot.model_validate(context).model_copy(update={"trust": "unverified"})
            if context
            else None
        )
        return await evaluate_approved_card(
            card_id,
            idempotency_key=idempotency_key,
            actor=trusted_actor,
            context=context_snapshot,
            principal=principal,
            parent_receipt_id=parent_receipt_id,
            workflow_step_key=workflow_step_key,
        )

    @mcp.tool()
    def get_decision_receipt(
        idempotency_key: str | None = None,
        receipt_id: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Recover one durable shadow result and its operator labels.

        A caller can use either the scheduler's idempotency key or the
        receipt id returned by ``evaluate_insight_card``. The card scope check
        runs before any receipt data is returned.
        """
        principal = request_principal(ctx)
        key = idempotency_key.strip() if idempotency_key else None
        requested_receipt_id = receipt_id.strip() if receipt_id else None
        if idempotency_key is not None and not key:
            raise ValueError("idempotency_key must not be empty")
        if receipt_id is not None and not requested_receipt_id:
            raise ValueError("receipt_id must not be empty")
        if bool(key) == bool(requested_receipt_id):
            raise ValueError("provide exactly one of idempotency_key or receipt_id")
        receipt = (
            decision_receipts.get_by_idempotency_key(key)
            if key
            else decision_receipts.get_by_receipt_id(requested_receipt_id)
        )
        if receipt is None:
            raise ValueError("unknown decision receipt")
        get_scoped_card(receipt.card_id, principal)
        feedback = decision_feedback.list(receipt_id=receipt.receipt_id)
        return {
            "status": "found",
            "receipt": receipt.model_dump(mode="json"),
            "result": receipt.result,
            "feedback": [item.model_dump(mode="json") for item in feedback],
        }

    @mcp.tool()
    async def resolve_insight_sources(
        card_id: str,
        context: ContextSnapshot | None = None,
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
            "card": _evaluation_card(card),
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
        original = card.model_dump(mode="json")
        review = await authoring.review(
            card,
            adapter=adapter,
            limit=limit,
            principal=principal,
        )
        if get_scoped_card(card_id, principal).model_dump(mode="json") != original:
            raise ValueError("Card changed during review; review the current card before approval.")
        card = append_onboarding_review(card, review)
        runtime.card_store.save_card(card)
        return {
            "card": _evaluation_card(card),
            "review": review.model_dump(mode="json"),
        }

    @mcp.tool()
    async def simulate_insight_card(
        card_id: str,
        context: ContextSnapshot | None = None,
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
        report = build_investigation_report(run.card, result, run.resources)
        return {
            "status": "preview",
            "delivery_enabled": False,
            "card": _evaluation_card(run.card),
            "resources": [resource.model_dump(mode="json") for resource in run.resources],
            "plan": run.plan.model_dump(mode="json"),
            "retrieval": bundle.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "report_markdown": render_investigation_report(report),
        }

    @mcp.tool()
    async def preview_investigation_report(
        card_id: str,
        context: ContextSnapshot | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Run a first analytical report before approving a recurring investigation.

        Uses the normal delivery-disabled simulation, real source adapters and Jev.
        The report exposes validated calculations, coverage, provenance and unresolved
        work. It never approves a card or certifies policy from one example. A caller
        should review this report, repair missing context, test other periods, and
        obtain owner authorization before scheduling evaluate_insight_card.
        """
        return await simulate_insight_card(card_id=card_id, context=context, ctx=ctx)

    @mcp.tool()
    def record_insight_card_correction(
        card_id: str,
        kind: OnboardingCorrectionKind,
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
        kind: DecisionFeedbackKind,
        feedback_id: str | None = None,
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
        stable_feedback_id = feedback_id.strip() if feedback_id else None
        if feedback_id is not None and not stable_feedback_id:
            raise ValueError("feedback_id must not be empty")
        actor = principal.principal_id if principal else "mcp-client"
        expected_routes = expected_delivery_method_keys or []
        feedback = DecisionFeedback(
            feedback_id=stable_feedback_id or f"feedback-{uuid4().hex}",
            receipt_id=receipt.receipt_id,
            idempotency_key=receipt.idempotency_key,
            card_id=card.id,
            card_version=receipt.card_version,
            kind=DecisionFeedbackKind(kind),
            expected_outcome=Outcome(expected_outcome) if expected_outcome else None,
            expected_delivery_method_keys=expected_routes,
            note=note.strip(),
            actor=actor,
            principal_tenant=principal.tenant_id if principal else None,
            context_provider=receipt.context_provider,
            context_version=receipt.context_version,
        )
        comparable_fields = (
            "receipt_id",
            "idempotency_key",
            "card_id",
            "card_version",
            "kind",
            "context_provider",
            "context_version",
            "expected_outcome",
            "expected_delivery_method_keys",
            "note",
            "actor",
            "principal_tenant",
        )

        def replay_if_same(existing: DecisionFeedback | None) -> dict[str, Any] | None:
            if existing is None:
                return None
            if any(
                getattr(existing, field) != getattr(feedback, field)
                for field in comparable_fields
            ):
                raise ValueError("feedback_id is already bound to different feedback")
            return {
                "status": "replayed",
                "feedback": existing.model_dump(mode="json"),
                "receipt_id": receipt.receipt_id,
            }

        if stable_feedback_id:
            existing = decision_feedback.get(stable_feedback_id)
            replay = replay_if_same(existing)
            if replay is not None:
                return replay
        try:
            decision_feedback.save(feedback)
        except ValueError:
            if stable_feedback_id:
                replay = replay_if_same(decision_feedback.get(stable_feedback_id))
                if replay is not None:
                    return replay
            raise
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
        source_selection_fingerprint: str | None = None,
        source_selection_reason: str | None = None,
        workflow_report_id: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Approve only after explicit owner review and a delivery-disabled simulation.

        For a fixed card with no dynamic investigation, an owner may confirm its
        exact selected sources despite duplicate titles or omitted recommendations.
        Pass source_selection_fingerprint from review_insight_card and the owner's
        source_selection_reason explaining which definitions/populations were chosen
        and why. Changed policy/catalog invalidates that confirmation. This cannot
        override source health, permissions, missing policy or other blockers.
        Feedback corrections alone never approve or resolve a card.
        Pass a successful acceptance-mode evaluate_card_workflow report as
        workflow_report_id to bind approval to tested policy, sources, plan and
        endpoints. Without it this is owner authorization only, not certification.
        """
        principal = request_principal(ctx)
        card = get_scoped_card(card_id, principal)
        original = card.model_dump(mode="json")
        if not card.sources:
            raise ValueError("an insight card needs at least one selected source before approval")
        acceptance_record = None
        if workflow_report_id is not None:
            acceptance_record = certification_reports.get(workflow_report_id)
            report = acceptance_record.report
            if (acceptance_record.kind != "card_workflow"
                    or acceptance_record.subject_id != card.id
                    or acceptance_record.tenant_id != (card.principal_tenant or (principal.tenant_id if principal else "deployment"))
                    or acceptance_record.subject_version != str(card.version)
                    or acceptance_record.status != "approved"
                    or report.get("acceptance_passed") is not True
                    or not has_current_evidence_admission_policy(report)
                    or report.get("card_execution_digests", {}).get(card.id) != card_acceptance_digest(card)):
                raise ValueError("Workflow acceptance report is failed, stale, outside this card/tenant, "
                                 "or not an acceptance test. Replay owner-labeled setup cases for the "
                                 "current card with evaluate_card_workflow(acceptance_outcomes=...).")
        onboarding_review = await authoring.review(card, principal=principal)
        if source_selection_fingerprint is not None or source_selection_reason is not None:
            reason = (source_selection_reason or "").strip()
            if not source_selection_fingerprint or not reason or len(reason) > 4000:
                raise ValueError("Provide both source_selection_fingerprint and a nonempty "
                                 "source_selection_reason (at most 4000 characters).")
            if (card.retrieval_mode != RetrievalMode.FIXED
                    or card.investigation_mode != InvestigationMode.NONE):
                raise ValueError("Source-selection confirmation requires retrieval_mode=fixed and "
                                 "investigation_mode=none. Draft that bounded scope, review, simulate, "
                                 "and ask its owner before approving; dynamic sources are not excluded.")
            previous = card.onboarding_review
            if (previous is None or not hmac.compare_digest(
                    source_selection_fingerprint, previous.source_selection_fingerprint)
                    or not hmac.compare_digest(source_selection_fingerprint,
                                               onboarding_review.source_selection_fingerprint)):
                raise ValueError("Source selection review is stale or missing. Call review_insight_card "
                                 "and obtain owner confirmation of the current policy and catalog.")
            confirmable = {OnboardingBlockerCode.DEFINITION_CONFLICT,
                           OnboardingBlockerCode.CANDIDATE_SELECTION_REVIEW}
            resolved = [b for b in onboarding_review.blockers if b.code in confirmable]
            remaining = [b for b in onboarding_review.blockers if b.code not in confirmable]
            if resolved:
                remaining_questions = [q for q in onboarding_review.questions
                                       if q not in {b.question for b in resolved}]
                blocking = any(b.severity.value == "block" for b in remaining)
                needs_review = any(b.severity.value == "review" for b in remaining)
                onboarding_review = onboarding_review.model_copy(update={
                    "blockers": remaining, "questions": remaining_questions,
                    "status": "needs_human_input" if remaining_questions else "ready_for_approval",
                    "readiness_status": "blocked" if blocking else "needs_human_review"
                    if needs_review else "ready_for_approval",
                    "source_selection_confirmation": reason,
                    "confirmed_blocker_codes": [b.code for b in resolved],
                })
        if onboarding_review.readiness_status != "ready_for_approval":
            codes = ", ".join(blocker.code.value for blocker in onboarding_review.blockers)
            raise ValueError(
                "insight card is not ready for approval; resolve onboarding blockers: "
                + (codes or "human review required")
                + ". Call review_insight_card for evidence. For an owner-confirmed fixed source "
                "selection (investigation_mode=none), pass its source_selection_fingerprint "
                "and source_selection_reason. Other blockers must be repaired, not acknowledged."
            )
        card = append_onboarding_review(card, onboarding_review)
        if card.compiled_plan is None:
            plan = await runtime.engine.compile(card)
            card = card.model_copy(update={"compiled_plan": plan})
        if get_scoped_card(card_id, principal).model_dump(mode="json") != original:
            raise ValueError("Card changed during approval; review and simulate the current card "
                             "and obtain its owner's approval again.")
        runtime.card_store.save_card(card)
        approved = runtime.card_store.set_card_status(card_id, InsightCardStatus.APPROVED)
        approved = approved.model_copy(
            update={
                "approved_by": principal.principal_id if principal else actor,
                "approved_at": datetime.now(timezone.utc),
            }
        )
        runtime.card_store.save_card(approved)
        return {
            "status": approved.status.value,
            "card": _evaluation_card(approved),
            "onboarding_review": onboarding_review.model_dump(mode="json"),
            "workflow_acceptance": {
                "status": "passed" if acceptance_record else "unassessed",
                "report_id": acceptance_record.report_id if acceptance_record else None,
                "human_authorization_required": True,
            },
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
        card_id: str, include_history: bool = False, ctx: Context | None = None
    ) -> dict[str, Any]:
        """Return active policy, compiled plan and latest review by stable ID.

        Set include_history=true for prior reviews and correction audit records.
        History stays persisted but is not repeated in ordinary agent reads.
        """
        principal = request_principal(ctx)
        return get_scoped_card(card_id, principal).model_dump(
            mode="json",
            exclude=set() if include_history else {"onboarding_review_history", "onboarding_corrections"},
        )

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
        if http_principal_resolver is None:
            expected_token = load_deployment_secret("PUSH_WEBHOOK_TOKEN")
            if not expected_token:
                return JSONResponse(
                    {"error": "push webhook authentication is not configured"}, status_code=503
                )
            if not hmac.compare_digest(
                request.headers.get("authorization", ""), f"Bearer {expected_token}"
            ):
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
        try:
            principal = (
                http_principal_resolver() if http_principal_resolver else runtime.principal
            )
        except RuntimeError:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if principal is None:
            return JSONResponse(
                {"error": "push webhook principal is not configured"}, status_code=503
            )
        actor = principal.principal_id
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
                principal=principal,
                parent_receipt_id=(
                    str(payload["parent_receipt_id"])
                    if payload.get("parent_receipt_id")
                    else None
                ),
                workflow_step_key=(
                    str(payload["workflow_step_key"])
                    if payload.get("workflow_step_key")
                    else None
                ),
            )
        except (KeyError, ValueError) as error:
            message = str(error)
            status_code = 409 if "draft" in message or "already being evaluated" in message else 404
            return JSONResponse({"error": str(error)}, status_code=status_code)
        return JSONResponse(result)

    return mcp


# The CLI constructs the server after resolving the runtime and credentials. Keeping module import
# side-effect free lets tests inspect the MCP factory without requiring a production API key.
