from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Outcome(StrEnum):
    IGNORE = "ignore"
    INVESTIGATE = "investigate"
    NOTIFY = "notify"
    ESCALATE = "escalate"
    INSUFFICIENT_DATA = "insufficient_data"


class Observation(BaseModel):
    chart_id: str
    chart_title: str
    metric: str
    unit: str = "number"
    current: float | None = None
    baseline: float | None = None
    previous: float | None = None
    change_pct: float | None = None
    dimensions: dict[str, float] = Field(default_factory=dict)
    freshness: str | None = None
    source_url: str | None = None


class ChartSnapshot(BaseModel):
    id: str
    title: str
    metric: str
    description: str = ""
    error: str | None = None
    observations: list[Observation] = Field(default_factory=list)
    related_chart_ids: list[str] = Field(default_factory=list)


class DashboardSnapshot(BaseModel):
    id: str
    title: str
    description: str = ""
    owners: list[str] = Field(default_factory=list)
    charts: list[ChartSnapshot] = Field(default_factory=list)
    source_url: str | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Recipient(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=500)


class MonitorCard(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    dashboard_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=200)
    intent: str = Field(min_length=1, max_length=8000)
    chart_ids: list[str] = Field(default_factory=list, max_length=200)
    comparison_windows: list[str] = Field(
        default_factory=lambda: ["previous_period", "trailing_4_period_average"]
    )
    investigation_hints: list[str] = Field(default_factory=list)
    materiality_threshold_pct: float = Field(default=10.0, ge=0.0, le=100000.0)
    recipients: list[Recipient] = Field(default_factory=list, max_length=100)
    allowed_outcomes: list[Outcome] = Field(
        default_factory=lambda: [
            Outcome.IGNORE,
            Outcome.INVESTIGATE,
            Outcome.NOTIFY,
            Outcome.ESCALATE,
            Outcome.INSUFFICIENT_DATA,
        ]
    )
    owner: str | None = None
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_routing_contract(self) -> MonitorCard:
        safe_outcomes = {Outcome.INVESTIGATE, Outcome.INSUFFICIENT_DATA}
        if not safe_outcomes.intersection(self.allowed_outcomes):
            raise ValueError("allowed_outcomes must include investigate or insufficient_data")
        recipient_keys = [recipient.key for recipient in self.recipients]
        if len(recipient_keys) != len(set(recipient_keys)):
            raise ValueError("recipient keys must be unique")
        return self


class MonitorPlan(BaseModel):
    monitor_id: str
    dashboard_id: str
    selected_chart_ids: list[str]
    comparison_windows: list[str]
    operations: list[str]
    investigation_questions: list[str]
    recipient_keys: list[str]
    compiled_by: str = "heuristic"
    source_intent: str


class Evidence(BaseModel):
    chart_id: str
    chart_title: str
    statement: str
    values: dict[str, Any] = Field(default_factory=dict)
    source_url: str | None = None


class Decision(BaseModel):
    outcome: Outcome
    recipient_key: str | None = None
    rationale: str
    confidence: float | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    monitor_id: str
    dashboard_id: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evaluator: str
