from copy import deepcopy
from pathlib import Path

import pytest

from evaluations.judgment_input_ablation import ARMS, retained_inputs, run, variant

PRIMARY = Path("docs/evidence/business-outcomes-live-01")


def test_ablations_do_not_change_policy_questions_or_evidence():
    rows = retained_inputs(PRIMARY)
    assert len(rows) == 6
    for row in rows:
        original = deepcopy(row["state"])
        for arm in ARMS:
            changed = variant(original, arm)
            assert all(changed[k] == original[k] for k in changed)
            assert changed["analyses"] == original["analyses"]
            assert changed["evidence"] == original["evidence"]
            assert changed["insight_card"] == original["insight_card"]
        assert original == row["state"]


def test_different_context_cannot_be_silently_removed():
    state = retained_inputs(PRIMARY)[0]["state"]
    state["card"]["title"] = "Different card"
    with pytest.raises(ValueError, match="differs"):
        variant(state, "deduplicated")


async def test_dry_run_never_needs_credentials(tmp_path):
    result = await run(PRIMARY, tmp_path / "dry")
    assert result == {"status": "dry_run", "attempts": 0}
