from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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
    population: str = Field(default="", max_length=1000)
    grain: str = Field(default="", max_length=1000)
    freshness_sla_hours: float | None = Field(default=None, ge=0.0, le=876000.0)
    lineage: list[str] = Field(default_factory=list, max_length=100)
    roles: list[str] = Field(default_factory=list, max_length=30)
    source_status: Literal["healthy", "stale", "failed", "ambiguous", "unknown"] = "healthy"
    authorized: bool = True


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
    status: ReceiptStatus
    outcome: Outcome | None = None
    delivery_enabled: bool = False
    delivery_method_keys: list[str] = Field(default_factory=list, max_length=100)
    result: dict[str, Any] = Field(default_factory=dict)
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


class ContextFact(BaseModel):
    """A versioned, provenance-bearing fact supplied by an external context system."""

    fact_id: str = Field(min_length=1, max_length=240)
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
    DELIVERY_POLICY_MISSING = "delivery-policy-missing"


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


class InsightCardOnboardingReview(BaseModel):
    """The confirmation boundary between an agent-drafted card and approval."""

    card_id: str
    status: Literal["needs_human_input", "ready_for_approval"]
    readiness_status: Literal["blocked", "needs_human_review", "ready_for_approval"] = (
        "ready_for_approval"
    )
    blockers: list[OnboardingBlocker] = Field(default_factory=list, max_length=50)
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
    """A bounded, typed snapshot returned by a source adapter."""

    source_key: str
    adapter: str
    resource: str
    title: str
    description: str = ""
    observations: list[Observation] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    source_url: str | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    contract: ResourceContract = Field(default_factory=ResourceContract)


class DeliveryMethod(BaseModel):
    """A configured way to deliver one outcome to a caller-owned destination."""

    key: str = Field(min_length=1, max_length=120)
    outcome: Outcome
    label: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=500)
    instructions: str = Field(default="", max_length=4000)


class InsightPlan(BaseModel):
    """Jev's bounded execution plan for one insight card."""

    card_id: str
    card_version: int = Field(default=1, ge=1)
    selected_source_keys: list[str]
    comparison_windows: list[str]
    capabilities: list[str]
    watch_for: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    delivery_method_keys: list[str] = Field(default_factory=list)
    compiled_by: str = "jev-latest"
    card_scope: str
    metric_query_plans: list[MetricQueryPlan] = Field(default_factory=list, max_length=50)
    investigation_mode: InvestigationMode = InvestigationMode.NONE
    max_investigation_sources: int = Field(default=0, ge=0, le=10)


class InsightCard(BaseModel):
    """The small, free-form contract a person authors for an insight."""

    id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=200)
    what_to_watch: str = Field(min_length=1, max_length=8000)
    why_watch: str = Field(min_length=1, max_length=4000)
    watch_for: list[str] = Field(default_factory=list, max_length=100)
    questions: list[str] = Field(default_factory=list, max_length=100)
    sources: list[SourceRef] = Field(default_factory=list, max_length=200)
    comparison_windows: list[str] = Field(
        default_factory=lambda: ["previous_period", "trailing_4_period_average"],
        max_length=20,
    )
    action_confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    owner: str | None = Field(default=None, max_length=240)
    version: int = Field(default=1, ge=1)
    max_source_age_hours: float | None = Field(default=24.0, ge=0.0, le=876000.0)
    delivery_methods: list[DeliveryMethod] = Field(default_factory=list, max_length=100)
    retrieval_mode: RetrievalMode = RetrievalMode.FIXED
    investigation_mode: InvestigationMode = InvestigationMode.NONE
    max_investigation_sources: int = Field(default=3, ge=0, le=10)
    investigation_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    principal_id: str | None = Field(default=None, max_length=240)
    principal_tenant: str | None = Field(default=None, max_length=160)
    compiled_plan: InsightPlan | None = None
    onboarding_review: InsightCardOnboardingReview | None = None
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
        if self.compiled_plan:
            if self.compiled_plan.card_id != self.id:
                raise ValueError("compiled_plan must belong to its insight card")
            if self.compiled_plan.card_version != self.version:
                raise ValueError("compiled_plan must match the insight card version")
            if not set(self.compiled_plan.selected_source_keys).issubset(source_keys):
                raise ValueError("compiled_plan may only select card sources")
            if not set(self.compiled_plan.delivery_method_keys).issubset(delivery_keys):
                raise ValueError("compiled_plan may only select card delivery methods")
        return self


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
    probability: float = Field(ge=0.0, le=1.0)


class QuestionResult(BaseModel):
    key: str
    question: str
    status: QuestionStatus
    probability: float = Field(ge=0.0, le=1.0)


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
        "contradicts",
        "quality",
        "unrelated",
        "unknown",
    ]
    probability: float = Field(ge=0.0, le=1.0)
    suggested_role: Literal[
        "driver",
        "corroborates",
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
    source_keys: list[str] = Field(default_factory=list)
    retrieval: EvidenceBundle | None = None
    context: ContextSnapshot | None = None
    investigation: InvestigationTrace | None = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evaluator: str
