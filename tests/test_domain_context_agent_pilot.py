"""Pilot fairness and fixture integrity, not simulated frontier-agent success."""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from evaluations.domain_context_agent_pilot import ContextEpisode, public_case

CASES = json.loads((Path(__file__).parents[1] / "evaluations/data/domain-context-pilot.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
async def test_pilot_arms_have_same_full_company_notes_and_sources(tmp_path, case):
    clock = datetime.now(timezone.utc)
    baseline = ContextEpisode(case, tmp_path / "baseline.db", False, clock)
    treatment = ContextEpisode(case, tmp_path / "treatment.db", True, clock)
    notes = await baseline.call("search_company_notes", {"query": ""})
    treated_notes = await treatment.call("search_company_notes", {"query": ""})
    # Wall-clock creation is audit metadata, not a knowledge difference.
    for item in notes["notes"] + treated_notes["notes"]:
        item.pop("created_at")
    assert notes == treated_notes
    assert len(notes["notes"]) == len(case["notes"])
    for source in case["sources"]:
        assert await baseline.call("read_source_snapshot", {"ref": source["ref"]}) == await treatment.call("read_source_snapshot", {"ref": source["ref"]})
    basic = {tool["name"] for tool in await baseline.specs()}
    extended = {tool["name"] for tool in await treatment.specs()}
    assert basic < extended
    assert extended - basic == {"retrieve_domain_context", "get_context_history"}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
async def test_hidden_labels_cannot_change_context_tools_or_public_input(tmp_path, case):
    changed = copy.deepcopy(case)
    changed["expected"] = {"outcome": "deliberately-wrong-hidden-label", "recipients": ["hidden"]}
    assert public_case(case) == public_case(changed)
    clock = datetime.now(timezone.utc)
    left = ContextEpisode(case, tmp_path / "left.db", True, clock)
    right = ContextEpisode(changed, tmp_path / "right.db", True, clock)
    assert await left.specs() == await right.specs()
    for episode in (left, right):
        response = await episode.call("search_company_notes", {"query": ""})
        assert "deliberately-wrong-hidden-label" not in json.dumps(response)
        assert "expected" not in episode.public
