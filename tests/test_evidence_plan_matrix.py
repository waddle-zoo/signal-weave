from __future__ import annotations

import pytest

from evaluations.evidence_plan_matrix import run_matrix


@pytest.mark.asyncio
async def test_evidence_plan_matrix_covers_non_superset_and_failure_boundaries():
    report = await run_matrix()

    assert report["case_count"] == 11
    assert report["failed_cases"] == []
    assert report["passed_cases"] == report["case_count"]
    assert report["adapter_count"] >= 12
    assert "superset" in report["adapters"]
    assert "trino" in report["adapters"]
    assert "cloudwatch" in report["adapters"]
    assert "salesforce" in report["adapters"]
