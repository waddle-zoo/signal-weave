from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

from .diagnostics import AnalysisReport, AnalyticalComparison
from .numeric_conditions import NumericCondition

EvidenceRequirementKey = Annotated[
    str, StringConstraints(pattern=r"^(question|watch):[1-9][0-9]*$"),
]

ComparisonWindows = Annotated[list[str], Field(
    min_length=1, max_length=20,
    description=(
        "Exact source-declared comparison identifiers from discovery's "
        "contract.available_comparison_windows, not translated labels. "
        "These are not required_comparison_keys: those must be exact analytical_comparisons[].key "
        "or reviewed catalog required_comparison_keys. Inspect the source; do not invent keys. "
        "Omit to resolve defaults from required sources; an explicit empty list is invalid."
    ),
)]

WatchConditions = Annotated[list[str], Field(
    max_length=100,
    description=(
        "Owner-defined conditions to check against fresh evidence on each run, in plain language. "
        "Use the card's scope and rules, not bare topic names or a generic analysis checklist. "
        "Unresolved items are required by default; use evidence_requirements only for "
        "explicitly owner-reviewed advisory details. Do not invent materiality rules."
    ),
)]

InvestigationQuestions = Annotated[list[str], Field(
    max_length=100,
    description=(
        "Analytical questions the investigation should answer from evidence on each run. "
        "Do not copy unanswered one-time setup questions here. Ask the owner first; preserve "
        "resolved definitions and policy in decision_guidance and source contracts. "
        "Questions about changing ownership or other non-numeric evidence remain supported."
    ),
)]


class Outcome(StrEnum):
    """The small set of outcomes a card can produce."""

    IGNORE = "ignore"
    INVESTIGATE = "investigate"
    NOTIFY = "notify"
    ESCALATE = "escalate"
    INSUFFICIENT_DATA = "insufficient_data"


class InsightCardStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"


class RetrievalMode(StrEnum):
    FIXED = "fixed"
    EXPAND = "expand"


class InvestigationMode(StrEnum):
    NONE = "none"
    BOUNDED = "bounded"


