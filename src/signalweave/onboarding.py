from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from .compiler import SUPPORTED_CAPABILITIES, base_plan
from .models import (
    ContextSnapshot,
    DeliveryMethod,
    EvidenceBundle,
    EvidenceRequirement,
    InsightCard,
    InsightCardOnboardingReview,
    InsightCardProposal,
    InvestigationMode,
    OnboardingBlocker,
    OnboardingBlockerCode,
    OnboardingBlockerSeverity,
    OnboardingDiscoveryReceipt,
    OnboardingSourceReview,
    Outcome,
    PrincipalContext,
    ResourceContract,
    ResourceDescriptor,
    ResourceDiscovery,
    ResourceMatch,
    RetrievalMode,
    SourceRef,
)
from .numeric_conditions import NumericCondition
from .retrieval import _search_text, build_candidate_pool, resource_ref
from .sources import SourceRegistry


class ResourceRelevanceJudger(Protocol):
    """The Jev capability required to rank bounded catalog candidates."""

    name: str

    async def rank_resources(
        self, goal: str, resources: list[ResourceDescriptor]
    ) -> dict[str, float]: ...


class SelectedSourceInput(BaseModel):
    """Typed public input for an explicitly selected catalog source."""

    model_config = ConfigDict(extra="forbid")

    ref: str = Field(
        min_length=3,
        pattern=r"^[^|\s]+\|[^|\s]+$",
        description="Exact authorized catalog identity in adapter|resource form.",
    )
    key: str | None = Field(
        default=None,
        description="Stable card-local name. Set this explicitly when numeric_conditions refer to this source; their source_key must equal this key, not the catalog ref.",
    )
    label: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    required: StrictBool = True


def _slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "insight"


def declared_comparison_windows(
    sources: list[SourceRef], contracts: dict[str, ResourceContract],
) -> dict[str, list[str]]:
    """Only reviewed catalog declarations constrain authoring; never infer windows."""
    return {
        f"{source.adapter}|{source.resource}": contract.available_comparison_windows
        for source in sources
        if (contract := contracts.get(f"{source.adapter}|{source.resource}")) is not None
        and contract.available_comparison_windows
    }


def resolve_comparison_windows(
    requested: list[str] | None, sources: list[SourceRef], contracts: dict[str, ResourceContract],
) -> list[str]:
    """Resolve omitted defaults; explicit identifiers are never rewritten."""
    if requested is not None:
        if not requested or any(not value.strip() for value in requested):
            raise ValueError("comparison_windows must contain nonempty identifiers")
        return list(requested)
    declared = declared_comparison_windows([source for source in sources if source.required], contracts)
    if not declared:
        return list(InsightCard.model_fields["comparison_windows"].get_default(call_default_factory=True))
    common = set.intersection(*(set(windows) for windows in declared.values()))
    if not common:
        raise ValueError("comparison-window-mismatch: required sources have no common declared window")
    return sorted(common)


def insight_goal(
    what_to_watch: str,
    why_watch: str,
    watch_for: list[str] | None = None,
    questions: list[str] | None = None,
    decision_guidance: str | None = None,
    follow_up_guidance: str | None = None,
    numeric_conditions: list[NumericCondition] | None = None,
) -> str:
    """Create the discovery query without adding another card concept."""
    parts = [what_to_watch.strip(), f"Purpose: {why_watch.strip()}"]
    if watch_for:
        parts.append("Look for: " + "; ".join(watch_for))
    if questions:
        parts.append("Questions: " + "; ".join(questions))
    if decision_guidance and decision_guidance.strip():
        parts.append("Decision guidance: " + decision_guidance.strip())
    if follow_up_guidance and follow_up_guidance.strip():
        parts.append("Follow-up guidance: " + follow_up_guidance.strip())
    if numeric_conditions:
        parts.append(
            "Numeric checks: " + "; ".join(condition.text for condition in numeric_conditions)
        )
    return "\n".join(parts)


def bind_numeric_condition_requirements(
    sources: list[SourceRef], conditions: list[NumericCondition]
) -> list[SourceRef]:
    """Make each authored analytical binding an explicit source requirement."""
    required_by_source: dict[str, set[str]] = defaultdict(set)
    for condition in conditions:
        required_by_source[condition.source_key].add(condition.comparison_key)
    return [
        source.model_copy(
            update={
                "required_comparison_keys": sorted(
                    set(source.required_comparison_keys)
                    | required_by_source.get(source.key, set())
                )
            }
        )
        for source in sources
    ]


