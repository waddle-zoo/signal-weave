"""Exploratory readiness gates for generalized insight-card onboarding.

This module deliberately lives under ``evaluations``.  It is a prototype of a
review contract, not a production API.  The purpose is to test whether the
human and enterprise failure modes are expressible as typed, actionable
questions before moving anything into ``signalweave.models``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from signalweave.models import InsightCard, InsightCardOnboardingReview, ResourceDiscovery


class BlockerSeverity(StrEnum):
    BLOCK = "block"
    REVIEW = "review"
    WARNING = "warning"


class ReadinessStatus(StrEnum):
    BLOCKED = "blocked"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    READY_FOR_APPROVAL = "ready_for_approval"


@dataclass(frozen=True)
class ReadinessBlocker:
    """One focused question or gate that explains why approval is unsafe."""

    code: str
    severity: BlockerSeverity
    layer: str
    message: str
    question: str
    refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class OnboardingReadiness:
    """Inspectable onboarding status independent of any vendor or UI."""

    status: ReadinessStatus
    blockers: tuple[ReadinessBlocker, ...]

    @property
    def blocker_codes(self) -> tuple[str, ...]:
        return tuple(blocker.code for blocker in self.blockers)

    @property
    def human_questions(self) -> tuple[str, ...]:
        return tuple(blocker.question for blocker in self.blockers)


def assess_readiness(
    card: InsightCard,
    discovery: ResourceDiscovery,
    review: InsightCardOnboardingReview,
    *,
    principal_tenant: str | None,
) -> OnboardingReadiness:
    """Convert discovery facts into explicit approval blockers.

    The rules are intentionally conservative and source-agnostic.  They do not
    decide relevance; Jev has already done that.  They decide whether the
    evidence and trust boundary are complete enough for a human to approve the
    proposed card.
    """

    blockers: list[ReadinessBlocker] = []
    selected_refs = {f"{source.adapter}|{source.resource}" for source in card.sources}
    recommended_refs = {match.ref for match in discovery.matches if match.recommended}
    missing_recommended = sorted(recommended_refs - selected_refs)

    if not principal_tenant:
        blockers.append(
            ReadinessBlocker(
                code="principal-required",
                severity=BlockerSeverity.BLOCK,
                layer="authorization",
                message="Discovery has no tenant or principal boundary.",
                question="Which enterprise principal should scope this card?",
            )
        )

    unauthorized = [
        match.ref
        for match in discovery.matches
        if not match.contract.authorized
        or (principal_tenant and match.contract.tenant_id != principal_tenant)
    ]
    if unauthorized:
        blockers.append(
            ReadinessBlocker(
                code="unauthorized-candidate",
                severity=BlockerSeverity.BLOCK,
                layer="authorization",
                message="The discovery result contains a candidate outside the caller's authorization boundary.",
                question="Re-run discovery through the source's authorization boundary before approval.",
                refs=tuple(sorted(set(unauthorized))),
            )
        )

    if not card.sources:
        blockers.append(
            ReadinessBlocker(
                code="anchor-required",
                severity=BlockerSeverity.BLOCK,
                layer="evidence",
                message="The card has no human-approved anchor source.",
                question="Which authorized source should anchor this monitoring goal?",
            )
        )

    if not card.watch_for and not card.questions:
        blockers.append(
            ReadinessBlocker(
                code="intent-detail-required",
                severity=BlockerSeverity.REVIEW,
                layer="human-intent",
                message="The card does not describe a concrete watch-out or question to answer.",
                question="Add at least one concrete thing to look for or one question the evidence should answer.",
            )
        )

    if discovery.no_match and not card.sources:
        blockers.append(
            ReadinessBlocker(
                code="no-authorized-candidate",
                severity=BlockerSeverity.BLOCK,
                layer="retrieval",
                message="No authorized candidate cleared the Jev relevance threshold.",
                question="Provide an authorized seed asset or refine the goal.",
            )
        )

    if review.selected_outside_bounded_candidates:
        blockers.append(
            ReadinessBlocker(
                code="selection-outside-discovery",
                severity=BlockerSeverity.BLOCK,
                layer="retrieval",
                message="A selected source was not present in the authorized candidate set.",
                question="Rediscover this source under the current principal before approval.",
                refs=tuple(review.selected_outside_bounded_candidates),
            )
        )

    if missing_recommended:
        blockers.append(
            ReadinessBlocker(
                code="candidate-selection-review",
                severity=BlockerSeverity.REVIEW,
                layer="human-intent",
                message="Jev found related candidates that the card has not accepted yet.",
                question="Confirm which suggested sources belong in this workflow.",
                refs=tuple(missing_recommended),
            )
        )

    if discovery.truncated:
        blockers.append(
            ReadinessBlocker(
                code="catalog-incomplete",
                severity=BlockerSeverity.REVIEW,
                layer="retrieval",
                message="The candidate catalog is bounded or paginated; omission is not proof of irrelevance.",
                question="Confirm the catalog search scope or provide another seed before approval.",
            )
        )

    selected_matches = [
        match
        for match in discovery.matches
        if match.ref in selected_refs or match.ref in recommended_refs
    ]
    unhealthy = [
        match.ref for match in selected_matches if match.contract.source_status != "healthy"
    ]
    if unhealthy:
        blockers.append(
            ReadinessBlocker(
                code="source-health-review",
                severity=BlockerSeverity.REVIEW,
                layer="freshness",
                message="A selected source is stale, failed, ambiguous, or otherwise not healthy.",
                question="Confirm the source is trustworthy for this run or choose a healthy replacement.",
                refs=tuple(sorted(unhealthy)),
            )
        )

    identity_groups: dict[tuple[str, str, str], list[str]] = {}
    for match in discovery.matches:
        identity = (
            match.title.strip().lower(),
            match.contract.domain.strip().lower(),
            match.kind.strip().lower(),
        )
        identity_groups.setdefault(identity, []).append(match.ref)
    conflicts = [
        ref
        for refs in identity_groups.values()
        if len(refs) > 1 and any(ref in recommended_refs for ref in refs)
        for ref in refs
    ]
    if conflicts:
        blockers.append(
            ReadinessBlocker(
                code="definition-conflict",
                severity=BlockerSeverity.REVIEW,
                layer="meaning",
                message="Multiple recommended assets share the same visible identity and may define different things.",
                question="Choose the governed definition or explain how these candidates differ.",
                refs=tuple(sorted(set(conflicts))),
            )
        )

    if not card.delivery_methods:
        blockers.append(
            ReadinessBlocker(
                code="delivery-policy-missing",
                severity=BlockerSeverity.WARNING,
                layer="operations",
                message="No card-owned delivery method is configured; the caller must provide the delivery path.",
                question="Will an external agent or scheduler own delivery for this card?",
            )
        )

    severity_order = {
        BlockerSeverity.BLOCK: 2,
        BlockerSeverity.REVIEW: 1,
        BlockerSeverity.WARNING: 0,
    }
    highest = max((severity_order[blocker.severity] for blocker in blockers), default=-1)
    status = (
        ReadinessStatus.BLOCKED
        if highest == 2
        else ReadinessStatus.NEEDS_HUMAN_REVIEW
        if highest == 1
        else ReadinessStatus.READY_FOR_APPROVAL
    )
    return OnboardingReadiness(status=status, blockers=tuple(blockers))