class WatchStatus(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class QuestionStatus(StrEnum):
    SUPPORTED = "supported"
    NOT_SUPPORTED = "not_supported"
    UNKNOWN = "unknown"


class SourceRef(BaseModel):
    """A card-owned reference to one approved resource in one adapter.

    ``resource`` is intentionally opaque to the insight engine. The adapter owns
    its locator grammar and execution policy. For example, the Superset adapter
    accepts ``dashboard:7``; another adapter can accept ``project:retention`` or
    ``query:orders_daily`` without making that vendor or source language a core
    engine concern.
    """

    key: str = Field(min_length=1, max_length=120)
    adapter: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    resource: str = Field(min_length=1, max_length=500)
    label: str = Field(min_length=1, max_length=240)
    parameters: dict[str, Any] = Field(default_factory=dict, max_length=50)
    required: bool = True
    required_comparison_keys: list[str] = Field(
        default_factory=list, max_length=20,
        description=(
            "Exact analytical_comparisons[].key or reviewed catalog required_comparison_keys, "
            "NOT comparison_window or time-window labels. Inspect the source; do not invent keys."
        ),
    )


class MetricDefinition(BaseModel):
    """An approved, structured definition from a catalog or query adapter.

    This is deliberately not SQL.  A query adapter owns the relation and column
    allowlist; the compiler combines these fields into a bounded query after a
    semantic selector chooses one definition.
    """

    key: str = Field(min_length=1, max_length=160, pattern=r"^[a-zA-Z0-9_.:-]+$")
    label: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    relation: str = Field(min_length=1, max_length=400)
    dialect: Literal["trino", "postgres", "ansi"] = "trino"
    aggregation: Literal[
        "sum", "avg", "min", "max", "count", "count_distinct"
    ]
    measure_column: str | None = Field(default=None, max_length=160)
    time_column: str = Field(min_length=1, max_length=160)
    supported_grains: list[Literal["day", "week", "month", "quarter", "year"]] = Field(
        default_factory=lambda: ["day", "week", "month", "quarter", "year"], max_length=5
    )
    dimensions: dict[str, str] = Field(default_factory=dict, max_length=50)
    partition_column: str | None = Field(default=None, max_length=160)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    population: str = Field(default="", max_length=1000)
    grain: str = Field(default="", max_length=1000)
    lineage: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_metric_definition(self) -> MetricDefinition:
        if self.aggregation in {"sum", "avg", "min", "max", "count_distinct"} and not self.measure_column:
            raise ValueError(f"{self.aggregation} metrics require measure_column")
        if not self.supported_grains:
            raise ValueError("metric definitions require at least one supported grain")
        if any(not name.strip() or not column.strip() for name, column in self.dimensions.items()):
            raise ValueError("metric dimensions require non-empty names and columns")
        return self


class ResourceContract(BaseModel):
    """Typed identity and trust metadata used during discovery and evaluation."""

    tenant_id: str = Field(default="default", min_length=1, max_length=160)
    domain: str = Field(default="unknown", min_length=1, max_length=160)
    scope: str = Field(default="", max_length=1000)
    metric_names: list[str] = Field(default_factory=list, max_length=100)
    metric_definitions: list[MetricDefinition] = Field(default_factory=list, max_length=100)
    available_comparison_windows: list[str] = Field(
        default_factory=list, max_length=20,
        description=(
            "Exact adapter-owned identifiers compatible with this resource's required comparisons. "
            "Empty means undeclared, not support for every window."
        ),
    )
    required_comparison_keys: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Reviewed catalog requirements copied onto proposed source references; "
            "never inferred from returned snapshots."
        ),
    )
    population: str = Field(default="", max_length=1000)
    grain: str = Field(default="", max_length=1000)
    freshness_sla_hours: float | None = Field(default=None, ge=0.0, le=876000.0)
    lineage: list[str] = Field(default_factory=list, max_length=100)
    roles: list[str] = Field(default_factory=list, max_length=30)
    source_status: Literal["healthy", "stale", "failed", "ambiguous", "unknown"] = "healthy"
    authorized: bool = True

    @field_validator("available_comparison_windows")
    @classmethod
    def validate_available_windows(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("available_comparison_windows entries must not be empty")
        return values


class PrincipalContext(BaseModel):
    """Trusted request or deployment identity used to scope onboarding evidence."""

    principal_id: str = Field(min_length=1, max_length=240)
    tenant_id: str = Field(min_length=1, max_length=160)
    scopes: list[str] = Field(default_factory=list, max_length=100)
    authorization_source: str = Field(default="deployment", max_length=160)


class MetricQueryPlan(BaseModel):
    """A fully resolved query plan made only from an approved metric definition."""

    source_key: str
    metric_key: str
    relation: str
    dialect: Literal["trino", "postgres", "ansi"]
    aggregation: Literal["sum", "avg", "min", "max", "count", "count_distinct"]
    measure_column: str | None = None
    time_column: str
    time_grain: Literal["day", "week", "month", "quarter", "year"]
    dimensions: dict[str, str] = Field(default_factory=dict)
    partition_column: str | None = None
    population: str = ""
    grain: str = ""
    selection_probability: float = Field(ge=0.0, le=1.0)
    selected_by: str = "jev-latest"


class CompiledQuery(BaseModel):
    """Deterministic SQL plus the bounded execution parameters."""

    plan: MetricQueryPlan
    sql: str
    parameters: dict[str, str]
    fingerprint: str
    scan_guard: str


class QueryCardStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"


class ReceiptStatus(StrEnum):
    PREPARED = "prepared"
    REPLAYED = "replayed"
    DELIVERED = "delivered"
    DELIVERY_DISABLED = "delivery_disabled"
    FAILED = "failed"


class DecisionReceipt(BaseModel):
    """An idempotent record of one evaluated decision and delivery state."""

    receipt_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=240)
    request_fingerprint: str = Field(default="", max_length=128)
    card_id: str = Field(min_length=1, max_length=160)
    card_version: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=240)
    parent_receipt_id: str | None = Field(default=None, max_length=160)
    workflow_step_key: str | None = Field(default=None, max_length=160)
    context_provider: str | None = Field(default=None, max_length=160)
    context_version: str | None = Field(default=None, max_length=240)
    delivery_mode: Literal["shadow", "live"] = "shadow"
    status: ReceiptStatus
    outcome: Outcome | None = None
    delivery_enabled: bool = False
    delivery_method_keys: list[str] = Field(default_factory=list, max_length=100)
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DecisionFeedbackKind(StrEnum):
    """Caller-owned labels used to evaluate a completed decision."""

    USEFUL = "useful"
    NOISY = "noisy"
    LATE = "late"
    INCOMPLETE = "incomplete"
    UNSAFE = "unsafe"


