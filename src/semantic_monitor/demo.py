"""Load checked-in demo data without making it part of product decision logic."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import DashboardSnapshot, MonitorCard


@dataclass(frozen=True)
class DemoCase:
    id: str
    expected_outcome: str
    expected_recipient: str | None
    dashboard: DashboardSnapshot
    monitor_card: MonitorCard


def default_fixture_path() -> Path:
    repo_path = Path(__file__).resolve().parents[2] / "examples" / "demo-cases.json"
    cwd_path = Path.cwd() / "examples" / "demo-cases.json"
    return cwd_path if cwd_path.exists() else repo_path


def load_demo_cases(path: str | Path | None = None) -> list[DemoCase]:
    fixture_path = Path(path) if path else default_fixture_path()
    payload: dict[str, Any] = json.loads(fixture_path.read_text())
    return [
        DemoCase(
            id=item["id"],
            expected_outcome=item["expected_outcome"],
            expected_recipient=item.get("expected_recipient"),
            dashboard=DashboardSnapshot.model_validate(item["dashboard"]),
            monitor_card=MonitorCard.model_validate(item["monitor_card"]),
        )
        for item in payload["cases"]
    ]


def scenario_catalog(path: str | Path | None = None) -> dict[str, DashboardSnapshot]:
    return {case.id: deepcopy(case.dashboard) for case in load_demo_cases(path)}


def default_cards(path: str | Path | None = None) -> dict[str, MonitorCard]:
    return {case.monitor_card.id: case.monitor_card.model_copy(deep=True) for case in load_demo_cases(path)}


def copy_dashboard(dashboard: DashboardSnapshot) -> DashboardSnapshot:
    return deepcopy(dashboard)
