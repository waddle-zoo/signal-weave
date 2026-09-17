from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .models import Observation


class SupersetChartSnapshot(BaseModel):
    id: str
    title: str
    metric: str
    description: str = ""
    error: str | None = None
    observations: list[Observation] = Field(default_factory=list)
    related_chart_ids: list[str] = Field(default_factory=list)


class SupersetDashboardSnapshot(BaseModel):
    id: str
    title: str
    description: str = ""
    owners: list[str] = Field(default_factory=list)
    charts: list[SupersetChartSnapshot] = Field(default_factory=list)
    source_url: str | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
