"""Regression guards for citation identity and explicit operator context."""

import copy
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluations import bootstrap_empirical_trial as trial
from tests.test_onboarding import make_server
from tests.test_onboarding_windows import dispatch


def resources():
    return [
        {"source_key": "primary", "adapter": "warehouse", "resource": "query:17",
         "evidence": [{"provenance": ["current-fact-1"]}]},
        {"source_key": "context", "adapter": "catalog", "resource": "record:8",
         "evidence": [{"provenance": ["current-fact-2"]}]},
    ]


def flat_intent(company):
    card = company["expert_card"]
    return {
        "title": card["title"],
        "what_to_watch": card["what_to_watch"],
        "why_watch": card["why_watch"],
        "decision_guidance": card["decision_guidance"],
        "source_keys": [source["key"] for source in company["sources"]],
        "routes": [
            {"destination_key": method["key"], "outcome": method["outcome"]}
            for method in card["delivery_methods"]
        ],
        "watch_for": card["watch_for"],
        "questions": card["questions"],
    }


def test_current_observed_identifiers_resolve_without_string_guessing():
    assert trial.canonical_evidence_refs(resources(), [
        "primary", "current-fact-1", "warehouse|query:17", "current-fact-2",
    ]) == ["warehouse|query:17", "catalog|record:8"]
    for invalid in ("previous-fact-1", "primary-suffix", "query:17", "other|query:17"):
        with pytest.raises(ValueError, match="unknown_or_ambiguous"):
            trial.canonical_evidence_refs(resources(), [invalid])


def test_ambiguous_alias_cannot_be_guessed():
    snapshots = resources()
    snapshots[1]["evidence"][0]["provenance"].append("current-fact-1")
    with pytest.raises(ValueError, match="unknown_or_ambiguous"):
        trial.canonical_evidence_refs(snapshots, ["current-fact-1"])


def test_retained_v1_citation_rejections_do_not_mean_wrong_business_decisions():
    root = Path(__file__).resolve().parents[1] / "docs/evidence/bootstrap-empirical-v1-01"
    manifest = json.loads((root / "manifest.json").read_text())
    report = json.loads((root / "report.json").read_text())
    events = [json.loads(line) for line in gzip.decompress(
        (root / "events.jsonl.gz").read_bytes(),
    ).decode().splitlines()]
    assert sum(row["exact_count"] for row in report["recomputed_score"]["companies"].values()) == 5
    checked = rejected = 0
    for company in manifest["companies"]:
        for case in company["holdout_cases"]:
            episode = f"{company['id']}:baseline:{case['id']}"
            attempts = [event for event in events if event["kind"] == "tool.result"
                        and event["episode"] == episode and event["name"] == "submit_analysis"]
            assert len(attempts) == 1
            attempt = attempts[0]
            submitted = attempt["arguments"]
            refs = trial.canonical_evidence_refs(case["resources"], submitted["evidence_refs"])
            required = {f"{source['adapter']}|{source['resource']}"
                        for source in company["sources"]
                        if source["key"] in case["required_evidence_source_keys"]}
            assert submitted["outcome"] == case["expected_outcome"]
            assert set(submitted["recipients"]) == set(case["expected_delivery_method_keys"])
            assert required <= set(refs)
            rejected += attempt["result"].get("message") == "uninspected_evidence_ref"
            checked += 1
    assert (checked, rejected) == (12, 7)


@pytest.mark.parametrize("field,value", [
    ("action_confidence_threshold", 1.0), ("action_confidence_threshold", 0.69),
    ("investigation_mode", "bounded"), ("retrieval_mode", "expand"),
])
def test_operator_profile_is_visible_and_not_authored_by_model(field, value):
    company = trial.build_companies()[0]
    public = trial.public_company(company)
    assert public["execution_profile"] == trial.FIXED_SNAPSHOT_PROFILE
    public["execution_profile"]["action_confidence_threshold"] = 1.0
    assert trial.FIXED_SNAPSHOT_PROFILE["action_confidence_threshold"] == 0.70
    card = copy.deepcopy(company["expert_card"])
    card[field] = value
    with pytest.raises(ValueError, match="profile|confidence"):
        trial._candidate(card, company)