class DecisionFeedback(BaseModel):
    """An append-only human or agent label attached to one decision receipt."""

    feedback_id: str = Field(min_length=1, max_length=160)
    receipt_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=240)
    card_id: str = Field(min_length=1, max_length=160)
    card_version: int = Field(ge=1)
    kind: DecisionFeedbackKind
    context_provider: str | None = Field(default=None, max_length=160)
    context_version: str | None = Field(default=None, max_length=240)
    expected_outcome: Outcome | None = None
    expected_delivery_method_keys: list[str] = Field(default_factory=list, max_length=100)
    note: str = Field(default="", max_length=4000)
    actor: str = Field(min_length=1, max_length=240)
    principal_tenant: str | None = Field(default=None, max_length=160)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CertificationRecord(BaseModel):
    """Durable, immutable record of a bootstrap or evaluation claim.

    The report body is intentionally opaque to the store.  The record carries
    the identity and input digest needed to determine whether a later lookup
    still refers to the same card, source snapshot, and context view.
    """

    report_id: str = Field(min_length=1, max_length=200)
    kind: Literal["bootstrap", "card_workflow", "retrieval_quality"]
    subject_id: str = Field(min_length=1, max_length=240)
    tenant_id: str = Field(default="deployment", min_length=1, max_length=160)
    subject_version: str = Field(default="", max_length=240)
    status: Literal["ready", "needs_review", "blocked", "shadow", "approved"]
    dataset_ids: list[str] = Field(default_factory=list, max_length=200)
    input_digest: str = Field(default="", min_length=0, max_length=128)
    label_digest: str = Field(default="", min_length=0, max_length=128)
    report: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MetricQueryCard(BaseModel):
    """A plain-language metric request resolved into an approved query plan."""

    id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=8000)
    why: str = Field(min_length=1, max_length=4000)
    sources: list[SourceRef] = Field(default_factory=list, max_length=50)
    requested_dimensions: list[str] = Field(default_factory=list, max_length=50)
    requested_time_grain: Literal["day", "week", "month", "quarter", "year"] | None = None
    query_plan: MetricQueryPlan | None = None
    status: QueryCardStatus = QueryCardStatus.DRAFT
    version: int = Field(default=1, ge=1)
    approved_by: str | None = Field(default=None, max_length=240)
    approved_at: datetime | None = None
    principal_id: str | None = Field(default=None, max_length=240)
    principal_tenant: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_query_card(self) -> MetricQueryCard:
        keys = [source.key for source in self.sources]
        if len(keys) != len(set(keys)):
            raise ValueError("query card source keys must be unique")
        if self.query_plan and self.query_plan.source_key not in keys:
            raise ValueError("query plan must reference one of the query card sources")
        if self.query_plan and any(
            name not in self.query_plan.dimensions for name in self.requested_dimensions
        ):
            raise ValueError("query plan does not contain every requested dimension")
        return self


class ResourceDescriptor(BaseModel):
    """Safe catalog metadata exposed by a source adapter."""

    adapter: str
    resource: str
    kind: str
    title: str
    description: str = ""
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    contract: ResourceContract = Field(default_factory=ResourceContract)


class CatalogSearchPage(BaseModel):
    """A bounded, adapter-owned catalog search result.

    ``resources`` is the only set that may be sent to Jev.  ``total_count`` and
    ``has_more`` make coverage visible to callers instead of allowing a local
    limit to look like a complete catalog.  A source adapter may implement this
    with a native search index, a graph query, or a paginated API.
    """

    resources: list[ResourceDescriptor] = Field(default_factory=list, max_length=500)
    total_count: int = Field(ge=0)
    has_more: bool = False
    next_cursor: str | None = Field(default=None, max_length=500)
    provider: str = Field(min_length=1, max_length=160)
    strategy: str = Field(min_length=1, max_length=160)
    warnings: list[str] = Field(default_factory=list, max_length=50)


class ResourceMatch(BaseModel):
    """A bounded catalog candidate ranked for a user's insight goal."""

    ref: str
    adapter: str
    resource: str
    kind: str
    title: str
    description: str = ""
    source_url: str | None = None
    relevance: float = Field(ge=0.0, le=1.0)
    recommended: bool = False
    suggested_role: Literal[
        "primary",
        "corroborates",
        "diagnostic",
        "quality",
        "owner",
        "unknown",
    ] = "unknown"
    role_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieval_signals: list[str] = Field(default_factory=list, max_length=20)
    contract: ResourceContract = Field(default_factory=ResourceContract)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextFact(BaseModel):
    """A versioned, provenance-bearing fact supplied by an external context system."""

    fact_id: str = Field(min_length=1, max_length=240)
    slot_key: str | None = Field(
        default=None,
        max_length=160,
        description="Optional evidence-plan slot this fact addresses; a tag alone does not fulfill a semantic watch or question.",
    )
    subject_ref: str = Field(min_length=1, max_length=500)
    relation: str = Field(min_length=1, max_length=160)
    object_ref: str | None = Field(default=None, max_length=500)
    statement: str = Field(min_length=1, max_length=4000)
    source_url: str | None = Field(default=None, max_length=2000)
    provenance: list[str] = Field(default_factory=list, max_length=20)


