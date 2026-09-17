from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

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
    accepts ``dashboard:7``; a future SQL adapter can accept ``query:orders_daily``
    without making SQL a core engine concern.
    """

    key: str = Field(min_length=1, max_length=120)
    adapter: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    resource: str = Field(min_length=1, max_length=500)
    label: str = Field(min_length=1, max_length=240)
    parameters: dict[str, Any] = Field(default_factory=dict, max_length=50)
    required: bool = True


class ResourceDescriptor(BaseModel):
    """Safe catalog metadata exposed by a source adapter."""

    adapter: str
    resource: str
    kind: str
    title: str
    description: str = ""
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class ResourceDiscovery(BaseModel):
    """The inspectable result of goal-to-resource discovery."""

    goal: str
    matches: list[ResourceMatch] = Field(default_factory=list)
    candidate_count: int = Field(ge=0)
    candidate_limit: int = Field(ge=1)
    truncated: bool = False
    evaluator: str


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
    compiled_plan: InsightPlan | None = None
    status: InsightCardStatus = InsightCardStatus.DRAFT

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
    evidence: list[Evidence] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    source_keys: list[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evaluator: str
