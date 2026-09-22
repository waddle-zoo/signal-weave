from __future__ import annotations

from evaluations.northstar_retrieval_ablation import (
    ROLE_NAMES,
    _bundle_metrics,
    _representative_cases,
    _select_bundles,
)
from evaluations.northstar_scale_trial import _build_cases, build_scale_fixtures
from signalweave.models import ResourceContract, ResourceDescriptor


def _resource(ref: str) -> ResourceDescriptor:
    adapter, resource = ref.split("|", 1)
    return ResourceDescriptor(
        adapter=adapter,
        resource=resource,
        kind="context",
        title=resource,
        contract=ResourceContract(domain="payments"),
    )


def test_ablation_selectors_keep_anchor_and_cover_distinct_roles():
    anchor = "superset|dashboard:anchor"
    refs = [anchor, "sql|driver", "airflow|quality", "incident|owner", "table|facts"]
    candidates = [_resource(ref) for ref in refs]
    scores = {
        anchor: {"global": 0.2, "related": 0.2, "diagnostic": 0.0, "quality": 0.0, "owner": 0.0},
        "sql|driver": {"global": 0.8, "related": 0.8, "diagnostic": 0.9, "quality": 0.1, "owner": 0.1},
        "airflow|quality": {"global": 0.7, "related": 0.7, "diagnostic": 0.1, "quality": 0.9, "owner": 0.1},
        "incident|owner": {"global": 0.6, "related": 0.6, "diagnostic": 0.1, "quality": 0.1, "owner": 0.9},
        "table|facts": {"global": 0.5, "related": 0.5, "diagnostic": 0.8, "quality": 0.8, "owner": 0.1},
    }

    selected = _select_bundles(candidates, scores, anchor)

    assert selected["goal_only"][0] == anchor
    assert selected["anchor_aware"][0] == anchor
    assert selected["role_aware"][0] == anchor
    assert set(selected["role_aware"]) >= {anchor, "sql|driver", "airflow|quality", "incident|owner"}
    assert ROLE_NAMES == ("related", "diagnostic", "quality", "owner")


def test_bundle_metrics_are_calculated_after_selection():
    result = _bundle_metrics(
        ["superset|anchor", "sql|driver", "airflow|quality"],
        expected_anchor="superset|anchor",
        expected_group={"sql|driver", "airflow|quality", "incident|owner"},
        acceptable={"superset|anchor", "sql|driver", "airflow|quality"},
    )

    assert result["expected_anchor_selected"] is True
    assert result["required_group_recall"] == 2 / 3
    assert result["acceptable_precision"] == 1.0
    assert result["unexpected_selected_refs"] == []


def test_live_ablation_uses_one_case_per_variant():
    config, fixtures, _ = build_scale_fixtures()
    _workflow_cases, retrieval_cases, _cards = _build_cases(
        config, fixtures, tenant_id="northstar-outfitters"
    )

    selected = _representative_cases(retrieval_cases)

    assert len(selected) == 7
    assert len({case.tags[-1] for case in selected}) == 7
    assert all("no-match" not in case.tags for case in selected)
