from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from .models import Observation


class SupersetChartSnapshot(BaseModel):
    id: str
    title: str
    metric: str
    metrics: list[str] = Field(default_factory=list)
    viz_type: str = "unknown"
    description: str = ""
    error: str | None = None
    semantic_status: Literal[
        "extracted", "partial", "unsupported", "metadata_only", "no_data"
    ] = "metadata_only"
    semantic_notes: list[str] = Field(default_factory=list, max_length=20)
    result_row_count: int = Field(default=0, ge=0)
    result_columns: list[str] = Field(default_factory=list, max_length=200)
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
