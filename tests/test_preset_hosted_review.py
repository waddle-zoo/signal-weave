from __future__ import annotations

from copy import deepcopy

import pytest

from evaluations.preset_hosted_review import review_report
from evaluations.preset_hosted_trial import run_trial


@pytest.mark.asyncio
async def test_independent_hosted_review_accepts_current_trial():
    report = await run_trial()

    review = review_report(report)

    assert review["passed"] is True
    assert review["findings"] == []


@pytest.mark.asyncio
async def test_independent_hosted_review_rejects_mutated_policy_evidence():
    report = deepcopy(await run_trial())
    report["workspace_results"][0]["cached_query_guards"] = False

    review = review_report(report)

    assert review["passed"] is False
    assert any("cached-query guards" in finding for finding in review["findings"])
