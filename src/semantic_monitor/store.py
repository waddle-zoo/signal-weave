from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from .models import MonitorWorkflow


class WorkflowStore(Protocol):
    def get_workflow(self, workflow_id: str) -> MonitorWorkflow: ...

    def list_workflows(self) -> list[MonitorWorkflow]: ...

    def save_workflow(self, workflow: MonitorWorkflow) -> None: ...


class JsonWorkflowStore:
    """Small atomic catalog for user-authored workflow contracts."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save_workflow(self, workflow: MonitorWorkflow) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        workflows = self._load()
        workflows[workflow.id] = workflow.model_dump(mode="json")
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = temporary.name
                temporary.write(json.dumps(workflows, indent=2) + "\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def get_workflow(self, workflow_id: str) -> MonitorWorkflow:
        workflows = self._load()
        if workflow_id not in workflows:
            raise KeyError(f"Unknown workflow: {workflow_id}")
        return MonitorWorkflow.model_validate(workflows[workflow_id])

    def list_workflows(self) -> list[MonitorWorkflow]:
        return [MonitorWorkflow.model_validate(item) for item in self._load().values()]

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"Workflow catalog must contain a JSON object: {self.path}")
        return payload