class ContextSnapshot(BaseModel):
    """An immutable context view used for one evaluation."""

    provider: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=240)
    trust: Literal["trusted", "unverified"] = "trusted"
    facts: list[ContextFact] = Field(default_factory=list, max_length=500)
    warnings: list[str] = Field(default_factory=list, max_length=50)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvidenceBundle(BaseModel):
    """The bounded source set resolved for one card evaluation."""

    card_id: str
    goal: str
    anchor_source_keys: list[str] = Field(default_factory=list, max_length=200)
    selected_sources: list[SourceRef] = Field(default_factory=list, max_length=200)
    related_matches: list[ResourceMatch] = Field(default_factory=list, max_length=100)
    omitted_matches: list[ResourceMatch] = Field(default_factory=list, max_length=100)
    candidate_count: int = Field(ge=0)
    candidate_limit: int = Field(ge=1)
    truncated: bool = False
    candidate_strategy: str = "hybrid-metadata"
    context_version: str | None = None
    evaluator: str
    warnings: list[str] = Field(default_factory=list, max_length=50)


class ResourceDiscovery(BaseModel):
    """The inspectable result of goal-to-resource discovery."""

    goal: str
    matches: list[ResourceMatch] = Field(default_factory=list)
    candidate_refs: list[str] = Field(
        default_factory=list,
        max_length=200,
        description=(
            "The bounded adapter-owned candidate pool that Jev ranked. This is "
            "diagnostic retrieval evidence, not a relevance judgment."
        ),
    )
    candidate_count: int = Field(ge=0)
    candidate_limit: int = Field(ge=1)
    truncated: bool = False
    no_match: bool = False
    candidate_strategy: str = "hybrid-metadata"
    evaluator: str
    authorized_tenant: str | None = None
    catalog_provider: str = "unknown"
    catalog_strategy: str = "unknown"
    catalog_cursor: str | None = None
    warnings: list[str] = Field(default_factory=list, max_length=50)


class OnboardingSourceReview(BaseModel):
    """A human-readable review of one candidate during card authoring."""

    ref: str
    adapter: str
    resource: str
    kind: str
    title: str
    description: str = ""
    source_url: str | None = None
    domain: str = "unknown"
    tenant_id: str = "default"
    source_status: str = "unknown"
    available_comparison_windows: list[str] = Field(default_factory=list, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)
    selected: bool = False
    recommended: bool = False
    relevance: float = Field(ge=0.0, le=1.0)
    suggested_role: Literal[
        "primary",
        "corroborates",
        "diagnostic",
        "quality",
        "owner",
        "unknown",
    ] = "unknown"
    role_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=2000)
    retrieval_signals: list[str] = Field(default_factory=list, max_length=20)


class OnboardingBlockerSeverity(StrEnum):
    """How strongly a typed onboarding condition constrains approval."""

    BLOCK = "block"
    REVIEW = "review"
    WARNING = "warning"


class OnboardingBlockerCode(StrEnum):
    """Stable codes for machine-readable onboarding questions."""

    ANCHOR_REQUIRED = "anchor-required"
    PRINCIPAL_REQUIRED = "principal-required"
    NO_AUTHORIZED_CANDIDATE = "no-authorized-candidate"
    UNAUTHORIZED_CANDIDATE = "unauthorized-candidate"
    SELECTION_OUTSIDE_DISCOVERY = "selection-outside-discovery"
    CANDIDATE_SELECTION_REVIEW = "candidate-selection-review"
    CATALOG_INCOMPLETE = "catalog-incomplete"
    SOURCE_HEALTH_REVIEW = "source-health-review"
    DEFINITION_CONFLICT = "definition-conflict"
    INTENT_DETAIL_REQUIRED = "intent-detail-required"
    DECISION_GUIDANCE_REQUIRED = "decision-guidance-required"
    DELIVERY_POLICY_MISSING = "delivery-policy-missing"
    COMPARISON_WINDOW_MISMATCH = "comparison-window-mismatch"


class OnboardingBlocker(BaseModel):
    """One explicit condition a caller must resolve before safe approval."""

    code: OnboardingBlockerCode
    severity: OnboardingBlockerSeverity
    layer: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=2000)
    question: str = Field(min_length=1, max_length=2000)
    refs: list[str] = Field(default_factory=list, max_length=200)


class OnboardingDiscoveryReceipt(BaseModel):
    """Replay identity for one bounded onboarding discovery decision."""

    principal_id: str | None = Field(default=None, max_length=240)
    principal_tenant: str | None = Field(default=None, max_length=160)
    authorization_evidence: str = Field(default="not-provided", max_length=240)
    catalog_provider: str = Field(min_length=1, max_length=160)
    catalog_strategy: str = Field(min_length=1, max_length=160)
    catalog_cursor: str | None = Field(default=None, max_length=500)
    candidate_refs: list[str] = Field(default_factory=list, max_length=200)
    candidate_count: int = Field(ge=0)
    candidate_limit: int = Field(ge=1)
    truncated: bool = False
    evaluator: str = Field(min_length=1, max_length=160)


