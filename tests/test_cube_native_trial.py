from decimal import Decimal
from types import SimpleNamespace

import pytest

from evaluations.cube_native_trial import CubeEpisode, grade


def sample():
    expected = {"metric_id": "finance.net", "current": Decimal("88.80"), "previous": Decimal("100.00"),
                "change_pct": Decimal("-11.20")}
    oracle = SimpleNamespace(expected=lambda resource: expected)
    frozen = {"resource": "metric:net-revenue", "observations": [{"unit": "USD"}],
              "metadata": {"metric_revision": "source-release-17", "data_snapshot_id": "cube-result-sha256:abc"}}
    submitted = {"metric_id": "finance.net", "current": 88.80, "previous": 100.00, "unit": "USD",
                 "definition_revision": "source-release-17", "data_snapshot_id": "cube-result-sha256:abc",
                 "source_refs": ["company|metric:net-revenue"], "current_period": "2026-09",
                 "previous_period": "2026-08", "outcome": "notify", "recipients": ["agent://finance"]}
    return frozen, oracle, submitted


def test_reader_grade_uses_source_revision_and_snapshot_not_hardcoded_r3():
    frozen, oracle, submitted = sample()
    assert all(grade(submitted, frozen, oracle).values())


@pytest.mark.parametrize(("field", "wrong"), [("definition_revision", "r3"),
                                           ("data_snapshot_id", "old-result"),
                                           ("unit", "EUR"), ("current", 100.00),
                                           ("recipients", []), ("outcome", "ignore")])
def test_agreement_on_numbers_does_not_hide_wrong_basis_or_action(field, wrong):
    frozen, oracle, submitted = sample()
    submitted[field] = wrong
    assert not all(grade(submitted, frozen, oracle).values())


def test_explicit_different_metric_does_not_inherit_the_net_alert_policy():
    frozen, oracle, submitted = sample()
    submitted.update(outcome="not_applicable", recipients=[])
    assert all(grade(submitted, frozen, oracle, alternate=True).values())
    submitted.update(outcome="notify", recipients=["agent://finance"])
    assert not all(grade(submitted, frozen, oracle, alternate=True).values())


@pytest.mark.asyncio
async def test_submission_schema_accepts_vendor_revision_ids_and_requires_result_identity():
    episode = CubeEpisode(None, None)
    tool = next(tool for tool in await episode.specs() if tool["name"] == "submit_report")
    properties = tool["parameters"]["properties"]
    assert "pattern" not in properties["definition_revision"]
    assert "data_snapshot_id" in tool["parameters"]["required"]
