"""Installed-workflow transfer fixtures built from the enterprise journeys.

The target journeys remain the future monitoring set.  Calibration examples are
generated independently, then identity-bound to the target catalog so the
agent sees familiar business families without receiving target future data.
The calibration cases carry explicit historical retrieval-scope labels for the
first two legitimate assets defined by the existing family specs.  This is a
known-family regression with supplied context-asset labels, not proof of
novice card authoring without context or a novel-company holdout.
"""

from __future__ import annotations

import copy
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from evaluations.bootstrap_agent_trial import shift_timestamps
from evaluations.bootstrap_scenarios import _specs
from evaluations.enterprise_onboarding_journeys import _replace, journeys

DEFAULT_SEED = 20261004
CALIBRATION_OFFSET = 1009
_CONDITIONS = ("quiet", "event", "quality")


def _legitimate_assets(family: str, catalog: list[dict[str, Any]]) -> set[str]:
    spec = next(item for item in _specs("holdout") if item["family"] == family)
    legitimate = set(zip(spec["titles"][:2], spec["descriptions"][:2], strict=True))
    return {
        item["resource"] for item in catalog
        if (item["title"], item["description"]) in legitimate
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _with_cutoff(period: dict[str, Any]) -> dict[str, Any]:
    period = copy.deepcopy(period)
    for snapshot in period["snapshots"].values():
        snapshot.setdefault("metadata", {})["reporting_cutoff"] = period["as_of"]
    return period


def _target_resource_map(target: dict[str, Any], calibration: dict[str, Any]) -> dict[str, str]:
    target_by_identity: dict[tuple[str, str], list[str]] = defaultdict(list)
    for item in target["public"]["catalog"]:
        target_by_identity[(item["title"], item["kind"])].append(item["resource"])
    calibration_by_identity: dict[tuple[str, str], list[str]] = defaultdict(list)
    for item in calibration["public"]["catalog"]:
        calibration_by_identity[(item["title"], item["kind"])].append(item["resource"])
    result = {}
    for identity, calibration_resources in calibration_by_identity.items():
        target_resources = target_by_identity.get(identity, [])
        if not target_resources or len(target_resources) != len(calibration_resources):
            raise ValueError(f"calibration asset has no target identity: {identity!r}")
        result.update(dict(zip(calibration_resources, target_resources, strict=True)))
    if len(result) != len(calibration["public"]["catalog"]):
        raise ValueError("calibration resource identities are not unique")
    return result


def _normalize_target_public(public: dict[str, Any], tenant: str) -> dict[str, Any]:
    public = copy.deepcopy(public)
    for descriptor in public["catalog"]:
        descriptor["contract"]["tenant_id"] = tenant
    for period in [public["onboarding"], *public["periods"]]:
        for snapshot in period["snapshots"].values():
            snapshot["contract"]["tenant_id"] = tenant
            snapshot.setdefault("metadata", {})["tenant"] = tenant
            snapshot["source_key"] = snapshot["resource"]
            for observation in snapshot.get("observations", []):
                observation["source_key"] = snapshot["resource"]
            for evidence in snapshot.get("evidence", []):
                evidence["source_key"] = snapshot["resource"]
    return public


def _destination_map(target: dict[str, Any], calibration: dict[str, Any]) -> dict[str, dict[str, str]]:
    target_by_label = {item["label"]: item for item in target["public"]["destinations"]}
    result = {}
    for source in calibration["public"]["destinations"]:
        target_destination = target_by_label.get(source["label"])
        if target_destination is None:
            raise ValueError(f"calibration destination has no target label: {source['label']!r}")
        result[source["key"]] = {
            "key": target_destination["key"],
            "destination": target_destination["destination"],
        }
    return result


def _normalize_calibration_period(
    period: dict[str, Any],
    *,
    resource_map: dict[str, str],
    tenant: str,
) -> dict[str, Any]:
    normalized = _with_cutoff(period)
    for old_resource, new_resource in resource_map.items():
        normalized = _replace(normalized, old_resource, new_resource)
    normalized["period_id"] = f"calibration-{_digest(period['period_id'])}"
    normalized["snapshots"] = {
        f"company_mcp|{snapshot['resource']}": snapshot
        for snapshot in normalized["snapshots"].values()
    }
    for snapshot in normalized["snapshots"].values():
        snapshot["contract"]["tenant_id"] = tenant
        snapshot.setdefault("metadata", {})["tenant"] = tenant
        snapshot["metadata"]["period_id"] = normalized["period_id"]
        snapshot["source_key"] = snapshot["resource"]
        for observation in snapshot.get("observations", []):
            observation["source_key"] = snapshot["resource"]
        for evidence in snapshot.get("evidence", []):
            evidence["source_key"] = snapshot["resource"]
            evidence["provenance"] = [snapshot["resource"]]
    return normalized


def _calibration_example(
    calibration: dict[str, Any],
    target: dict[str, Any],
    condition: str,
    *,
    resource_map: dict[str, str],
    destination_map: dict[str, dict[str, str]],
    approved_resources: set[str],
) -> tuple[dict[str, Any], str]:
    period_id, label = next(
        (period_id, label)
        for period_id, label in calibration["private"]["periods"].items()
        if label["condition"] == condition
    )
    original_period = next(
        period for period in calibration["public"]["periods"] if period["period_id"] == period_id
    )
    period = _normalize_calibration_period(
        original_period,
        resource_map=resource_map,
        tenant=target["scenario_id"],
    )
    recipients = [destination_map[key]["key"] for key in label["recipients"]]
    endpoints = {destination_map[key]["key"]: destination_map[key]["destination"] for key in label["recipients"]}
    required_refs = [
        f"company_mcp|{resource_map[ref.split('|', 1)[1]]}"
        for ref in label["required_evidence_refs"]
    ]
    expected_retrieval_refs = [
        f"company_mcp|{resource_map[resource]}"
        for resource in sorted(approved_resources)
    ]
    resources = [
        snapshot for snapshot in period["snapshots"].values()
        if f"company_mcp|{snapshot['resource']}" in expected_retrieval_refs
    ]
    example = {
        "id": f"calibration-{_digest(target['scenario_id'] + ':' + condition)}",
        "as_of": period["as_of"],
        "expected_outcome": label["outcome"],
        "expected_delivery_destinations": endpoints,
        "required_evidence_refs": required_refs,
        "expected_retrieval_refs": expected_retrieval_refs,
        "resources": resources,
    }
    if sorted(recipients) != sorted(endpoints):
        raise ValueError("calibration route projection is inconsistent")
    return example, period["as_of"]


def _rebase_before(examples: list[dict[str, Any]], onboarding_as_of: str) -> list[dict[str, Any]]:
    latest = max(
        datetime.fromisoformat(resource["metadata"]["reporting_cutoff"].replace("Z", "+00:00"))
        for example in examples
        for resource in example["resources"]
    )
    onboarding = datetime.fromisoformat(onboarding_as_of.replace("Z", "+00:00"))
    delta = onboarding - timedelta(hours=1) - latest
    return shift_timestamps(copy.deepcopy(examples), delta)


def build_transfers(seed: int = DEFAULT_SEED) -> list[dict[str, Any]]:
    """Build six known-family transfer scenarios with independent calibration data."""

    target_scenarios = journeys(seed)
    calibration_scenarios = journeys(seed + CALIBRATION_OFFSET)
    if len(target_scenarios) != 6 or len(calibration_scenarios) != 6:
        raise ValueError("enterprise journeys must provide six target and calibration families")

    result = []
    for target, calibration in zip(target_scenarios, calibration_scenarios, strict=True):
        public = _normalize_target_public(target["public"], target["scenario_id"])
        public["onboarding"] = _with_cutoff(public["onboarding"])
        public["periods"] = [_with_cutoff(period) for period in public["periods"]]
        resource_map = _target_resource_map(target, calibration)
        destination_map = _destination_map(target, calibration)
        calibration_assets = _legitimate_assets(
            target["private"]["family"], calibration["public"]["catalog"]
        )
        if len(calibration_assets) != 2:
            raise ValueError("family specs must identify exactly two legitimate calibration assets")
        examples = [
            _calibration_example(
                calibration,
                target,
                condition,
                resource_map=resource_map,
                destination_map=destination_map,
                approved_resources=calibration_assets,
            )[0]
            for condition in _CONDITIONS
        ]
        examples = _rebase_before(examples, public["onboarding"]["as_of"])
        result.append({
            "schema_version": target.get("schema_version", 1),
            "scorer_version": target.get("scorer_version", 1),
            "scenario_id": target["scenario_id"],
            "public": public,
            "private": copy.deepcopy(target["private"]),
            "owner_examples": examples,
        })
    return result
