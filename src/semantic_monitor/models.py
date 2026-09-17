from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, model_validator


class Outcome(StrEnum):
    IGNORE = "ignore"
    INVESTIGATE = "investigate"
    NOTIFY = "notify"
    ESCALATE = "escalate"
    INSUFFICIENT_DATA = "insufficient_data"


class SourceRef(BaseModel):
    """A workflow-owned reference to one approved resource in one adapter.

    ``resource`` is intentionally opaque to the workflow engine. The adapter owns
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


class Observation(BaseModel):
    """A normalized fact from any source, not necessarily a dashboard metric."""

    source_key: str = "unknown"
    subject_id: str = Field(
        default="unknown",
        validation_alias=AliasChoices("subject_id", "chart_id"),
    )
    subject_label: str = Field(
        default="unknown",
        validation_alias=AliasChoices("subject_label", "chart_title"),
    )
    subject_type: str = "metric"
    metric: str
    unit: str = "number"
    current: float | None = None
    baseline: float | None = None
    previous: float | None = None
    change_pct: float | None = None
    dimensions: dict[str, Any] = Field(default_factory=dict)
    freshness: str | None = None
    source_url: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    """A source-provided or engine-derived fact shown with the decision."""

    source_key: str = "unknown"
    subject_id: str = Field(
        default="unknown",
        validation_alias=AliasChoices("subject_id", "chart_id"),
    )
    subject_label: str = Field(
        default="unknown",
        validation_alias=AliasChoices("subject_label", "chart_title"),
    )
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


class Recipient(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=500)


class MonitorWorkflow(BaseModel):
    """The user-authored workflow contract evaluated by SignalWeave."""

    id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=200)
    intent: str = Field(min_length=1, max_length=8000)
    sources: list[SourceRef] = Field(default_factory=list, max_length=200)
    comparison_windows: list[str] = Field(
        default_factory=lambda: ["previous_period", "trailing_4_period_average"],
        max_length=20,
    )
    investigation_hints: list[str] = Field(default_factory=list, max_length=50)
    materiality_threshold_pct: float = Field(default=10.0, ge=0.0, le=100000.0)
    action_confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    materiality_definition: str | None = Field(default=None, max_length=4000)
    outcome_guidance: dict[str, str] = Field(default_factory=dict, max_length=10)
    recipients: list[Recipient] = Field(default_factory=list, max_length=100)
    allowed_outcomes: list[Outcome] = Field(default_factory=lambda: list(Outcome))
    owner: str | None = None
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_routing_contract(self) -> MonitorWorkflow:
        safe_outcomes = {Outcome.INVESTIGATE, Outcome.INSUFFICIENT_DATA}
        if not safe_outcomes.intersection(self.allowed_outcomes):
            raise ValueError("allowed_outcomes must include investigate or insufficient_data")
        source_keys = [source.key for source in self.sources]
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("source keys must be unique within a workflow")
        recipient_keys = [recipient.key for recipient in self.recipients]
        if len(recipient_keys) != len(set(recipient_keys)):
            raise ValueError("recipient keys must be unique")
        unknown_guidance = set(self.outcome_guidance) - {
            outcome.value for outcome in self.allowed_outcomes
        }
        if unknown_guidance:
            raise ValueError("outcome_guidance may only describe allowed_outcomes")
        return self


class MonitorPlan(BaseModel):
    workflow_id: str
    selected_source_keys: list[str]
    comparison_windows: list[str]
    operations: list[str]
    investigation_questions: list[str]
    recipient_keys: list[str]
    compiled_by: str = "jev-latest"
    source_intent: str


class Decision(BaseModel):
    outcome: Outcome
    recipient_key: str | None = None
    rationale: str
    confidence: float | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    workflow_id: str
    source_keys: list[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evaluator: str
