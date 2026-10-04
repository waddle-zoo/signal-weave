"""Independent mechanical audit of paired onboarding artifacts.

The live comparison reviewer answers whether the monitoring arms were paired
fairly and whether their structured results were scored correctly.  This
reviewer answers a different question: did onboarding retain enough owner
context, and did SignalWeave produce a reusable executable card rather than
only another block of agent notes?

It deliberately does not call Luna or Jev and does not pretend that token
overlap proves semantic correctness.  Policy fidelity still needs a human or
independent narrative review.  Historical artifacts can be inspected with
``--allow-historical`` but are never silently promoted to current evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from evaluations.bootstrap_agent_trial import (
    canonical,
    select_scenarios,
    source_fingerprint,
    write_exclusive,
)
from evaluations.bootstrap_scenarios import build_scenarios, dataset_digest


def _fixture_options(config: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {
        "seed": config["seed"],
        "split": config["split"],
    }
    if config.get("connector_profile", False):
        options["connector_profile"] = True
    if config.get("catalog_noise", 0):
        options["catalog_noise"] = config["catalog_noise"]
    return options


def _same(left: Any, right: Any) -> bool:
    return canonical(left) == canonical(right)


def _ref(source: dict[str, Any]) -> str:
    return f"{source.get('adapter')}|{source.get('resource')}"


def _catalog_refs(scenario: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Return all authorized refs and the canonical (non-noise) subset."""

    catalog = scenario["public"]["catalog"]
    all_refs = {_ref(item) for item in catalog}
    canonical_refs = {
        _ref(item)
        for item in catalog
        if not (item.get("metadata") or {}).get("scope")
    }
    return all_refs, canonical_refs


def _load_card(report_path: Path, row: dict[str, Any]) -> dict[str, Any] | None:
    card_id = row.get("card_id")
    scenario_id = row.get("scenario_id")
    if not card_id or not scenario_id:
        return None
    path = report_path.parent / str(scenario_id) / "luna_signalweave_jev" / "cards.json"
    try:
        cards = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    card = cards.get(card_id) if isinstance(cards, dict) else None
    return card if isinstance(card, dict) else None


def _policy_anchors(policy: str) -> set[str]:
    """Extract only review hints, never use this as a semantic scorer."""

    words = re.findall(r"\b[a-z][a-z0-9_+-]*\b", policy.lower())
    numeric = re.findall(r"\b\d+(?:\.\d+)?%?\b", policy.lower())
    important = {
        word
        for word in words
        if word in {
            "ignore", "notify", "investigate", "insufficient_data", "missing",
            "incomplete", "complete", "previous", "double", "doubles", "twice",
            "causal", "causation", "population", "coverage", "partitions", "watermark",
        }
    }
    return set(numeric) | important


def _coverage(policy: str, text: str) -> dict[str, Any]:
    required = _policy_anchors(policy)
    normalized = text.lower()
    present = sorted(token for token in required if token in normalized)
    missing = sorted(required - set(present))
    return {
        "anchor_count": len(required),
        "present_count": len(present),
        "recall": len(present) / len(required) if required else 1.0,
        "missing": missing,
        "method": "mechanical policy-anchor hints; not semantic validation",
    }


def _expected_outcomes(scenario: dict[str, Any]) -> set[str]:
    return {
        str(label["outcome"])
        for label in scenario["private"]["periods"].values()
        if label.get("outcome") != "ignore"
    }


