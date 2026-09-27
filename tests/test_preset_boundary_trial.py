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
    assert report["provider_credentials"]["hex_bearer_builds"] is True
    assert report["provider_credentials"]["looker_oauth_builds"] is True


def test_preset_boundary_reviewer_rejects_mutated_pass_report():
    report = asyncio.run(run_trial())
    report["checks"]["tenant_foreign_credential_rejected"] = False

    review = review_report(report)

    assert review["passed"] is False
    assert "serialized boundary checks are not all true" in review["findings"]


def test_preset_boundary_reviewer_rejects_missing_direct_client_coverage():
    report = asyncio.run(run_trial())
    report["direct_client_boundary"].pop("looker_redirect_is_not_followed")

    review = review_report(report)

    assert review["passed"] is False
    assert "direct hosted-client boundary coverage is incomplete" in review["findings"]
