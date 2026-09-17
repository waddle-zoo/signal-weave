from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .models import DashboardSnapshot, MonitorCard
from .scenarios import copy_dashboard, default_cards, scenario_catalog
from .superset_client import SupersetClient


class DashboardStore(Protocol):
    def get_dashboard(self, dashboard_id: str) -> DashboardSnapshot: ...


class FixtureStore:
    def __init__(self) -> None:
        self.dashboards = scenario_catalog()
        self.cards = default_cards()

    def get_dashboard(
        self,
        dashboard_id: str,
        chart_ids: list[str] | None = None,
        include_data: bool = True,
    ) -> DashboardSnapshot:
        for dashboard in self.dashboards.values():
            if dashboard.id == dashboard_id:
                snapshot = copy_dashboard(dashboard)
                if chart_ids:
                    snapshot = snapshot.model_copy(
                        update={
                            "charts": [chart for chart in snapshot.charts if chart.id in chart_ids]
                        }
                    )
                return snapshot
        raise KeyError(f"Unknown dashboard: {dashboard_id}")

    def list_dashboards(self) -> list[DashboardSnapshot]:
        return [copy_dashboard(dashboard) for dashboard in self.dashboards.values()]

    def get_dashboard_by_scenario(self, scenario: str) -> DashboardSnapshot:
        return copy_dashboard(self.dashboards[scenario])

    def get_card(self, monitor_id: str) -> MonitorCard:
        return self.cards[monitor_id].model_copy(deep=True)

    def list_cards(self) -> list[MonitorCard]:
        return [card.model_copy(deep=True) for card in self.cards.values()]

    def save_card(self, card: MonitorCard) -> None:
        self.cards[card.id] = card.model_copy(deep=True)


class SupersetStore:
    """Remote dashboard store backed by Superset and a local monitor catalog."""

    def __init__(self, client: SupersetClient, monitor_path: str | Path) -> None:
        self.client = client
        self.monitors = JsonMonitorStore(monitor_path)

    async def list_dashboards(self) -> list[DashboardSnapshot]:
        metadata = await self.client.list_dashboards()
        return [self.client.metadata_to_snapshot(item) for item in metadata]

    async def get_dashboard(
        self,
        dashboard_id: str,
        chart_ids: list[str] | None = None,
        include_data: bool = True,
    ) -> DashboardSnapshot:
        return await self.client.dashboard_snapshot(
            dashboard_id, include_data=include_data, chart_ids=chart_ids
        )

    def get_card(self, monitor_id: str) -> MonitorCard:
        return self.monitors.get(monitor_id)

    def list_cards(self) -> list[MonitorCard]:
        return self.monitors.list()

    def save_card(self, card: MonitorCard) -> None:
        self.monitors.save(card)


class JsonMonitorStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, card: MonitorCard) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        cards = self._load()
        cards[card.id] = card.model_dump(mode="json")
        self.path.write_text(json.dumps(cards, indent=2) + "\n")

    def get(self, monitor_id: str) -> MonitorCard:
        cards = self._load()
        if monitor_id not in cards:
            raise KeyError(f"Unknown monitor: {monitor_id}")
        return MonitorCard.model_validate(cards[monitor_id])

    def list(self) -> list[MonitorCard]:
        return [MonitorCard.model_validate(card) for card in self._load().values()]

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())
