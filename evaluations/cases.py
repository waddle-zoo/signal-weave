"""Load evaluation cases without making them part of product decision logic."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from semantic_monitor.models import DashboardSnapshot, MonitorCard


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    expected_outcome: str
    expected_recipient: str | None
    dashboard: DashboardSnapshot
    monitor_card: MonitorCard


def default_fixture_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "demo-cases.json"


def load_evaluation_cases(path: str | Path | None = None) -> list[EvaluationCase]:
    fixture_path = Path(path) if path else default_fixture_path()
    payload: dict[str, Any] = json.loads(fixture_path.read_text())
    return [
        EvaluationCase(
            id=item["id"],
            expected_outcome=item["expected_outcome"],
            expected_recipient=item.get("expected_recipient"),
            dashboard=DashboardSnapshot.model_validate(item["dashboard"]),
            monitor_card=MonitorCard.model_validate(item["monitor_card"]),
        )
        for item in payload["cases"]
    ]