class OnboardingCorrectionKind(StrEnum):
    """Caller-owned feedback about one onboarding decision."""

    CANDIDATE_ACCEPTED = "candidate-accepted"
    CANDIDATE_REJECTED = "candidate-rejected"
    DEFINITION_CONFIRMED = "definition-confirmed"
    INTENT_CLARIFIED = "intent-clarified"
    OTHER = "other"


class OnboardingCorrection(BaseModel):
    """Durable feedback for an external agent or knowledge graph to consume."""

    correction_id: str = Field(min_length=1, max_length=160)
    card_id: str = Field(min_length=1, max_length=160)
    card_version: int = Field(ge=1)
    kind: OnboardingCorrectionKind
    source_ref: str | None = Field(default=None, max_length=500)
    note: str = Field(default="", max_length=4000)
    principal_id: str | None = Field(default=None, max_length=240)
    principal_tenant: str | None = Field(default=None, max_length=160)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvidenceRequirement(BaseModel):
    """An owner-reviewable semantic prerequisite, not an execution result."""

    key: str
    question: str
    required: StrictBool


class InsightCardOnboardingReview(BaseModel):
    """The confirmation boundary between an agent-drafted card and approval."""

    card_id: str
    status: Literal["needs_human_input", "ready_for_approval"]
    readiness_status: Literal["blocked", "needs_human_review", "ready_for_approval"] = (
        "ready_for_approval"
    )
    blockers: list[OnboardingBlocker] = Field(default_factory=list, max_length=50)
    source_selection_fingerprint: str = Field(default="", max_length=64)
    source_selection_confirmation: str | None = Field(default=None, max_length=4000)
    confirmed_blocker_codes: list[OnboardingBlockerCode] = Field(default_factory=list)
    principal_id: str | None = Field(default=None, max_length=240)
    principal_tenant: str | None = Field(default=None, max_length=160)
    authorization_evidence: str = Field(default="not-provided", max_length=240)
    discovery_receipt: OnboardingDiscoveryReceipt
    selected_source_refs: list[str] = Field(default_factory=list, max_length=200)
    recommended_source_refs: list[str] = Field(default_factory=list, max_length=200)
    missing_recommended_refs: list[str] = Field(default_factory=list, max_length=200)
    selected_outside_bounded_candidates: list[str] = Field(
        default_factory=list, max_length=200
    )
    ambiguous_candidate_groups: list[list[str]] = Field(
        default_factory=list, max_length=50
    )
    source_candidates: list[OnboardingSourceReview] = Field(
        default_factory=list, max_length=100
    )
    questions: list[str] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list, max_length=50)
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list, max_length=200)


class Observation(BaseModel):
    """A normalized fact from any source, not necessarily a dashboard metric."""

    source_key: str = "unknown"
    subject_id: str = "unknown"
    subject_label: str = "unknown"
    subject_type: str = "metric"
    metric: str
    unit: str = "number"
    current: float | None = None
    baseline: float | None = None
    previous: float | None = None
    change_pct: float | None = None
    comparison_baselines: dict[str, float] = Field(default_factory=dict, max_length=20)
    dimensions: dict[str, Any] = Field(default_factory=dict)
    freshness: str | None = None
    source_url: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    """A source-provided or engine-derived fact shown with an insight result."""

    source_key: str = "unknown"
    subject_id: str = "unknown"
    subject_label: str = "unknown"
    statement: str
    values: dict[str, Any] = Field(default_factory=dict)
    source_url: str | None = None
    origin: Literal["source", "context", "derived"] = "source"
    provenance: list[str] = Field(default_factory=list, max_length=20)


class ResourceSnapshot(BaseModel):
    """A bounded, typed snapshot returned by a source adapter.

    ``captured_at`` records when SignalWeave received the snapshot.  Adapters
    that can prove when the underlying result was produced should populate
    ``source_captured_at`` so freshness checks measure the data rather than
    the retrieval request.
    """

    source_key: str
    adapter: str
    resource: str
    title: str
    description: str = ""
    observations: list[Observation] = Field(default_factory=list)
    analytical_comparisons: list[AnalyticalComparison] = Field(default_factory=list, max_length=20)
    evidence: list[Evidence] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    source_url: str | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_captured_at: datetime | None = None
    contract: ResourceContract = Field(default_factory=ResourceContract)


class DeliveryMethod(BaseModel):
    """A configured way to deliver one outcome to a caller-owned destination."""

    key: str = Field(min_length=1, max_length=120)
    outcome: Outcome
    label: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=500)
    instructions: str = Field(default="", max_length=4000)