def test_flat_bridge_preserves_approved_provenance_and_omits_runtime_fields():
    company = trial.build_companies()[0]
    from examples.investigation_agent.onboarding import draft_arguments

    kwargs = draft_arguments(flat_intent(company), company["sources"], company["destinations"])
    assert kwargs["sources"] == company["sources"]
    assert kwargs["sources"][0]["parameters"] == company["sources"][0]["parameters"]
    assert kwargs["delivery_methods"][0]["destination"] == company["destinations"][0]["destination"]
    assert not {"id", "compiled_plan", "status", "retrieval_mode", "investigation_mode"} & set(kwargs)
    json.dumps(kwargs)


@pytest.mark.asyncio
async def test_flat_bridge_dispatches_through_existing_native_draft_tool(tmp_path):
    from examples.investigation_agent.onboarding import draft_arguments

    approved_sources = [{
        "key": "metric",
        "adapter": "superset",
        "resource": "dashboard:7",
        "label": "Metric",
        "parameters": {"metadata": {"code": "native-dispatch"}},
        "required": True,
    }]
    approved_destinations = [{
        "key": "owner",
        "label": "Owner",
        "destination": "agent://owner",
    }]
    intent = {
        "title": "Native dispatch check",
        "what_to_watch": "Checkout conversion.",
        "why_watch": "Decide whether the owner should respond.",
        "decision_guidance": "Investigate a material decline.",
        "source_keys": ["metric"],
        "routes": [{"destination_key": "owner", "outcome": "investigate"}],
    }
    kwargs = draft_arguments(intent, approved_sources, approved_destinations)
    server = make_server(tmp_path)
    response = await dispatch(server, "draft_insight_card", json.loads(json.dumps(kwargs)))

    assert response["card"]["title"] == intent["title"]
    assert response["card"]["sources"] == kwargs["sources"]
    assert response["card"]["delivery_methods"][0]["destination"] == kwargs["delivery_methods"][0]["destination"]
    assert response["card"]["retrieval_mode"] == "fixed"
    assert response["card"]["investigation_mode"] == "none"
    assert response["card"]["action_confidence_threshold"] == 0.70
    assert response["card"]["status"] == "draft"
    # This is an offline MCP serialization/compile-double check, not semantic proof.


async def test_authoring_regression_cannot_dispatch_baseline_or_control(monkeypatch, tmp_path):
    authors = []
    budgets = []

    async def failed_author(company, **kwargs):
        authors.append(company["id"])
        kwargs["audit"].emit("api.request", provider="openai", request_id=-len(authors))
        return {"status": "failed", "accepted_card": None}

    async def forbidden(*args, **kwargs):
        raise AssertionError("No baseline/control or failed-card monitoring may run")

    def fake_jev(key, budget, audit):
        budgets.append(budget.limit)
        return SimpleNamespace()

    monkeypatch.setattr(trial, "author_company", failed_author)
    monkeypatch.setattr(trial, "run_native_holdout", forbidden)
    monkeypatch.setattr(trial, "run_raw_holdout", forbidden)
    monkeypatch.setattr(trial, "load_api_key", lambda path: "offline-only")
    monkeypatch.setattr(trial, "TrialJev", fake_jev)
    report = await trial.run_trial(
        tmp_path / "regression", live=True, jev_key_file="unused",
        authoring_regression=True,
    )
    manifest = json.loads((tmp_path / "regression" / "manifest.json").read_text())
    assert len(authors) == 3 and budgets == [40, 40]
    assert manifest["max_jev_attempts"] == 40
    assert report["recomputed_score"]["status"] == "not_run"
    assert report["paid_calls_made"]  # Audited attempted episodes, not a false zero.
    assert report["freeze_verified"]
    for row in report["execution_comparison"].values():
        assert not row["paired_with_authored_card"]
        assert row["expert_native_jev"] is row["treatment_native_jev"] is None
        assert row["raw_luna"] == []
