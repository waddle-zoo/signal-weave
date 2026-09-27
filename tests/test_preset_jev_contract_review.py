from __future__ import annotations

from copy import deepcopy

import pytest

from evaluations.preset_jev_contract_review import review_report
from evaluations.preset_jev_contract_trial import run_trial


@pytest.mark.asyncio
async def test_independent_preset_jev_contract_review_passes(tmp_path):
    report = await run_trial(tmp_path / "preset-jev-contract.json")

    review = review_report(report)

    assert review["passed"] is True
    assert review["workspace_count"] == 3
    assert review["visualization_count"] >= 10


@pytest.mark.asyncio
async def test_independent_preset_jev_contract_review_rejects_mutated_evidence(tmp_path):
    report = await run_trial(tmp_path / "preset-jev-contract.json")
    mutated = deepcopy(report)
    mutated["workspaces"][0]["typed_judge_input"]["received_evidence"] = False

    review = review_report(mutated)

    assert review["passed"] is False
    assert any("did not send evidence" in finding for finding in review["findings"])


@pytest.mark.asyncio
async def test_independent_preset_jev_contract_review_rejects_raw_handoff_mutation(tmp_path):
    report = await run_trial(tmp_path / "preset-jev-contract.json")
    mutated = deepcopy(report)
    mutated["workspaces"][0]["jev_call_trace"]["full"][-1]["state"]["evidence"].pop()

    review = review_report(mutated)

    assert review["passed"] is False
    assert any(
        "not derived from raw Jev input" in finding
        or "differs from Jev input evidence" in finding
        for finding in review["findings"]
    )


@pytest.mark.asyncio
async def test_independent_preset_jev_contract_review_rejects_filter_context_mutation(tmp_path):
    report = await run_trial(tmp_path / "preset-jev-contract.json")
    mutated = deepcopy(report)
    mutated["workspaces"][0]["typed_judge_input"]["dashboard_filter_statuses"] = [
        "applied"
    ]

    review = review_report(mutated)

    assert review["passed"] is False
    assert any("dashboard filter metadata" in finding for finding in review["findings"])


@pytest.mark.asyncio
async def test_independent_preset_jev_contract_review_rejects_cache_provenance_mutation(tmp_path):
    report = await run_trial(tmp_path / "preset-jev-contract.json")
    mutated = deepcopy(report)
    mutated["workspaces"][0]["typed_judge_input"]["cache_statuses"] = ["cached"]

    review = review_report(mutated)

    assert review["passed"] is False
    assert any("cache provenance" in finding for finding in review["findings"])