class EvidenceSlot(BaseModel):
    """One bounded evidence request derived from an approved insight card."""

    key: str = Field(min_length=1, max_length=160)
    role: Literal["primary", "diagnostic", "question", "watch", "quality", "ownership"]
    question: str = Field(min_length=1, max_length=4000)
    source_keys: list[str] = Field(default_factory=list, max_length=100)
    source_refs: list[SourceRef] = Field(default_factory=list, max_length=100)
    required: bool = False
    completion_criteria: str = Field(default="", max_length=2000)
    status: Literal["pending", "fulfilled", "conflicting", "unavailable"] = "pending"
    evidence_fact_ids: list[str] = Field(default_factory=list, max_length=100)
    evidence_source_keys: list[str] = Field(default_factory=list, max_length=100)


class EvidencePlan(BaseModel):
    """Inspectable evidence work needed before an agent should deliver."""

    objective: str = Field(min_length=1, max_length=4000)
    slots: list[EvidenceSlot] = Field(default_factory=list, max_length=200)
    status: Literal["incomplete", "complete", "blocked"] = "incomplete"
    missing_slot_keys: list[str] = Field(default_factory=list, max_length=200)
    conflicting_slot_keys: list[str] = Field(default_factory=list, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=50)
    generated_by: str = "signalweave"
    context_version: str | None = Field(default=None, max_length=240)


class InsightPlan(BaseModel):
    """Jev's bounded execution plan for one insight card."""

    card_id: str
    card_version: int = Field(default=1, ge=1)
    selected_source_keys: list[str]
    comparison_windows: ComparisonWindows
    capabilities: list[str]
    watch_for: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    delivery_method_keys: list[str] = Field(default_factory=list)
    compiled_by: str = "jev-latest"
    card_scope: str
    metric_query_plans: list[MetricQueryPlan] = Field(default_factory=list, max_length=50)
    investigation_mode: InvestigationMode = InvestigationMode.NONE
    max_investigation_sources: int = Field(default=0, ge=0, le=10)
    evidence_slots: list[EvidenceSlot] = Field(default_factory=list, max_length=200)


CardDeliveryMethods = Annotated[list[DeliveryMethod], Field(
    max_length=100,
    description=(
        "Exact owner-approved outcome-to-destination mappings. Match decision_guidance: "
        "investigate and notify are different outcomes and need separate entries when both "
        "should be routed. Policy prose does not create a route. Do not invent recipients "
        "or change an investigation into a notification. Empty means no configured routes; "
        "notify and escalate are unavailable. Actual delivery execution is always caller-owned."
    ),
)]


