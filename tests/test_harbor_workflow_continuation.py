"""Accounting controls, not evidence of a human or analyst outcome."""

import pytest

from evaluations import harbor_workflow_continuation as continuation
from evaluations import harbor_workflow_journey as journey
from evaluations.harbor_workflow_preflight import _sha


def completed(inputs, uncached=50_000):
    return {"process_complete": True, "usage": {"known": True, "usage": {
        "input_tokens": inputs, "uncached_input_tokens": uncached}},
        "provider_attempts": 0, "provider_usage": {"known": True}}


def fixture(tmp_path):
    parent, current = tmp_path / "parent", tmp_path / "current"
    parent.mkdir()
    current.mkdir()
    paths = {arm: parent / f"onboarding-{arm}.json" for arm in journey.ARMS}
    for path in paths.values():
        journey.write(path, completed(650_000))
    return parent, current, {"parent": str(parent), "parent_reports": {
        arm: _sha(path) for arm, path in paths.items()}}


def test_parent_effort_is_not_reset(tmp_path):
    _, root, metadata = fixture(tmp_path)
    # Closed parent crossed its old cap; new prospective cap explicitly includes it.
    assert continuation.admission(root, metadata) == 0
    journey.write(root / "recurring-signalweave.json", completed(1_200_000))
    with pytest.raises(ValueError, match="Cumulative"):
        continuation.admission(root, metadata)


def test_cannot_edit_parent_to_admit_more_work(tmp_path):
    parent, root, metadata = fixture(tmp_path)
    (parent / "onboarding-baseline.json").write_text("{}")
    with pytest.raises(ValueError, match="parent report changed"):
        continuation.admission(root, metadata)


@pytest.mark.parametrize("failure", ["unknown", "failed", "claim", "provider"])
def test_no_retry_after_unknown_or_incomplete_work(tmp_path, failure):
    _, root, metadata = fixture(tmp_path)
    report = completed(1000)
    if failure == "unknown":
        report["usage"]["known"] = False
    elif failure == "failed":
        report["process_complete"] = False
    elif failure == "provider":
        report["provider_usage"]["known"] = False
    if failure == "claim":
        journey._private_file(root / "recurring-signalweave.claimed", "interrupted")
    else:
        journey.write(root / "recurring-signalweave.json", report)
    with pytest.raises(ValueError):
        continuation.admission(root, metadata)
