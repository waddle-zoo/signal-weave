from __future__ import annotations

import pytest

from evaluations.preset_jev_contract_trial import run_trial


@pytest.mark.asyncio
async def test_preset_snapshots_flow_through_production_jev_contract(tmp_path):
    report = await run_trial(tmp_path / "preset-jev-contract.json")

    assert report["passed"] is True
    assert report["synthetic_typesafe_transport"] is True
    assert report["live_jev_semantics_proven"] is False
    assert report["real_preset_tenant_proven"] is False
    assert report["checks"]["production_jev_evaluator"] is True
    assert report["checks"]["judge_received_normalized_evidence"] is True
    assert report["checks"]["partial_quality_fails_safe"] is True