@dataclass
class InsightAuthoringService:
    """Conversation-facing card authoring over installed source adapters.

    Candidate retrieval is deliberately bounded before Jev sees the catalog. The
    pool unions lexical, relationship, domain, and context signals; Jev remains
    the required semantic ranker and there is no local relevance fallback.
    """

    registry: SourceRegistry
    engine: Any
    max_candidates: int = 40
    recommendation_threshold: float = 0.60
    related_source_limit: int = 6
    principal: PrincipalContext | None = None

    def _effective_principal(self, principal: PrincipalContext | None) -> PrincipalContext | None:
        return principal or self.principal

    @staticmethod
    def _validate_selected_sources(
        selected_sources: list[SelectedSourceInput | dict[str, Any]],
    ) -> list[SelectedSourceInput]:
        """Validate caller-provided refs before discovery invokes Jev.

        Optional authoring metadata is retained for card construction, but
        source identity and authorization are resolved from the adapter catalog.
        """
        if not isinstance(selected_sources, list):
            raise ValueError("selected_sources must be a list of objects")
        if not selected_sources:
            raise ValueError("selected_sources must not be empty")
        validated: list[SelectedSourceInput] = []
        for index, item in enumerate(selected_sources):
            if not isinstance(item, (SelectedSourceInput, dict)):
                raise ValueError(f"selected_sources[{index}] must be an object")
            try:
                validated.append(
                    item if isinstance(item, SelectedSourceInput)
                    else SelectedSourceInput.model_validate(item)
                )
            except ValidationError as error:
                field = error.errors()[0].get("loc", ("input",))[0]
                raise ValueError(f"selected_sources[{index}].{field} is invalid") from error
        return validated

    @staticmethod
    def source_selection_fingerprint(
        card: InsightCard, discovery: ResourceDiscovery, principal: PrincipalContext | None
    ) -> str:
        """Bind confirmation to policy and authorized catalog identity, not ranking.

        This is a stale-review check, not an authentication credential. Caller
        identity/tenant and source authorization are checked independently. The
        selected source definitions are material; non-selected ranking scores,
        roles, order, and top-k visibility are not.
        """
        policy = card.model_dump(mode="json", exclude={
            "compiled_plan", "onboarding_review", "onboarding_review_history",
            "onboarding_corrections", "status", "approved_at", "approved_by",
        })
        selected_refs = {
            f"{source.adapter}|{source.resource}" for source in card.sources
        }
        selected_catalog = []
        matches = {match.ref: match for match in discovery.matches}
        for ref in sorted(selected_refs):
            match = matches.get(ref)
            selected_catalog.append({
                "ref": ref,
                "definition": None if match is None else match.model_dump(
                    mode="json",
                    exclude={
                        "relevance", "recommended", "suggested_role",
                        "role_probability", "retrieval_signals",
                    },
                ),
            })
        payload = {
            "card": policy,
            "selected_catalog": selected_catalog,
            "catalog_refs": sorted(set(discovery.candidate_refs)),
            "catalog_identity": discovery.catalog_fingerprint,
            "catalog_strategy": discovery.catalog_strategy,
            "principal": principal.model_dump(mode="json") if principal else None,
            "tenant": discovery.authorized_tenant, "truncated": discovery.truncated}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _relationship_seed_refs(
        anchors: list[SourceRef], context: ContextSnapshot | None
    ) -> list[str]:
        """Return approved anchors plus graph endpoints directly connected to them."""
        anchor_refs = {f"{source.adapter}|{source.resource}" for source in anchors}
        seeds = set(anchor_refs)
        # Caller-supplied context is useful evidence, but it must not widen the
        # retrieval neighborhood until an external provider has marked it trusted.
        if context is not None and context.trust == "trusted":
            for fact in context.facts:
                endpoints = {fact.subject_ref}
                if fact.object_ref:
                    endpoints.add(fact.object_ref)
                if endpoints & anchor_refs:
                    seeds.update(endpoints)
        return sorted(seeds)

    @staticmethod
    def _required_relationship_groups(
        anchors: list[SourceRef],
        context: ContextSnapshot | None,
        resources: list[ResourceDescriptor],
    ) -> list[tuple[str, set[str]]]:
        """Map explicit card-context edges to candidate reference groups.

        A context edge is an obligation to preserve at least one authorized,
        Jev-supported neighbor for the referenced object. It is intentionally
        not a requirement to select every representation returned by an
        adapter; one graph node may have dashboard, query, quality, and owner
        projections.
        """
        if context is None or context.trust != "trusted":
            return []
        anchor_refs = {f"{source.adapter}|{source.resource}" for source in anchors}
        targets = {
            fact.object_ref
            for fact in context.facts
            if (
                fact.object_ref
                and fact.subject_ref in anchor_refs
                and fact.relation.lower().startswith("requires_")
            )
        }
        groups: list[tuple[str, set[str]]] = []
        for target in sorted(targets):
            refs: set[str] = set()
            for resource in resources:
                related_refs = {
                    *resource.contract.lineage,
                    *(
                        resource.metadata.get("related_refs", [])
                        if isinstance(resource.metadata.get("related_refs", []), list)
                        else []
                    ),
                    *(
                        resource.metadata.get("related_resources", [])
                        if isinstance(resource.metadata.get("related_resources", []), list)
                        else []
                    ),
                }
                ref = resource_ref(resource)
                if ref == target or target in related_refs:
                    refs.add(ref)
            if refs:
                groups.append((target, refs))
        return groups

    @staticmethod
    def _role_judgment(
        resource: ResourceDescriptor, judgments: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """Prefer governed adapter roles, then fall back to Jev's advisory role."""
        allowed_roles = {"primary", "corroborates", "diagnostic", "quality", "owner"}
        for role in resource.contract.roles:
            normalized = role.strip().lower()
            if normalized in allowed_roles:
                return {"role": normalized, "probability": 1.0}
        judgment = judgments.get(resource_ref(resource), {})
        role = str(judgment.get("role", "unknown"))
        if role not in allowed_roles:
            role = "unknown"
        try:
            probability = float(judgment.get("probability", 0.0))
        except (TypeError, ValueError):
            probability = 0.0
        return {
            "role": role,
            "probability": max(0.0, min(1.0, probability)),
        }

    @staticmethod
    def _source_reason(match: ResourceMatch) -> str:
        """Explain a candidate without pretending ranking proves ownership."""
        reasons: list[str] = []
        if match.recommended:
            reasons.append("Jev judged it materially relevant to the stated goal")
        else:
            reasons.append("it remained in the bounded candidate set for review")
        if "title-match" in match.retrieval_signals:
            reasons.append("its title matches the user's language")
        if "anchor-relationship" in match.retrieval_signals:
            reasons.append("the adapter published a relationship to a selected source")
        if "context-reference" in match.retrieval_signals:
            reasons.append("the supplied context references it")
        if match.contract.domain and match.contract.domain != "unknown":
            reasons.append(f"its catalog domain is {match.contract.domain}")
        if match.suggested_role != "unknown":
            reasons.append(
                f"Jev classified its evidence role as {match.suggested_role} "
                f"({match.role_probability:.2f})"
            )
        return "; ".join(reasons) + "."

    @classmethod
    def build_onboarding_review(
        cls,
        card: InsightCard,
        discovery: ResourceDiscovery,
        *,
        principal: PrincipalContext | None = None,
        explicit_anchors_revalidated: bool = False,
    ) -> InsightCardOnboardingReview:
        selected_refs = {
            resource_ref(
                ResourceDescriptor(
                    adapter=source.adapter,
                    resource=source.resource,
                    kind="selected",
                    title=source.label,
                )
            )
            for source in card.sources
        }
        candidate_refs = {match.ref for match in discovery.matches}
        recommended_refs = {
            match.ref for match in discovery.matches if match.recommended
        }
        missing_recommended = sorted(recommended_refs - selected_refs)
        selected_outside = sorted(selected_refs - candidate_refs)
        by_identity: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        for match in discovery.matches:
            by_identity[
                (match.adapter, match.title.strip().lower(), match.contract.domain)
            ].append(match.ref)
        ambiguous_groups = [
            sorted(refs) for refs in by_identity.values() if len(refs) > 1
        ]
        ambiguous_relevant_groups = (
            [
                refs
                for refs in ambiguous_groups
                if set(refs)
                & (
                    recommended_refs
                    if explicit_anchors_revalidated
                    else selected_refs | recommended_refs
                )
            ]
            if explicit_anchors_revalidated
            else ambiguous_groups
        )
        candidates = [
            OnboardingSourceReview(
                ref=match.ref,
                adapter=match.adapter,
                resource=match.resource,
                kind=match.kind,
                title=match.title,
                description=match.description,
                source_url=match.source_url,
                domain=match.contract.domain,
                tenant_id=match.contract.tenant_id,
                source_status=match.contract.source_status,
                available_comparison_windows=list(match.contract.available_comparison_windows),
                metadata={**match.contract.model_dump(mode="json"),
                          "adapter_metadata": match.metadata},
                selected=match.ref in selected_refs,
                recommended=match.recommended,
                relevance=match.relevance,
                suggested_role=match.suggested_role,
                role_probability=match.role_probability,
                reason=cls._source_reason(match),
                retrieval_signals=match.retrieval_signals,
            )
            for match in discovery.matches
        ]
        questions: list[str] = []
        warnings: list[str] = []
        blockers: list[OnboardingBlocker] = []

        def add_blocker(
            code: OnboardingBlockerCode,
            severity: OnboardingBlockerSeverity,
            layer: str,
            message: str,
            question: str,
            refs: list[str] | None = None,
        ) -> None:
            blockers.append(
                OnboardingBlocker(
                    code=code,
                    severity=severity,
                    layer=layer,
                    message=message,
                    question=question,
                    refs=sorted(set(refs or [])),
                )
            )

        declared_windows = declared_comparison_windows(
            card.sources, {match.ref: match.contract for match in discovery.matches},
        )
        window_issues: list[str] = []
        window_refs: list[str] = []
        undeclared_refs: list[str] = []
        optional_window_issues: list[str] = []
        for source in card.sources:
            ref = f"{source.adapter}|{source.resource}"
            available = declared_windows.get(ref)
            if not available:
                undeclared_refs.append(ref)
            elif not set(card.comparison_windows).issubset(available):
                message = f"{ref}: requested {card.comparison_windows!r}; available {available!r}."
                if source.required:
                    window_issues.append(message)
                    window_refs.append(ref)
                else:
                    optional_window_issues.append(message)
        if undeclared_refs:
            warnings.append("Comparison windows are undeclared; compatibility is unverified for: "
                            + ", ".join(undeclared_refs))
            automatic_routes = [
                method for method in card.delivery_methods
                if method.outcome in {Outcome.NOTIFY, Outcome.ESCALATE}
            ]
            if automatic_routes:
                route_names = ", ".join(method.outcome.value for method in automatic_routes)
                window_issues.append(
                    "Required sources do not declare compatible comparison windows for "
                    f"automatic {route_names} routes. Verify a source-owned comparison "
                    "contract before approval."
                )
                window_refs.extend(undeclared_refs)
        if optional_window_issues:
            warnings.append("Optional source comparison-window mismatch: " + " ".join(optional_window_issues))
        if not card.comparison_windows:
            window_issues.append("The card must select at least one comparison window.")
        if card.compiled_plan is not None and (
            not card.compiled_plan.comparison_windows
            or not set(card.compiled_plan.comparison_windows).issubset(card.comparison_windows)
        ):
            window_issues.append("Cached plan windows must be a nonempty subset of the card's windows.")
        if window_issues:
            question = "Select exact compatible source identifiers and recompile the card before approval."
            questions.append(question)
            add_blocker(
                OnboardingBlockerCode.COMPARISON_WINDOW_MISMATCH,
                OnboardingBlockerSeverity.BLOCK, "comparison-window",
                " ".join(window_issues)[:2000], question, window_refs,
            )

        principal_tenant = principal.tenant_id if principal else discovery.authorized_tenant
        principal_id = principal.principal_id if principal else None
        authorization_evidence = (
            principal.authorization_source if principal else "catalog-tenant-filter"
            if discovery.authorized_tenant
            else "not-provided"
        )
        if principal is None and discovery.authorized_tenant is None:
            add_blocker(
                OnboardingBlockerCode.PRINCIPAL_REQUIRED,
                OnboardingBlockerSeverity.BLOCK,
                "authorization",
                "The onboarding request has no authenticated principal or tenant boundary.",
                "Provide an authenticated principal and tenant scope before approval.",
            )
        elif principal is not None and discovery.authorized_tenant not in {
            None,
            principal.tenant_id,
        }:
            add_blocker(
                OnboardingBlockerCode.UNAUTHORIZED_CANDIDATE,
                OnboardingBlockerSeverity.BLOCK,
                "authorization",
                "The discovery tenant does not match the authenticated principal tenant.",
                "Re-run discovery with the authenticated principal's tenant scope.",
            )

        if not card.sources:
            question = "Select at least one authorized source before approval."
            questions.append(question)
            add_blocker(
                OnboardingBlockerCode.ANCHOR_REQUIRED,
                OnboardingBlockerSeverity.BLOCK,
                "evidence",
                "The card has no human-approved anchor source.",
                question,
            )
        if not card.watch_for and not card.questions and not card.decision_guidance.strip():
            question = (
                "Describe the decision rule in decision_guidance, or add a concrete watch-out "
                "or question. Do not duplicate an existing decision rule as a required watch item."
            )
            questions.append(question)
            add_blocker(
                OnboardingBlockerCode.INTENT_DETAIL_REQUIRED,
                OnboardingBlockerSeverity.REVIEW,
                "human-intent",
                "The card has no decision guidance, watch-out, or question to answer.",
                question,
            )
        if card.delivery_methods and not card.decision_guidance.strip():
            question = (
                "Describe in plain English what should be ignored, investigated, notified, "
                "escalated, or treated as insufficient data."
            )
            questions.append(question)
            add_blocker(
                OnboardingBlockerCode.DECISION_GUIDANCE_REQUIRED,
                OnboardingBlockerSeverity.BLOCK,
                "decision-policy",
                (
                    "The card has push delivery but does not define the human decision "
                    "boundary for expected, ambiguous, actionable, and untrusted states."
                ),
                question,
            )
        if missing_recommended:
            labels = [
                match.title
                for match in discovery.matches
                if match.ref in missing_recommended
            ]
            question = (
                "Review the suggested sources before approval; the draft omitted: "
                + ", ".join(labels)
                + "."
            )
            # Expand mode is an explicit request for caller-owned dynamic
            # related-source retrieval. Fixed cards must resolve proposed scope.
            if card.retrieval_mode == RetrievalMode.FIXED:
                questions.append(question)
                add_blocker(
                    OnboardingBlockerCode.CANDIDATE_SELECTION_REVIEW,
                    OnboardingBlockerSeverity.REVIEW,
                    "human-intent",
                    "Jev found related candidates that the fixed card has not accepted.",
                    question,
                    missing_recommended,
                )
            else:
                warnings.append(
                    "Expand mode will inspect related Jev-recommended sources at run time; "
                    "the caller owns the dynamic-source policy."
                )
        if selected_outside:
            question = (
                "Confirm the explicitly selected source(s) outside this bounded candidate set: "
                + ", ".join(selected_outside)
                + "."
            )
            questions.append(question)
            add_blocker(
                OnboardingBlockerCode.SELECTION_OUTSIDE_DISCOVERY,
                OnboardingBlockerSeverity.BLOCK,
                "retrieval",
                "A selected source was not present in the authorized candidate set.",
                question,
                selected_outside,
            )
        if ambiguous_relevant_groups:
            question = (
                "Disambiguate repeated catalog candidates before approval using owner, "
                "lineage, freshness, or relationship metadata."
            )
            questions.append(question)
            add_blocker(
                OnboardingBlockerCode.DEFINITION_CONFLICT,
                OnboardingBlockerSeverity.REVIEW,
                "meaning",
                "Multiple candidates share a visible identity and may define different things.",
                question,
                [ref for refs in ambiguous_relevant_groups for ref in refs],
            )
        elif ambiguous_groups:
            warnings.append(
                "The bounded candidate set contains ambiguous omitted assets; the ambiguity "
                "does not affect the card's explicit or Jev-recommended sources."
            )
        if discovery.truncated:
            question = (
                "Confirm the catalog search scope or provide another seed before approval; "
                "an omitted source is not proof that the catalog lacks it."
            )
            warnings.append(
                "Discovery was bounded; an omitted source is not proof that the catalog lacks it."
            )
            # Fixed cards already carry human-selected anchors. Once those
            # anchors have been revalidated, pagination is a warning about
            # omitted alternatives rather than a reason to reject the card.
            # Expand-mode cards still need a human review of the bounded
            # dynamic scope because their runtime evidence may widen.
            if (
                not explicit_anchors_revalidated
                or card.retrieval_mode != RetrievalMode.FIXED
                or not card.sources
                or selected_outside
            ):
                questions.append(question)
                add_blocker(
                    OnboardingBlockerCode.CATALOG_INCOMPLETE,
                    OnboardingBlockerSeverity.REVIEW,
                    "retrieval",
                    "The candidate catalog is bounded or paginated.",
                    question,
                )
        if discovery.no_match:
            warning = (
                "No candidate cleared the Jev relevance threshold; source selection needs "
                "explicit human confirmation."
            )
            warnings.append(warning)
            if not card.sources:
                add_blocker(
                    OnboardingBlockerCode.NO_AUTHORIZED_CANDIDATE,
                    OnboardingBlockerSeverity.BLOCK,
                    "retrieval",
                    "No authorized candidate cleared the Jev relevance threshold.",
                    "Provide an authorized seed asset or refine the goal.",
                )
        unauthorized = [
            match.ref
            for match in discovery.matches
            if not match.contract.authorized
            or (
                discovery.authorized_tenant is not None
                and match.contract.tenant_id != discovery.authorized_tenant
            )
        ]
        if unauthorized:
            question = "Re-run discovery through the source authorization boundary before approval."
            questions.append(question)
            add_blocker(
                OnboardingBlockerCode.UNAUTHORIZED_CANDIDATE,
                OnboardingBlockerSeverity.BLOCK,
                "authorization",
                "Discovery contains a candidate outside the caller's authorization boundary.",
                question,
                unauthorized,
            )
        unhealthy = [
            match.ref
            for match in discovery.matches
            if (match.ref in selected_refs or match.recommended)
            and match.contract.source_status != "healthy"
        ]
        if unhealthy:
            question = "Confirm the unhealthy source is trustworthy for this run or choose a healthy replacement."
            questions.append(question)
            add_blocker(
                OnboardingBlockerCode.SOURCE_HEALTH_REVIEW,
                OnboardingBlockerSeverity.REVIEW,
                "freshness",
                "A selected or recommended source is stale, failed, ambiguous, or otherwise not healthy.",
                question,
                unhealthy,
            )
        if not card.delivery_methods:
            add_blocker(
                OnboardingBlockerCode.DELIVERY_POLICY_MISSING,
                OnboardingBlockerSeverity.WARNING,
                "operations",
                "No card-owned delivery method is configured.",
                "Will an external agent or scheduler own delivery for this card?",
            )
        severity_order = {
            OnboardingBlockerSeverity.BLOCK: 2,
            OnboardingBlockerSeverity.REVIEW: 1,
            OnboardingBlockerSeverity.WARNING: 0,
        }
        highest = max(
            (severity_order[blocker.severity] for blocker in blockers), default=-1
        )
        readiness_status = (
            "blocked"
            if highest == 2
            else "needs_human_review"
            if highest == 1
            else "ready_for_approval"
        )
        discovery_receipt = OnboardingDiscoveryReceipt(
            principal_id=principal_id,
            principal_tenant=principal_tenant,
            authorization_evidence=authorization_evidence,
            catalog_provider=discovery.catalog_provider,
            catalog_strategy=discovery.catalog_strategy,
            catalog_cursor=discovery.catalog_cursor,
            candidate_refs=sorted(candidate_refs),
            candidate_count=discovery.candidate_count,
            candidate_limit=discovery.candidate_limit,
            truncated=discovery.truncated,
            evaluator=discovery.evaluator,
        )
        return InsightCardOnboardingReview(
            card_id=card.id,
            source_selection_fingerprint=cls.source_selection_fingerprint(card, discovery, principal),
            status="needs_human_input" if questions else "ready_for_approval",
            readiness_status=readiness_status,
            blockers=blockers,
            principal_id=principal_id,
            principal_tenant=principal_tenant,
            authorization_evidence=authorization_evidence,
            discovery_receipt=discovery_receipt,
            selected_source_refs=sorted(selected_refs),
            recommended_source_refs=sorted(recommended_refs),
            missing_recommended_refs=missing_recommended,
            selected_outside_bounded_candidates=selected_outside,
            ambiguous_candidate_groups=ambiguous_groups,
            source_candidates=candidates,
            questions=questions,
            warnings=warnings,
            evidence_requirements=[
                EvidenceRequirement(key=slot.key, question=slot.question, required=slot.required)
                for slot in base_plan(card).evidence_slots
                if slot.role in {"question", "watch"}
            ],
        )

    async def review(
        self,
        card: InsightCard,
        *,
        adapter: str | None = None,
        limit: int = 10,
        principal: PrincipalContext | None = None,
    ) -> InsightCardOnboardingReview:
        goal = insight_goal(
            card.what_to_watch,
            card.why_watch,
            card.watch_for,
            card.questions,
            card.decision_guidance,
            card.follow_up_guidance,
            card.numeric_conditions,
        )
        effective_principal = self._effective_principal(principal)
        authorized_descriptors = await self._authorize_explicit_anchors(
            list(card.sources), principal=effective_principal
        ) if card.sources else {}
        discovery = await self.discover(
            goal, adapter=adapter, limit=limit, principal=effective_principal
        )
        discovery = await self._retain_explicit_anchors(
            list(card.sources), discovery, principal=effective_principal,
            authorized_descriptors=authorized_descriptors,
        )
        selected_refs = {
            f"{source.adapter}|{source.resource}" for source in card.sources
        }
        explicit_anchors_revalidated = bool(selected_refs) and selected_refs.issubset(
            {match.ref for match in discovery.matches}
        )
        return self.build_onboarding_review(
            card,
            discovery,
            principal=effective_principal,
            explicit_anchors_revalidated=explicit_anchors_revalidated,
        )

    async def _retain_explicit_anchors(
        self,
        anchors: list[SourceRef],
        discovery: ResourceDiscovery,
        *,
        principal: PrincipalContext | None,
        authorized_descriptors: dict[str, ResourceDescriptor] | None = None,
    ) -> ResourceDiscovery:
        """Keep authorized human anchors visible even when discovery is bounded.

        A bounded search result is a recall pool, not the definition of an
        already-selected source. An owner may have supplied a valid source that
        ranked below the review page or was omitted by pagination. Revalidate
        those explicit anchors through the adapter boundary and append them to
        the review evidence. Unauthorized or unavailable anchors remain absent
        and are still blocked by the normal onboarding checks.
        """
        visible_refs = {match.ref for match in discovery.matches}
        missing = [
            source
            for source in anchors
            if f"{source.adapter}|{source.resource}" not in visible_refs
        ]
        if not missing:
            return discovery
        appended: list[ResourceMatch] = []
        for source in missing:
            if authorized_descriptors is not None:
                descriptor = authorized_descriptors.get(
                    f"{source.adapter}|{source.resource}"
                )
            else:
                try:
                    descriptor = await self.registry.authorize(
                        source,
                        authorized_tenants=[principal.tenant_id] if principal else None,
                    )
                except Exception:  # noqa: BLE001 - unavailable anchors remain blocked
                    descriptor = None
            if descriptor is None:
                continue
            ref = f"{source.adapter}|{source.resource}"
            appended.append(
                ResourceMatch(
                    ref=ref,
                    adapter=source.adapter,
                    resource=source.resource,
                    kind=descriptor.kind,
                    title=descriptor.title or source.label,
                    description=descriptor.description,
                    source_url=descriptor.source_url,
                    relevance=1.0,
                    recommended=False,
                    retrieval_signals=["explicit-card-anchor", "authorized-revalidation"],
                    contract=descriptor.contract,
                    metadata=descriptor.metadata,
                )
            )
        if not appended:
            return discovery
        refs = [*discovery.candidate_refs, *(match.ref for match in appended)]
        warnings = [
            *discovery.warnings,
            "Explicit card anchors were revalidated and retained despite bounded discovery.",
        ]
        return discovery.model_copy(
            update={
                "matches": [*discovery.matches, *appended],
                "candidate_refs": sorted(set(refs)),
                "warnings": warnings,
            }
        )

    async def _authorize_explicit_anchors(
        self,
        anchors: list[SourceRef],
        *,
        principal: PrincipalContext | None,
    ) -> dict[str, ResourceDescriptor]:
        """Authorize explicit anchors before bounded discovery invokes Jev."""
        authorized: dict[str, ResourceDescriptor] = {}
        for source in anchors:
            ref = f"{source.adapter}|{source.resource}"
            try:
                descriptor = await self.registry.authorize(
                    source,
                    authorized_tenants=[principal.tenant_id] if principal else None,
                )
            except Exception:  # noqa: BLE001 - fail closed before paid ranking
                descriptor = None
            if descriptor is not None:
                authorized[ref] = descriptor
        unauthorized = [
            f"{source.adapter}|{source.resource}"
            for source in anchors
            if f"{source.adapter}|{source.resource}" not in authorized
        ]
        if unauthorized:
            raise ValueError(
                "selected source refs must come from the authorized adapter catalog "
                "and discover_insight_sources when available: "
                + ", ".join(unauthorized)
            )
        return authorized

    async def discover(
        self,
        goal: str,
        *,
        adapter: str | None = None,
        limit: int = 10,
        principal: PrincipalContext | None = None,
    ) -> ResourceDiscovery:
        if not goal.strip():
            raise ValueError("insight goal must not be empty")
        if not 1 <= limit <= 25:
            raise ValueError("limit must be between 1 and 25")
        effective_principal = self._effective_principal(principal)
        # Fetch a small bounded overage before the hybrid pool trims to the Jev
        # budget. Without this, round-robin fan-in can systematically drop an
        # adapter's final result when the global limit is not divisible by the
        # number of installed adapters.
        search_limit = self.max_candidates + max(1, len(self.registry.adapter_names()))
        catalog = await self.registry.search_resources(
            goal,
            adapter_name=adapter,
            limit=search_limit,
            authorized_tenants=(
                [effective_principal.tenant_id] if effective_principal else None
            ),
        )
        resources = catalog.resources
        pool = build_candidate_pool(goal, resources, limit=self.max_candidates)
        candidates = pool.resources
        judger = self._relevance_judger()
        scores = await judger.rank_resources(goal, candidates)
        role_judgments: dict[str, dict[str, Any]] = {}
        role_classifier = getattr(judger, "classify_resource_roles", None)
        if callable(role_classifier):
            role_judgments = await role_classifier(goal, candidates)
        matches: list[ResourceMatch] = []
        for resource in candidates:
            role_judgment = self._role_judgment(resource, role_judgments)
            matches.append(
                ResourceMatch(
                    ref=resource_ref(resource),
                    adapter=resource.adapter,
                    resource=resource.resource,
                    kind=resource.kind,
                    title=resource.title,
                    description=resource.description,
                    source_url=resource.source_url,
                    relevance=max(
                        0.0, min(1.0, float(scores.get(resource_ref(resource), 0.0)))
                    ),
                    suggested_role=role_judgment["role"],
                    role_probability=role_judgment["probability"],
                    contract=resource.contract,
                    metadata=resource.metadata,
                    retrieval_signals=pool.signals.get(resource_ref(resource), []),
                )
            )
        matches.sort(key=lambda match: (-match.relevance, match.title.lower(), match.ref))
        visible = matches[:limit]
        no_match = not any(
            match.relevance >= self.recommendation_threshold for match in visible
        )
        visible = [
            match.model_copy(
                update={
                    "recommended": (
                        not no_match and match.relevance >= self.recommendation_threshold
                    )
                }
            )
            for match in visible
        ]
        warnings: list[str] = []
        if no_match:
            warnings.append(
                "No catalog candidate cleared the Jev recommendation threshold; "
                "select a source explicitly or refine the insight goal."
            )
        if pool.truncated or catalog.has_more:
            warnings.append(
                "The catalog was bounded before Jev ranking; verify that the selected "
                "source is authorized; card review revalidates explicit anchors."
            )
        if any(resource.contract.tenant_id == "default" for resource in candidates):
            warnings.append(
                "One or more candidates lack an explicit tenant identity; production "
                "deployments should configure tenant-aware adapter metadata."
            )
        warnings.extend(catalog.warnings)
        authorized_tenants = (
            {effective_principal.tenant_id}
            if effective_principal
            else self.registry.authorized_tenants
        )
        catalog_identity = hashlib.sha256(
            json.dumps(
                [
                    resource.model_dump(mode="json")
                    for resource in sorted(resources, key=resource_ref)
                ],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        authorized_tenant = (
            next(iter(authorized_tenants)) if authorized_tenants and len(authorized_tenants) == 1 else None
        )
        return ResourceDiscovery(
            goal=goal,
            matches=visible,
            candidate_refs=[resource_ref(resource) for resource in candidates],
            candidate_count=catalog.total_count,
            candidate_limit=self.max_candidates,
            truncated=pool.truncated or catalog.has_more,
            no_match=no_match,
            candidate_strategy=f"{catalog.strategy}+{pool.strategy}",
            evaluator=judger.name,
            authorized_tenant=authorized_tenant,
            catalog_provider=catalog.provider,
            catalog_strategy=catalog.strategy,
            catalog_fingerprint=catalog_identity,
            catalog_cursor=catalog.next_cursor,
            warnings=warnings,
        )

    async def propose(
        self,
        what_to_watch: str,
        why_watch: str,
        *,
        watch_for: list[str] | None = None,
        questions: list[str] | None = None,
        numeric_conditions: list[NumericCondition] | None = None,
        evidence_requirements: dict[str, StrictBool] | None = None,
        decision_guidance: str | None = None,
        follow_up_guidance: str | None = None,
        selected_sources: list[SelectedSourceInput | dict[str, Any]] | None = None,
        adapter: str | None = None,
        limit: int = 10,
        title: str | None = None,
        comparison_windows: list[str] | None = None,
        delivery_methods: list[DeliveryMethod] | None = None,
        action_confidence_threshold: float = 0.70,
        owner: str | None = None,
        max_source_age_hours: float | None = 24.0,
        retrieval_mode: RetrievalMode = RetrievalMode.EXPAND,
        investigation_mode: InvestigationMode = InvestigationMode.BOUNDED,
        max_investigation_sources: int = 3,
        investigation_threshold: float = 0.60,
        principal: PrincipalContext | None = None,
    ) -> InsightCardProposal:
        validated_selected_sources: list[SelectedSourceInput] | None = None
        if selected_sources is not None:
            validated_selected_sources = self._validate_selected_sources(selected_sources)
        if not what_to_watch.strip():
            raise ValueError("what_to_watch must not be empty")
        if not why_watch.strip():
            raise ValueError("why_watch must not be empty")
        watch_for = list(watch_for or [])
        questions = list(questions or [])
        numeric_conditions = [
            NumericCondition.model_validate(item) for item in (numeric_conditions or [])
        ]
        delivery_methods = list(delivery_methods or [])
        decision_guidance = (decision_guidance or "").strip()
        follow_up_guidance = (follow_up_guidance or "").strip()
        goal = insight_goal(
            what_to_watch,
            why_watch,
            watch_for,
            questions,
            decision_guidance,
            follow_up_guidance,
            numeric_conditions,
        )
        effective_principal = self._effective_principal(principal)
        requested_anchors: list[SourceRef] = []
        if validated_selected_sources is not None:
            requested_anchors = [
                SourceRef(
                    key=item.key or f"source-{_slug(item.ref)}",
                    adapter=item.ref.split("|", 1)[0],
                    resource=item.ref.split("|", 1)[1],
                    label=item.label or item.ref,
                    parameters=item.parameters,
                    required=item.required,
                )
                for item in validated_selected_sources
            ]
            available_keys = {source.key for source in requested_anchors}
            unknown_keys = {condition.source_key for condition in numeric_conditions} - available_keys
            if unknown_keys:
                raise ValueError(
                    "numeric_conditions.source_key must match selected_sources.key; unknown: "
                    + ", ".join(sorted(unknown_keys)) + "; available card-local keys: "
                    + ", ".join(sorted(available_keys))
                )
        authorized_descriptors = await self._authorize_explicit_anchors(
            requested_anchors, principal=effective_principal
        ) if requested_anchors else {}
        discovery = await self.discover(
            goal, adapter=adapter, limit=limit, principal=effective_principal
        )
        matches = {match.ref: match for match in discovery.matches}
        requested = validated_selected_sources
        if requested is None:
            requested = [
                SelectedSourceInput(ref=match.ref)
                for match in discovery.matches
                if match.recommended
            ]
        else:
            discovery = await self._retain_explicit_anchors(
                requested_anchors, discovery, principal=effective_principal,
                authorized_descriptors=authorized_descriptors,
            )
            matches = {match.ref: match for match in discovery.matches}
        unknown = [item.ref for item in requested if item.ref not in matches]
        if unknown:
            raise ValueError(
                "selected source refs must come from the authorized adapter catalog "
                "and discover_insight_sources when available: "
                + ", ".join(str(item) for item in unknown)
            )
        source_refs = [
            SourceRef(
                key=item.key or f"source-{_slug(item.ref)}",
                adapter=matches[item.ref].adapter,
                resource=matches[item.ref].resource,
                label=item.label or matches[item.ref].title,
                parameters=item.parameters,
                required=item.required,
                required_comparison_keys=list(matches[item.ref].contract.required_comparison_keys),
            )
            for item in requested
        ]
        source_refs = bind_numeric_condition_requirements(source_refs, numeric_conditions)
        card_title = (title or what_to_watch.strip().rstrip("."))[:200] or "Untitled insight"
        card = InsightCard(
            id=f"card-{_slug(card_title)}-{uuid4().hex[:8]}",
            title=card_title,
            what_to_watch=what_to_watch,
            why_watch=why_watch,
            watch_for=watch_for,
            questions=questions,
            numeric_conditions=numeric_conditions,
            evidence_requirements=evidence_requirements or {},
            decision_guidance=decision_guidance,
            follow_up_guidance=follow_up_guidance,
            sources=source_refs,
            comparison_windows=resolve_comparison_windows(
                comparison_windows, source_refs, {ref: match.contract for ref, match in matches.items()},
            ),
            delivery_methods=delivery_methods,
            action_confidence_threshold=action_confidence_threshold,
            owner=owner,
            max_source_age_hours=max_source_age_hours,
            retrieval_mode=retrieval_mode,
            investigation_mode=investigation_mode,
            max_investigation_sources=max_investigation_sources,
            investigation_threshold=investigation_threshold,
            principal_id=effective_principal.principal_id if effective_principal else None,
            principal_tenant=effective_principal.tenant_id if effective_principal else None,
        )
        plan = await self.engine.compile(card)
        onboarding_review = self.build_onboarding_review(
            card, discovery, principal=effective_principal
        )
        card = card.model_copy(
            update={
                "onboarding_review": onboarding_review,
                "onboarding_review_history": [onboarding_review],
            }
        )
        setup_questions: list[str] = list(onboarding_review.questions)
        if plan.comparison_windows:
            setup_questions.append(
                f"Confirm the comparison window proposed by Jev: {plan.comparison_windows[0]}."
            )
        if discovery.truncated:
            setup_questions.append(
                "Confirm the selected sources; discovery used a bounded candidate set "
                f"from {discovery.candidate_count} catalog resources."
            )
        return InsightCardProposal(
            card=card,
            plan=plan,
            discovery=discovery,
            onboarding_review=onboarding_review,
            setup_questions=setup_questions,
        )

    async def resolve_bundle(
        self,
        card: InsightCard,
        context: ContextSnapshot | None = None,
        *,
        principal: PrincipalContext | None = None,
    ) -> EvidenceBundle:
        """Resolve a bounded Jev-ranked source bundle for one card evaluation.

        Card sources remain the human-approved anchors. Expansion only adds
        optional catalog resources above the configured relevance threshold;
        missing or weakly related candidates never replace an anchor.
        """
        goal = insight_goal(
            card.what_to_watch,
            card.why_watch,
            card.watch_for,
            card.questions,
            card.decision_guidance,
            card.follow_up_guidance,
            card.numeric_conditions,
        )
        effective_principal = self._effective_principal(principal)
        anchors = list(card.sources)
        retrieval_context = context if context is not None and context.trust == "trusted" else None
        if card.retrieval_mode == RetrievalMode.FIXED:
            return EvidenceBundle(
                card_id=card.id,
                goal=goal,
                anchor_source_keys=[source.key for source in anchors],
                selected_sources=anchors,
                candidate_count=0,
                candidate_limit=self.max_candidates,
                candidate_strategy="fixed-card-sources",
                context_version=context.version if context else None,
                evaluator="fixed-card-sources",
                warnings=["Card retrieval_mode is fixed; no related source expansion was requested."],
            )

        catalog = await self.registry.search_resources(
            goal,
            limit=self.max_candidates,
            authorized_tenants=(
                [effective_principal.tenant_id] if effective_principal else None
            ),
        )
        relationship_catalog = await self.registry.expand_related_resources(
            self._relationship_seed_refs(anchors, retrieval_context),
            limit=self.max_candidates,
            authorized_tenants=(
                [effective_principal.tenant_id] if effective_principal else None
            ),
        )
        resources_by_ref = {
            resource_ref(resource): resource
            for resource in [*catalog.resources, *relationship_catalog.resources]
        }
        resources = list(resources_by_ref.values())
        anchor_refs = {f"{source.adapter}|{source.resource}" for source in anchors}
        anchor_descriptors = {
            resource_ref(resource): resource
            for resource in resources
            if resource_ref(resource) in anchor_refs
        }
        anchor_context = " ".join(_search_text(resource) for resource in anchor_descriptors.values())
        ranked_goal = f"{goal}\nConfirmed anchor context: {anchor_context}" if anchor_context else goal
        pool = build_candidate_pool(
            ranked_goal,
            resources,
            anchors=list(anchor_descriptors.values()),
            context=retrieval_context,
            limit=self.max_candidates,
        )
        candidates = pool.resources
        required_groups = self._required_relationship_groups(anchors, retrieval_context, candidates)
        judger = self._relevance_judger()
        rank_with_context = getattr(judger, "rank_resources_with_context", None)
        if retrieval_context is not None and callable(rank_with_context):
            scores = await rank_with_context(ranked_goal, candidates, retrieval_context)
        else:
            scores = await judger.rank_resources(ranked_goal, candidates)
        matches = [
            ResourceMatch(
                ref=resource_ref(resource),
                adapter=resource.adapter,
                resource=resource.resource,
                kind=resource.kind,
                title=resource.title,
                description=resource.description,
                source_url=resource.source_url,
                relevance=max(0.0, min(1.0, float(scores.get(resource_ref(resource), 0.0)))),
                recommended=False,
                contract=resource.contract,
                retrieval_signals=pool.signals.get(resource_ref(resource), []),
            )
            for resource in candidates
            if resource_ref(resource) not in anchor_refs
        ]
        matches.sort(key=lambda match: (-match.relevance, match.title.lower(), match.ref))
        eligible = [
            match for match in matches if match.relevance >= self.recommendation_threshold
        ]
        selected_matches: list[ResourceMatch] = []
        covered_targets: set[str] = set()
        coverage_warnings: list[str] = []
        for target, group in required_groups:
            if any(match.ref in group for match in selected_matches):
                covered_targets.add(target)
                continue
            group_matches = [match for match in eligible if match.ref in group]
            if not group_matches:
                # A trusted graph obligation can be present even when Jev's
                # generic goal-relevance threshold does not clear. Re-rank
                # within the typed obligation below so a weak lexical score
                # cannot erase an explicitly required context projection.
                group_matches = [match for match in matches if match.ref in group]
            if not group_matches:
                coverage_warnings.append(
                    "No Jev-supported candidate cleared the threshold for required "
                    f"context relationship {target}."
                )
                continue
            selected = group_matches[0]
            if selected.relevance < self.recommendation_threshold:
                coverage_warnings.append(
                    "Jev ranked the top projection for required context relationship "
                    f"{target} below the optional relevance threshold; the trusted "
                    "graph obligation retained it and this bundle remains human-reviewable."
                )
            if selected.ref not in {match.ref for match in selected_matches}:
                if len(selected_matches) < self.related_source_limit:
                    selected_matches.append(selected)
                    covered_targets.add(target)
        selected_refs = {match.ref for match in selected_matches}
        # When the trusted graph declares explicit context obligations, the
        # bundle should contain one Jev-ranked projection per obligation and
        # stop. Filling the remaining slots with merely eligible candidates
        # adds noise, cost, and ambiguous evidence to the workflow. Cards with
        # no graph obligations retain the bounded relevance expansion behavior.
        if not required_groups:
            for match in eligible:
                if len(selected_matches) >= self.related_source_limit:
                    break
                if match.ref not in selected_refs:
                    selected_matches.append(match)
                    selected_refs.add(match.ref)
        if required_groups and len(covered_targets) < len(required_groups):
            coverage_warnings.append(
                "The resolved bundle is missing one or more explicit graph-context "
                "relationships; approval should remain human-reviewed."
            )
        selected_refs = {match.ref for match in selected_matches}
        selected_matches = [match.model_copy(update={"recommended": True}) for match in selected_matches]
        omitted_matches = [match for match in matches if match.ref not in selected_refs]
        selected_sources = list(anchors)
        source_keys = {source.key for source in selected_sources}
        for match in selected_matches:
            base_key = f"related-{_slug(match.ref)}"
            source_key = base_key
            suffix = 2
            while source_key in source_keys:
                source_key = f"{base_key}-{suffix}"
                suffix += 1
            source_keys.add(source_key)
            selected_sources.append(
                SourceRef(
                    key=source_key,
                    adapter=match.adapter,
                    resource=match.resource,
                    label=match.title,
                    required=False,
                    required_comparison_keys=list(match.contract.required_comparison_keys),
                )
            )
        warnings: list[str] = []
        if context is not None and context.trust != "trusted":
            warnings.append(
                "The context snapshot is unverified; it was retained for the receipt but "
                "not used for relationship expansion, required bundle coverage, or Jev ranking."
            )
        if pool.truncated or catalog.has_more:
            warnings.append(
                "The catalog was bounded before Jev ranking; related-source recall depends "
                "on adapter metadata and lexical candidate coverage."
            )
        warnings.extend(coverage_warnings)
        if not selected_matches:
            warnings.append(
                "Jev found no related source above the expansion threshold; the card will "
                "run over its human-approved anchors only."
            )
        if any(resource.contract.tenant_id == "default" for resource in candidates):
            warnings.append(
                "One or more candidates lack explicit tenant identity; production adapters "
                "should configure tenant-aware metadata."
            )
        warnings.extend(catalog.warnings)
        return EvidenceBundle(
            card_id=card.id,
            goal=goal,
            anchor_source_keys=[source.key for source in anchors],
            selected_sources=selected_sources,
            related_matches=selected_matches,
            omitted_matches=omitted_matches,
            candidate_count=catalog.total_count + relationship_catalog.total_count,
            candidate_limit=self.max_candidates,
            candidate_strategy=(
                f"{catalog.strategy}+{relationship_catalog.strategy}+{pool.strategy}"
            ),
            truncated=pool.truncated or catalog.has_more or relationship_catalog.has_more,
            context_version=context.version if context else None,
            evaluator=judger.name,
            warnings=[
                *warnings,
                *relationship_catalog.warnings,
                *(
                    [
                        "The adapter supplied a relationship-aware expansion neighborhood; "
                        "catalog and expansion counts may overlap."
                    ]
                    if relationship_catalog.resources
                    else []
                ),
            ],
        )

    def _relevance_judger(self) -> ResourceRelevanceJudger:
        judger = getattr(self.engine, "judger", None)
        if not hasattr(judger, "rank_resources"):
            raise RuntimeError("the configured Jev judger does not support resource discovery")
        return judger

def proposal_summary(proposal: InsightCardProposal) -> dict[str, Any]:
    """Return a compact MCP-friendly view while retaining the full typed proposal."""
    return {
        "status": proposal.status.value,
        "card_id": proposal.card.id,
        "title": proposal.card.title,
        "what_to_watch": proposal.card.what_to_watch,
        "why_watch": proposal.card.why_watch,
        "watch_for": proposal.card.watch_for,
        "questions": proposal.card.questions,
        "numeric_conditions": [condition.model_dump(mode="json") for condition in proposal.card.numeric_conditions],
        "decision_guidance": proposal.card.decision_guidance,
        "retrieval_mode": proposal.card.retrieval_mode.value,
        "investigation_mode": proposal.card.investigation_mode.value,
        "max_investigation_sources": proposal.card.max_investigation_sources,
        "selected_sources": [source.model_dump(mode="json") for source in proposal.card.sources],
        "recommended_capabilities": [
            {"key": capability, "description": SUPPORTED_CAPABILITIES[capability]}
            for capability in proposal.plan.capabilities
            if capability in SUPPORTED_CAPABILITIES
        ],
        "comparison_windows": proposal.plan.comparison_windows,
        "delivery_methods": [
            method.model_dump(mode="json") for method in proposal.card.delivery_methods
        ],
        "setup_questions": proposal.setup_questions,
        "onboarding_review": proposal.onboarding_review.model_dump(mode="json"),
        "discovery": proposal.discovery.model_dump(mode="json"),
    }
