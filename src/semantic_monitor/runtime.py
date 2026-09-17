from __future__ import annotations

import os
from dataclasses import dataclass

from .engine import MonitorEngine
from .store import FixtureStore, SupersetStore
from .superset_client import SupersetClient
from .typesafe_adapter import HeuristicJudger, JevJudger, load_api_key


@dataclass
class Runtime:
    store: FixtureStore | SupersetStore
    engine: MonitorEngine


def build_runtime(mode: str | None = None, source: str | None = None) -> Runtime:
    mode = (mode or os.getenv("TYPESAFE_MODE", "heuristic")).lower()
    if mode == "jev":
        key = load_api_key()
        if not key:
            raise RuntimeError(
                "TYPESAFE_MODE=jev requires TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE"
            )
        judger = JevJudger(api_key=key)
    elif mode == "heuristic":
        judger = HeuristicJudger()
    else:
        raise ValueError(f"Unsupported TYPESAFE_MODE: {mode}")
    source = (source or os.getenv("MONITOR_SOURCE", "fixtures")).lower()
    if source == "superset":
        url = os.getenv("SUPERSET_URL")
        if not url:
            raise RuntimeError("MONITOR_SOURCE=superset requires SUPERSET_URL")
        store = SupersetStore(
            client=SupersetClient(
                base_url=url,
                username=os.getenv("SUPERSET_USERNAME"),
                password=os.getenv("SUPERSET_PASSWORD"),
            ),
            monitor_path=os.getenv("MONITOR_STORE", "data/monitors.json"),
        )
    elif source == "fixtures":
        store = FixtureStore()
    else:
        raise ValueError(f"Unsupported MONITOR_SOURCE: {source}")
    return Runtime(store=store, engine=MonitorEngine(judger=judger))
