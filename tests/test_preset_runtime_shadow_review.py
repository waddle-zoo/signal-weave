from __future__ import annotations

from copy import deepcopy

import pytest

from evaluations.preset_runtime_shadow_review import review_report
from evaluations.preset_runtime_shadow_trial import run_trial


@pytest.mark.asyncio
async def test_independent_runtime_shadow_review_accepts_generated_report(tmp_path):
    report = await run_trial(
        tmp_path / "runtime-shadow.json",
        generated_workspace_count=1,
        generated_charts_per_workspace=8,
        generated_seed=17,
    )

    review = review_report(report)

    assert review["passed"] is True
    assert review["workspace_count"] == 4
    assert review["card_count"] == 8


@pytest.mark.asyncio
async def test_independent_runtime_shadow_review_rejects_leaked_secret(tmp_path):
    report = await run_trial(
        tmp_path / "runtime-shadow.json",
        generated_workspace_count=1,
        generated_charts_per_workspace=8,
        generated_seed=17,
    )
    mutated = deepcopy(report)
    mutated["workspaces"][0]["full_dashboard"]["secrets_absent_from_jev_state"] = False

    review = review_report(mutated)

    assert review["passed"] is False
    assert any("leaked a provider secret to Jev" in finding for finding in review["findings"])


@pytest.mark.asyncio
async def test_independent_runtime_shadow_review_rejects_dropped_card(tmp_path):
    report = await run_trial(
        tmp_path / "runtime-shadow.json",
        generated_workspace_count=1,
        generated_charts_per_workspace=8,
        generated_seed=17,
    )
    mutated = deepcopy(report)
    mutated["workspaces"][0].pop("focused_chart")

    review = review_report(mutated)

    assert review["passed"] is False
    assert any("missing focused_chart" in finding for finding in review["findings"])


def test_independent_runtime_shadow_review_rejects_malformed_workspace_without_crashing():
    review = review_report(
        {
            "workspaces": [None],
            "workspace_count": 1,
            "named_workspace_count": 1,
            "generated_workspace_count": 0,
            "card_count": 2,
            "total_jev_requests": 0,
            "not_proven": [],
            "synthetic_preset_transport": True,
            "synthetic_typesafe_transport": True,
            "live_jev_semantics_proven": False,
            "real_preset_tenant_proven": False,
            "passed": True,
        }
    )

    assert review["passed"] is False
    assert any("not an object" in finding for finding in review["findings"])
