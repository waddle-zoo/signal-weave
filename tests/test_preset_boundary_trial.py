from __future__ import annotations

import asyncio

from evaluations.preset_boundary_review import review_report
from evaluations.preset_boundary_trial import run_trial


def test_preset_boundary_trial_and_independent_review_pass():
    report = asyncio.run(run_trial())
    review = review_report(report)

    assert report["passed"] is True
    assert review["passed"] is True
    assert report["provider_requests"] == 0
    assert report["typesafe_requests"] == 0


def test_preset_boundary_reviewer_rejects_mutated_pass_report():
    report = asyncio.run(run_trial())
    report["checks"]["tenant_foreign_credential_rejected"] = False

    review = review_report(report)

    assert review["passed"] is False
    assert "serialized boundary checks are not all true" in review["findings"]
