from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from .compiler import SUPPORTED_CAPABILITIES
from .models import (
    ContextSnapshot,
    DeliveryMethod,
    EvidenceBundle,
    InsightCard,
    InsightCardOnboardingReview,
    InsightCardProposal,
    InvestigationMode,
    OnboardingBlocker,
    OnboardingBlockerCode,
    OnboardingBlockerSeverity,
    OnboardingDiscoveryReceipt,
    OnboardingSourceReview,
    PrincipalContext,
    ResourceDescriptor,
    ResourceDiscovery,
    ResourceMatch,
    RetrievalMode,
    SourceRef,
)
from .retrieval import _search_text, build_candidate_pool, resource_ref
from .sources import SourceRegistry


class ResourceRelevanceJudger(Protocol):
    """The Jev capability required to rank bounded catalog candidates."""

    name: str

    async def rank_resources(
        self, goal: str, resources: list[ResourceDescriptor]
    ) -> dict[str, float]: ...


def _slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "insight"


def insight_goal(
    what_to_watch: str,
    why_watch: str,
    watch_for: list[str] | None = None,
    questions: list[str] | None = None,
) -> str:
    """Create the discovery query without adding another card concept."""
    parts = [what_to_watch.strip(), f"Purpose: {why_watch.strip()}"]
    if watch_for:
        parts.append("Look for: " + "; ".join(watch_for))
    if questions:
        parts.append("Questions: " + "; ".join(questions))
    return "\n".join(parts)


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
                metadata=match.contract.model_dump(mode="json"),
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
        if not card.watch_for and not card.questions:
            question = (
                "Add at least one concrete thing to look for or one question the evidence should answer."
            )
            questions.append(question)
            add_blocker(
                OnboardingBlockerCode.INTENT_DETAIL_REQUIRED,
                OnboardingBlockerSeverity.REVIEW,
                "human-intent",
                "The card does not describe a concrete watch-out or question to answer.",
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
        if ambiguous_groups:
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
                [ref for refs in ambiguous_groups for ref in refs],
            )
        if discovery.truncated:
            question = (
                "Confirm the catalog search scope or provide another seed before approval; "
                "an omitted source is not proof that the catalog lacks it."
            )
            questions.append(question)
            warnings.append(
                "Discovery was bounded; an omitted source is not proof that the catalog lacks it."
            )
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
        )

    async def review(
        self,
        card: InsightCard,
        *,
        adapter: str | None = None,
        limit: int = 10,
    ) -> InsightCardOnboardingReview:
        goal = insight_goal(
            card.what_to_watch, card.why_watch, card.watch_for, card.questions
        )
        discovery = await self.discover(goal, adapter=adapter, limit=limit)
        return self.build_onboarding_review(card, discovery, principal=self.principal)

    async def discover(
        self,
        goal: str,
        *,
        adapter: str | None = None,
        limit: int = 10,
    ) -> ResourceDiscovery:
        if not goal.strip():
            raise ValueError("insight goal must not be empty")
        if not 1 <= limit <= 25:
            raise ValueError("limit must be between 1 and 25")
        catalog = await self.registry.search_resources(
            goal, adapter_name=adapter, limit=self.max_candidates
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
                "source is present in the returned candidate set."
            )
        if any(resource.contract.tenant_id == "default" for resource in candidates):
            warnings.append(
                "One or more candidates lack an explicit tenant identity; production "
                "deployments should configure tenant-aware adapter metadata."
            )
        warnings.extend(catalog.warnings)
        authorized_tenants = self.registry.authorized_tenants
        authorized_tenant = (
            next(iter(authorized_tenants)) if authorized_tenants and len(authorized_tenants) == 1 else None
        )
        return ResourceDiscovery(
            goal=goal,
            matches=visible,
            candidate_count=catalog.total_count,
            candidate_limit=self.max_candidates,
            truncated=pool.truncated or catalog.has_more,
            no_match=no_match,
            candidate_strategy=f"{catalog.strategy}+{pool.strategy}",
            evaluator=judger.name,
            authorized_tenant=authorized_tenant,
            catalog_provider=catalog.provider,
            catalog_strategy=catalog.strategy,
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
        selected_sources: list[dict[str, Any]] | None = None,
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
    ) -> InsightCardProposal:
        if not what_to_watch.strip():
            raise ValueError("what_to_watch must not be empty")
        if not why_watch.strip():
            raise ValueError("why_watch must not be empty")
        watch_for = list(watch_for or [])
        questions = list(questions or [])
        delivery_methods = list(delivery_methods or [])
        goal = insight_goal(what_to_watch, why_watch, watch_for, questions)
        discovery = await self.discover(goal, adapter=adapter, limit=limit)
        matches = {match.ref: match for match in discovery.matches}
        requested = selected_sources
        if requested is None:
            requested = [{"ref": match.ref} for match in discovery.matches if match.recommended]
        unknown = [item.get("ref") for item in requested if item.get("ref") not in matches]
        if unknown:
            raise ValueError(
                "selected source refs must come from discover_insight_sources: "
                + ", ".join(str(item) for item in unknown)
            )
        source_refs = [
            SourceRef(
                key=f"source-{_slug(str(item['ref']))}",
                adapter=matches[item["ref"]].adapter,
                resource=matches[item["ref"]].resource,
                label=str(item.get("label") or matches[item["ref"]].title),
                parameters=item.get("parameters") or {},
                required=bool(item.get("required", True)),
            )
            for item in requested
        ]
        card_title = (title or what_to_watch.strip().rstrip("."))[:200] or "Untitled insight"
        card = InsightCard(
            id=f"card-{_slug(card_title)}-{uuid4().hex[:8]}",
            title=card_title,
            what_to_watch=what_to_watch,
            why_watch=why_watch,
            watch_for=watch_for,
            questions=questions,
            sources=source_refs,
            comparison_windows=comparison_windows
            or ["previous_period", "trailing_4_period_average"],
            delivery_methods=delivery_methods,
            action_confidence_threshold=action_confidence_threshold,
            owner=owner,
            max_source_age_hours=max_source_age_hours,
            retrieval_mode=retrieval_mode,
            investigation_mode=investigation_mode,
            max_investigation_sources=max_investigation_sources,
            investigation_threshold=investigation_threshold,
        )
        plan = await self.engine.compile(card)
        onboarding_review = self.build_onboarding_review(card, discovery, principal=self.principal)
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
        self, card: InsightCard, context: ContextSnapshot | None = None
    ) -> EvidenceBundle:
        """Resolve a bounded Jev-ranked source bundle for one card evaluation.

        Card sources remain the human-approved anchors. Expansion only adds
        optional catalog resources above the configured relevance threshold;
        missing or weakly related candidates never replace an anchor.
        """
        goal = insight_goal(card.what_to_watch, card.why_watch, card.watch_for, card.questions)
        anchors = list(card.sources)
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

        catalog = await self.registry.search_resources(goal, limit=self.max_candidates)
        resources = catalog.resources
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
            context=context,
            limit=self.max_candidates,
        )
        candidates = pool.resources
        judger = self._relevance_judger()
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
        selected_matches = [
            match
            for match in matches
            if match.relevance >= self.recommendation_threshold
        ][: self.related_source_limit]
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
                )
            )
        warnings: list[str] = []
        if pool.truncated or catalog.has_more:
            warnings.append(
                "The catalog was bounded before Jev ranking; related-source recall depends "
                "on adapter metadata and lexical candidate coverage."
            )
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
            candidate_count=catalog.total_count,
            candidate_limit=self.max_candidates,
            candidate_strategy=f"{catalog.strategy}+{pool.strategy}",
            truncated=pool.truncated or catalog.has_more,
            context_version=context.version if context else None,
            evaluator=judger.name,
            warnings=warnings,
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