class InsightCard(BaseModel):
    """The small, free-form contract a person authors for an insight."""

    id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=200)
    what_to_watch: str = Field(min_length=1, max_length=8000)
    why_watch: str = Field(min_length=1, max_length=4000)
    watch_for: WatchConditions = Field(default_factory=list)
    questions: InvestigationQuestions = Field(default_factory=list)
    numeric_conditions: list[NumericCondition] = Field(
        default_factory=list,
        max_length=100,
        description=(
            "Approved numeric projections bound to a card source and analytical comparison. "
            "They are evidence checks only; action selection remains owner/Jev state."
        ),
    )
    evidence_requirements: dict[EvidenceRequirementKey, StrictBool] = Field(
        default_factory=dict,
        max_length=200,
        description=(
            "Reviewed overrides for existing one-based question:N or watch:N slots. "
            "Unspecified slots are required for automatic notification/escalation. "
            "False marks advisory detail, not a conditional prerequisite or a source waiver."
        ),
    )
    decision_guidance: str = Field(
        default="",
        max_length=8000,
        description=(
            "Human-authored guidance describing what ignore, investigate, notify, "
            "escalate, and insufficient_data mean for this card."
        ),
    )
    follow_up_guidance: str = Field(
        default="",
        max_length=8000,
        description=(
            "Optional free-form instructions for an agent after an investigate or "
            "insufficient_data outcome. The caller owns execution and re-evaluation."
        ),
    )
    sources: list[SourceRef] = Field(default_factory=list, max_length=200)
    comparison_windows: ComparisonWindows = Field(
        default_factory=lambda: ["previous_period", "trailing_4_period_average"],
    )
    action_confidence_threshold: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description=(
            "Model-support floor for automatic action, not an accuracy guarantee. "
            "The normal default is 0.70; 1.0 is an advanced override that may prevent automation."
        ),
    )
    owner: str | None = Field(default=None, max_length=240)
    version: int = Field(default=1, ge=1)
    max_source_age_hours: float | None = Field(default=24.0, ge=0.0, le=876000.0)
    delivery_methods: CardDeliveryMethods = Field(default_factory=list)
    retrieval_mode: RetrievalMode = Field(
        default=RetrievalMode.FIXED,
        description=(
            "Retrieval scope: fixed uses the selected source references as provided; expand "
            "allows additional authorized sources when the adapter registry supports bounded "
            "related-source retrieval."
        ),
    )
    investigation_mode: InvestigationMode = Field(
        default=InvestigationMode.NONE,
        description=(
            "Investigation scope: none disables follow-up; bounded enables bounded follow-up "
            "investigation and requires a live SourceRegistry."
        ),
    )
    max_investigation_sources: int = Field(default=3, ge=0, le=10)
    investigation_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    principal_id: str | None = Field(default=None, max_length=240)
    principal_tenant: str | None = Field(default=None, max_length=160)
    compiled_plan: InsightPlan | None = None
    onboarding_review: InsightCardOnboardingReview | None = None
    onboarding_review_history: list[InsightCardOnboardingReview] = Field(
        default_factory=list, max_length=20
    )
    onboarding_corrections: list[OnboardingCorrection] = Field(
        default_factory=list, max_length=100
    )
    status: InsightCardStatus = InsightCardStatus.DRAFT
    approved_by: str | None = Field(default=None, max_length=240)
    approved_at: datetime | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> InsightCard:
        source_keys = [source.key for source in self.sources]
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("source keys must be unique within an insight card")
        delivery_keys = [method.key for method in self.delivery_methods]
        if len(delivery_keys) != len(set(delivery_keys)):
            raise ValueError("delivery method keys must be unique")
        for field_name in ("watch_for", "questions", "comparison_windows"):
            values = getattr(self, field_name)
            if any(not value.strip() for value in values):
                raise ValueError(f"{field_name} entries must not be empty")
        source_by_key = {source.key: source for source in self.sources}
        for condition in self.numeric_conditions:
            source = source_by_key.get(condition.source_key)
            if source is None:
                raise ValueError(
                    f"numeric condition source_key must reference a card source: {condition.source_key}"
                )
            if condition.comparison_key not in source.required_comparison_keys:
                raise ValueError(
                    "numeric condition comparison_key must be listed in the bound source's "
                    f"required_comparison_keys: {condition.comparison_key}"
                )
        requirement_keys = {
            *(f"question:{i + 1}" for i in range(len(self.questions))),
            *(f"watch:{i + 1}" for i in range(len(self.watch_for))),
        }
        if unknown := set(self.evidence_requirements) - requirement_keys:
            raise ValueError(
                "evidence_requirements must identify existing question:N or watch:N slots: "
                + ", ".join(sorted(unknown))
            )
        if self.compiled_plan:
            if not self.compiled_plan.comparison_windows or not set(
                self.compiled_plan.comparison_windows
            ).issubset(self.comparison_windows):
                raise ValueError("compiled_plan comparison windows must be a nonempty subset of card windows")
            if self.compiled_plan.card_id != self.id:
                raise ValueError("compiled_plan must belong to its insight card")
            if self.compiled_plan.card_version != self.version:
                raise ValueError("compiled_plan must match the insight card version")
            if not set(self.compiled_plan.selected_source_keys).issubset(source_keys):
                raise ValueError("compiled_plan may only select card sources")
            if not set(self.compiled_plan.delivery_method_keys).issubset(delivery_keys):
                raise ValueError("compiled_plan may only select card delivery methods")
        return self

    def execution_payload(self) -> dict[str, Any]:
        """Return the bounded card context that may be sent to Jev.

        Onboarding receipts and correction history are durable audit/retrieval
        records, not execution instructions. Sending them on every evaluation
        duplicates the catalog and can exhaust a provider's token budget after
        a card has accumulated review history. Delivery endpoints are also
        application routing data rather than semantic evidence.
        """

        payload = self.model_dump(mode="json")
        for field in (
            "compiled_plan",
            "onboarding_review",
            "onboarding_review_history",
            "onboarding_corrections",
            "status",
            "approved_by",
            "approved_at",
            "principal_id",
            "principal_tenant",
        ):
            payload.pop(field, None)
        payload["delivery_methods"] = [
            {
                key: value
                for key, value in method.items()
                if key != "destination"
            }
            for method in payload.get("delivery_methods", [])
        ]
        return payload


class InsightCardProposal(BaseModel):
    """A human-reviewable card assembled from a natural-language goal."""

    card: InsightCard
    plan: InsightPlan
    discovery: ResourceDiscovery
    onboarding_review: InsightCardOnboardingReview
    setup_questions: list[str] = Field(default_factory=list)
    status: InsightCardStatus = InsightCardStatus.DRAFT


class WatchResult(BaseModel):
    key: str
    watch_for: str
    status: WatchStatus
    probability: float = Field(ge=0.0, le=1.0, description="Probability of present, not confidence in the final status; 0.5 if no valid answer.")
    probabilities: dict[WatchStatus, float] = Field(
        default_factory=dict,
        description="Jev present/absent/unknown distribution; empty for legacy or invalid answers. Code may override status for source failures.",
    )


