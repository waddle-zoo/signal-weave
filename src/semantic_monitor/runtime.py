from __future__ import annotations

import os
from dataclasses import dataclass

from .engine import MonitorEngine
from .sources import SourceRegistry
from .store import JsonWorkflowStore, WorkflowStore
from .superset_adapter import SupersetAdapter
from .superset_client import SupersetClient
from .typesafe_adapter import JevJudger, load_api_key


@dataclass
class Runtime:
    workflow_store: WorkflowStore
    sources: SourceRegistry
    engine: MonitorEngine


def build_runtime(mode: str | None = None) -> Runtime:
    mode = (mode or os.getenv("TYPESAFE_MODE", "jev")).lower()
    if mode == "jev":
        key = load_api_key()
        if not key:
            raise RuntimeError(
                "TYPESAFE_MODE=jev requires TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE"
            )
        judger = JevJudger(api_key=key)
    else:
        raise ValueError("SignalWeave production runtime only supports TYPESAFE_MODE=jev")
    url = os.getenv("SUPERSET_URL")
    if not url:
        raise RuntimeError("SignalWeave production runtime requires SUPERSET_URL")
    registry = SourceRegistry(
        [
            SupersetAdapter(
                SupersetClient(
                    base_url=url,
                    username=os.getenv("SUPERSET_USERNAME"),
                    password=os.getenv("SUPERSET_PASSWORD"),
                )
            )
        ]
    )
    return Runtime(
        workflow_store=JsonWorkflowStore(os.getenv("MONITOR_STORE", "data/workflows.json")),
        sources=registry,
        engine=MonitorEngine(judger=judger, registry=registry),
    )