def _card_quality(
    card: dict[str, Any] | None,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    public = scenario["public"]
    all_refs, canonical_refs = _catalog_refs(scenario)
    policy = str(public["owner_answers"].get("materiality", ""))
    if card is None:
        return {
            "artifact_present": False,
            "artifact_kind": "missing",
            "mechanical_pass": False,
            "semantic_status": "unassessed",
        }
    sources = card.get("sources") if isinstance(card.get("sources"), list) else []
    source_refs = {_ref(source) for source in sources if isinstance(source, dict)}
    methods = card.get("delivery_methods") if isinstance(card.get("delivery_methods"), list) else []
    # DeliveryMethod.key is intentionally card-local. It is a stable label
    # used by the compiled plan, not an authorization principal. The
    # caller-owned destination is the security boundary: accept either the
    # exact configured destination URI or its configured opaque key because
    # adapters may persist one or the other while preserving the same route.
    authorized_destinations = {
        value
        for item in public["destinations"]
        for value in (str(item["key"]), str(item["destination"]))
    }
    route_keys = {str(method.get("key")) for method in methods if isinstance(method, dict)}
    route_destinations = {
        str(method.get("destination"))
        for method in methods
        if isinstance(method, dict) and method.get("destination")
    }
    route_outcomes = {
        str(method.get("outcome"))
        for method in methods
        if isinstance(method, dict) and method.get("outcome")
    }
    expected_outcomes = _expected_outcomes(scenario)
    guidance = " ".join(
        str(card.get(field) or "")
        for field in ("what_to_watch", "why_watch", "decision_guidance", "follow_up_guidance")
    )
    coverage = _coverage(policy, guidance)
    checks = {
        "approved": card.get("status") == "approved",
        "has_intent": bool(str(card.get("what_to_watch") or "").strip())
        and bool(str(card.get("why_watch") or "").strip()),
        "sources_authorized": bool(source_refs) and source_refs <= all_refs,
        "sources_avoid_catalog_noise": bool(source_refs) and source_refs <= canonical_refs,
        "routes_authorized": bool(route_destinations)
        and route_destinations <= authorized_destinations,
        "routes_cover_labeled_nonquiet_outcomes": expected_outcomes <= route_outcomes,
        "decision_guidance_present": bool(str(card.get("decision_guidance") or "").strip()),
        "materiality_anchor_hints_present": coverage["recall"] >= 0.80,
        "has_condition_or_explicit_policy": bool(card.get("numeric_conditions"))
        or bool(str(card.get("decision_guidance") or "").strip()),
    }
    return {
        "artifact_present": True,
        "artifact_kind": "approved_card",
        "card_id": card.get("id"),
        "status": card.get("status"),
        "source_refs": sorted(source_refs),
        "route_keys": sorted(route_keys),
        "route_destinations": sorted(route_destinations),
        "authorized_destinations": sorted(authorized_destinations),
        "route_outcomes": sorted(route_outcomes),
        "expected_nonquiet_outcomes": sorted(expected_outcomes),
        "retrieval_mode": card.get("retrieval_mode"),
        "investigation_mode": card.get("investigation_mode"),
        "policy_anchor_hints": coverage,
        "checks": checks,
        "mechanical_pass": all(checks.values()),
        "semantic_status": "unassessed",
        "limitations": [
            "Token/phrase anchors are diagnostics, not proof that the card means the owner's policy.",
            "The review does not establish causal explanations or human usefulness.",
        ],
    }


def _notes_quality(row: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    notes = str(row.get("notes") or "")
    public = scenario["public"]
    policy = str(public["owner_answers"].get("materiality", ""))
    route_tokens = [str(item["key"]) for item in public["destinations"]]
    coverage = _coverage(policy, notes)
    checks = {
        "notes_present": bool(notes.strip()),
        "owner_topics_complete": set(row.get("asked_owner_topics") or [])
        >= set(public["owner_topics"]),
        "route_keys_retained": bool(route_tokens) and all(token in notes for token in route_tokens),
        "materiality_anchor_hints_retained": coverage["recall"] >= 0.80,
    }
    return {
        "artifact_present": bool(notes.strip()),
        "artifact_kind": "persistent_notes",
        "policy_anchor_hints": coverage,
        "checks": checks,
        "mechanical_pass": all(checks.values()),
        "executable_artifact": False,
        "semantic_status": "unassessed",
        "limitations": [
            "Notes can preserve useful context but do not define a typed executable workflow.",
            "The baseline is not penalized for lacking SignalWeave's card artifact; this is the product distinction being measured.",
        ],
    }


def review_report(report_path: Path, *, require_current_source: bool = True) -> dict[str, Any]:
    report = json.loads(report_path.read_text())
    config = report["config"]
    recorded_source = config.get("source_fingerprint")
    current_source = source_fingerprint()
    source_match = isinstance(recorded_source, dict) and _same(recorded_source, current_source)
    fixtures = select_scenarios(
        build_scenarios(**_fixture_options(config)),
        config.get("selected_scenario_ids"),
        config.get("selected_companies", 0),
    )
    scenarios = {scenario["scenario_id"]: scenario for scenario in fixtures}
    rows = [row for row in report.get("rows", []) if row.get("phase") == "onboarding"]
    by_arm: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_arm.setdefault(str(row.get("arm")), []).append(row)
    findings: list[str] = []
    gates = {
        "source_fingerprint_present": isinstance(recorded_source, dict),
        "source_fingerprint_matches_current": source_match,
        "fixture_digest_matches": dataset_digest(fixtures) == config.get("dataset_digest"),
        "report_complete": report.get("status") == "complete",
        "paired_onboarding_denominators": len(by_arm.get("luna_bi", []))
        == len(by_arm.get("luna_signalweave_jev", []))
        == len(fixtures)
        and bool(fixtures),
        "usage_complete": all(
            row.get("usage", {}).get(provider, {}).get("unknown_usage_attempts", 0) == 0
            for row in rows
            for provider in ("openai", "jev")
        ),
        "foreign_tools_absent": all(not row.get("foreign_tools") for row in rows),
    }
    if require_current_source and not source_match:
        findings.append("onboarding artifact is historical-only because its source fingerprint is stale or missing")
    if not gates["fixture_digest_matches"]:
        findings.append("reconstructed onboarding fixture differs from the measured run")
    if not gates["paired_onboarding_denominators"]:
        findings.append("onboarding arms do not have one paired row per selected company")

    quality: dict[str, dict[str, Any]] = {}
    for arm, arm_rows in by_arm.items():
        company_results = []
        for row in sorted(arm_rows, key=lambda item: (str(item.get("scenario_id")), str(item.get("card_id")))):
            scenario = scenarios.get(row.get("scenario_id"))
            if scenario is None:
                company_results.append({"scenario_id": row.get("scenario_id"), "mechanical_pass": False, "reason": "unknown_scenario"})
                continue
            if arm == "luna_signalweave_jev":
                result = _card_quality(_load_card(report_path, row), scenario)
                result["setup_complete"] = row.get("status") == "complete"
                result["owner_topics_complete"] = set(row.get("asked_owner_topics") or []) >= set(scenario["public"]["owner_topics"])
                result["mechanical_pass"] = bool(result["mechanical_pass"] and result["setup_complete"] and result["owner_topics_complete"])
            else:
                result = _notes_quality(row, scenario)
                result["setup_complete"] = row.get("status") == "complete"
                result["mechanical_pass"] = bool(result["mechanical_pass"] and result["setup_complete"])
            result["scenario_id"] = scenario["scenario_id"]
            company_results.append(result)
        quality[arm] = {
            "companies": company_results,
            "mechanical_pass_count": sum(bool(item.get("mechanical_pass")) for item in company_results),
            "company_count": len(company_results),
            "mechanical_pass_rate": (
                sum(bool(item.get("mechanical_pass")) for item in company_results) / len(company_results)
                if company_results else None
            ),
            "semantic_status": "unassessed",
        }

    integrity_gates = dict(gates)
    if not require_current_source:
        integrity_gates.pop("source_fingerprint_matches_current", None)
    integrity_pass = all(integrity_gates.values())
    treatment = quality.get("luna_signalweave_jev", {})
    baseline = quality.get("luna_bi", {})
    treatment_executable = sum(
        bool(item.get("artifact_present") and item.get("artifact_kind") == "approved_card" and item.get("mechanical_pass"))
        for item in treatment.get("companies", [])
    )
    baseline_executable = sum(bool(item.get("executable_artifact")) for item in baseline.get("companies", []))
    return {
        "review_version": 1,
        "report": str(report_path),
        "source_review": {
            "require_current_source": require_current_source,
            "recorded": recorded_source,
            "current": current_source,
            "matches_current": source_match,
            "historical_only": not source_match,
        },
        "integrity_pass": integrity_pass,
        "gates": gates,
        "findings": findings,
        "quality": quality,
        "comparison": {
            "treatment_approved_executable_cards": treatment_executable,
            "baseline_approved_executable_cards": baseline_executable,
            "treatment_card_rate": treatment_executable / len(fixtures) if fixtures else None,
            "baseline_card_rate": baseline_executable / len(fixtures) if fixtures else None,
            "interpretation": (
                "The card artifact is the measured product distinction. This is a mechanical artifact and "
                "authorization result, not semantic proof or a human-usefulness score."
            ),
        },
        "interpretation": (
            "Onboarding protocol is internally consistent; semantic policy fidelity and human usability remain "
            "unassessed."
            if integrity_pass
            else "Do not use this onboarding artifact as current proof until the failed integrity gates are fixed."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--allow-historical",
        action="store_true",
        help="Inspect an older artifact while marking it historical-only.",
    )
    args = parser.parse_args()
    result = review_report(args.report, require_current_source=not args.allow_historical)
    write_exclusive(args.output, result)
    print(canonical(result))
    return 0 if result["integrity_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