class QuestionResult(BaseModel):
    key: str
    question: str
    status: QuestionStatus
    probability: float = Field(
        ge=0.0, le=1.0,
        description="Probability the evidence supports a concrete answer, not probability the answer is yes. Low support does not establish contradictory evidence.",
    )


class EvidenceFinding(BaseModel):
    """A typed role for one observation in the final explanation."""

    key: str
    source_key: str
    subject_id: str
    subject_label: str
    metric: str
    role: Literal[
        "driver",
        "corroborates",
        "diagnostic",
        "contradicts",
        "quality",
        "unrelated",
        "unknown",
    ]
    probability: float = Field(ge=0.0, le=1.0)
    suggested_role: Literal[
        "driver",
        "corroborates",
        "diagnostic",
        "contradicts",
        "quality",
        "unrelated",
        "unknown",
    ] | None = None


class InvestigationSelection(BaseModel):
    """One optional source selected for the bounded follow-up stage."""

    source: SourceRef
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    selection_reason: str = Field(min_length=1, max_length=1000)
    retrieval_status: Literal["not_attempted", "succeeded", "failed"] = "not_attempted"
    retrieval_error: str | None = Field(default=None, max_length=1000)


class InvestigationTrace(BaseModel):
    """Inspectable record of the single bounded follow-up retrieval stage."""

    mode: InvestigationMode
    attempted: bool = False
    failed: bool = False
    need_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    candidate_count: int = Field(ge=0)
    candidate_limit: int = Field(ge=0, le=10)
    catalog_count: int = Field(default=0, ge=0)
    catalog_has_more: bool = False
    catalog_strategy: str = "not-requested"
    selected: list[InvestigationSelection] = Field(default_factory=list, max_length=10)
    omitted_refs: list[str] = Field(default_factory=list, max_length=100)
    evaluator: str
    context_version: str | None = None
    warnings: list[str] = Field(default_factory=list, max_length=50)


class WorkflowHandoff(BaseModel):
    """A typed, caller-owned next step for continuing one card decision."""

    status: Literal["complete", "ready", "pending", "blocked"]
    step_key: str = Field(min_length=1, max_length=160)
    action: Literal[
        "suppress",
        "retrieve_evidence",
        "deliver",
        "repair_source",
        "request_review",
        "re_evaluate",
    ]
    objective: str = Field(min_length=1, max_length=4000)
    instructions: str = Field(default="", max_length=8000)
    required_source_keys: list[str] = Field(default_factory=list, max_length=100)
    completion_criteria: str = Field(default="", max_length=4000)
    delivery_method_keys: list[str] = Field(default_factory=list, max_length=100)
    evidence_plan: EvidencePlan | None = None


class RunTelemetry(BaseModel):
    """Provider-neutral measurements attached to one evaluated decision.

    Adapters may publish optional query measurements under
    ``ResourceSnapshot.metadata['telemetry']``. SignalWeave records those
    measurements without interpreting them as correctness evidence, so a
    caller can compare shadow runs on usefulness, latency, and cost.
    """

    wall_time_ms: float = Field(default=0.0, ge=0.0)
    source_fetch_ms: float = Field(default=0.0, ge=0.0)
    source_count: int = Field(default=0, ge=0)
    observation_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    jev_requests: int = Field(default=0, ge=0)
    jev_input_tokens: int = Field(default=0, ge=0)
    jev_output_tokens: int = Field(default=0, ge=0)
    jev_payload_bytes: int = Field(default=0, ge=0)
    jev_payload_budget_bytes: int = Field(default=4_000_000, ge=1_024)
    query_calls: int = Field(default=0, ge=0)
    query_bytes_scanned: int = Field(default=0, ge=0)
    query_cache_hits: int = Field(default=0, ge=0)
    query_cache_misses: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list, max_length=50)


class InsightResult(BaseModel):
    """Typed outcome plus the evidence and per-item judgments behind it."""

    card_id: str
    outcome: Outcome
    delivery_methods: list[DeliveryMethod] = Field(default_factory=list)
    summary: str
    rationale: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    probabilities: dict[str, float] = Field(default_factory=dict)
    watch_results: list[WatchResult] = Field(default_factory=list)
    question_results: list[QuestionResult] = Field(default_factory=list)
    evidence_findings: list[EvidenceFinding] = Field(default_factory=list, max_length=500)
    evidence: list[Evidence] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    analyses: list[AnalysisReport] = Field(default_factory=list, max_length=4000)
    source_keys: list[str] = Field(default_factory=list)
    retrieval: EvidenceBundle | None = None
    context: ContextSnapshot | None = None
    investigation: InvestigationTrace | None = None
    evidence_plan: EvidencePlan | None = None
    workflow: WorkflowHandoff | None = None
    telemetry: RunTelemetry = Field(default_factory=RunTelemetry)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evaluator: str
