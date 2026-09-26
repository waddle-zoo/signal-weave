from __future__ import annotations

import pytest

from evaluations.preset_runtime_shadow_trial import run_trial


@pytest.mark.asyncio
async def test_environment_to_mcp_shadow_path_is_proven_without_live_credits(tmp_path):
    report = await run_trial(tmp_path / "preset-runtime-shadow.json")

    assert report["passed"] is True
    assert report["synthetic_preset_transport"] is True
    assert report["synthetic_typesafe_transport"] is True
    assert report["live_jev_semantics_proven"] is False
    assert report["checks"]["onboarding_and_approval_passed"] is True
    assert report["checks"]["receipts_are_delivery_disabled"] is True
    assert report["checks"]["idempotent_replay_does_not_call_jev"] is True
