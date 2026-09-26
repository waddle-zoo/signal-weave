from __future__ import annotations

import pytest

from evaluations.preset_hosted_trial import run_trial


@pytest.mark.asyncio
async def test_preset_hosted_trial_passes_all_declared_checks():
    report = await run_trial()

    assert report["passed"] is True
    assert all(report["checks"].values())
    assert {item["workspace"] for item in report["workspace_results"]} == {
        "northstar",
        "harbor-bank",
        "orbitworks",
    }
    assert len(report["viz_types"]) == 12
    assert "custom_plugin" in report["viz_types"]
