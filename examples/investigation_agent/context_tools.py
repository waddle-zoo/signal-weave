from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from signalweave.models import ContextFact

from .agent import InvestigationTool


def load_json_tools(path: str | Path) -> list[InvestigationTool]:
    """Load caller-owned fact tools from a fixture or an integration export.

    The file contains facts, not executable queries.  A production deployment
    should replace these tools with bounded adapters for its warehouse, BI
    system, campaign platform, incident system, and ownership graph.
    """

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("tools"), list):
        raise ValueError("evidence tool file must contain a tools array")
    tools: list[InvestigationTool] = []
    for raw_tool in payload["tools"]:
        if not isinstance(raw_tool, dict):
            raise ValueError("each evidence tool must be an object")
        key = str(raw_tool.get("key") or "").strip()
        description = str(raw_tool.get("description") or "").strip()
        raw_facts = raw_tool.get("facts", [])
        default_slot_key = str(raw_tool.get("slot_key") or "").strip() or None
        if not key or not description or not isinstance(raw_facts, list):
            raise ValueError("each evidence tool needs key, description, and facts")
        parsed_facts: list[ContextFact] = []
        for raw_fact in raw_facts:
            fact = ContextFact.model_validate(raw_fact)
            if default_slot_key and not fact.slot_key:
                fact = fact.model_copy(update={"slot_key": default_slot_key})
            parsed_facts.append(fact)
        facts = tuple(parsed_facts)

        async def collect(_request: Any, *, facts: tuple[ContextFact, ...] = facts) -> tuple[ContextFact, ...]:
            return facts

        tools.append(InvestigationTool(key=key, description=description, collect=collect))
    return tools
