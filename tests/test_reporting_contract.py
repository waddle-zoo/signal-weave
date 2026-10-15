from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime

import pytest
from jsonschema import ValidationError, validate

from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter
from evaluations.bootstrap_scenarios import (
    _Submission,
    build_scenarios,
    public_episode,
    score_submission,
)
from evaluations.domain_context_onboarding_trial import RecurringEpisode


def _episode(scenario, period_id, *, reporting_contract=True, native=None):
    public = public_episode(scenario, period_id)
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    adapter.set_period(public["period"], datetime.fromisoformat(public["period"]["as_of"]))
    return RecurringEpisode(
        public, adapter, native, reporting_contract=reporting_contract
    )


async def _wire_schema(episode):
    tool = next(item for item in await episode.specs() if item["name"] == "submit_analysis")
    return json.loads(json.dumps(tool["parameters"]))


def _submission(episode, *, source_ref=None):
    fact = episode.public["numeric_vocabulary"][0]
    unit = episode.public["submission_contract"]["numeric_definitions"][fact]["unit"]
    source_ref = source_ref or next(
        f"{item['adapter']}|{item['resource']}" for item in episode.public["catalog"]
    )
    return {
        "outcome": "ignore",
        "recipients": [],
        "evidence_refs": [source_ref],
        "numeric_claims": [{
            "fact": fact,
            "value": 987654321,
            "unit": unit,
            "evidence_refs": [source_ref],
        }],
        "claims": [],
        "summary": "A bounded report for the current period.",
    }


class _EmptyNative:
    async def list_tools(self):
        return []


@pytest.fixture(scope="module")
def public_scenarios():
    return tuple(
        scenario
        for split in ("dev", "holdout")
        for scenario in build_scenarios(
            seed=20261001, split=split, connector_profile=True
        )
    )


def _assert_public_bindings(episode, schema):
    numeric = schema["$defs"]["_NumericClaim"]
    definitions = episode.public["submission_contract"]["numeric_definitions"]
    bindings = {
        branch["if"]["properties"]["fact"]["const"]:
        branch["then"]["properties"]["unit"]["const"]
        for branch in numeric["allOf"]
    }
    assert numeric["properties"]["fact"]["enum"] == list(definitions)
    assert bindings == {fact: item["unit"] for fact, item in definitions.items()}
    assert schema["properties"]["recipients"]["items"]["enum"] == [
        item["key"] for item in episode.public["destinations"]
    ]
    recipient_description = schema["properties"]["recipients"]["description"]
    assert "alert or review destinations only" in recipient_description and "routine report audience" in recipient_description
    assert "quantities may be source-cited in prose" in schema["properties"]["numeric_claims"]["description"]
    reference_fields = (
        schema["properties"]["evidence_refs"],
        numeric["properties"]["evidence_refs"],
        schema["$defs"]["_Claim"]["properties"]["evidence_refs"],
    )
    assert all(field["items"]["pattern"] == r"^[^|]+\|.+$" for field in reference_fields)
    assert all("workflow receipts in summary prose" in field["description"] for field in reference_fields)


def test_schema_is_period_invariant_and_shared_by_both_arms(public_scenarios):
    multiple_unit_contracts = 0
    for scenario in public_scenarios:
        definitions = scenario["public"]["submission_contract"]["numeric_definitions"]
        multiple_unit_contracts += len({item["unit"] for item in definitions.values()}) > 1
        schemas = []
        for period in scenario["public"]["periods"]:
            baseline = _episode(scenario, period["period_id"])
            treatment = _episode(scenario, period["period_id"], native=_EmptyNative())
            baseline_schema = baseline.submission_schema()
            assert treatment.submission_schema() == baseline_schema
            _assert_public_bindings(baseline, baseline_schema)
            schemas.append(baseline_schema)
        assert schemas[1:] == schemas[:-1]
    assert multiple_unit_contracts > 0


async def test_serialized_tool_schema_and_submit_call_accept_static_unit_independent_of_value():
    scenario = build_scenarios(seed=20261001, split="dev", connector_profile=True)[0]
    episode = _episode(scenario, scenario["public"]["periods"][0]["period_id"])
    schema = await _wire_schema(episode)
    submission = _submission(episode)
    _assert_public_bindings(episode, schema)

    validate(submission, schema)
    result = await episode.call("submit_analysis", submission)

    assert result == {"recorded": True, "delivery_enabled": False}
    assert episode.submission["numeric_claims"][0]["value"] == 987654321


async def test_empty_vocabulary_allows_cited_prose_but_rejects_numeric_claims():
    scenario = build_scenarios(seed=20261001, split="dev", connector_profile=True)[0]
    episode = _episode(scenario, scenario["public"]["periods"][0]["period_id"])
    submission = _submission(episode)
    typed_claim = deepcopy(submission["numeric_claims"][0])
    episode.public["numeric_vocabulary"] = []
    episode.public["submission_contract"]["numeric_definitions"] = {}
    submission["numeric_claims"] = []
    submission["summary"] = "Describe any source-supported auxiliary counts in this report prose."
    schema = await _wire_schema(episode)

    numeric = schema["$defs"]["_NumericClaim"]
    assert schema["properties"]["numeric_claims"]["maxItems"] == 0
    assert "enum" not in numeric["properties"]["fact"] and "allOf" not in numeric
    validate(submission, schema)
    assert (await episode.call("submit_analysis", submission))["recorded"]

    submission["numeric_claims"] = [typed_claim]
    with pytest.raises(ValidationError):
        validate(submission, schema)
    with pytest.raises(ValidationError):
        await episode.call("submit_analysis", submission)


async def test_ignore_allows_business_audience_in_prose_but_rejects_alert_route():
    scenario = build_scenarios(seed=20261001, split="dev", connector_profile=True)[0]
    episode = _episode(scenario, scenario["public"]["periods"][0]["period_id"])
    submission = _submission(episode)
    submission["numeric_claims"] = []
    submission["summary"] = "Prepared for the business owner; context is included in report prose."
    schema = await _wire_schema(episode)

    validate(submission, schema)
    assert (await episode.call("submit_analysis", submission))["recorded"]

    submission["recipients"] = [episode.public["destinations"][0]["key"]]
    with pytest.raises(ValidationError):
        validate(submission, schema)
    with pytest.raises(ValidationError):
        await episode.call("submit_analysis", submission)


@pytest.mark.parametrize("invalid", ["wrong_unit", "unknown_fact", "receipt_as_source"])
async def test_wire_schema_and_submit_call_reject_diagonal_metadata(invalid):
    scenario = build_scenarios(seed=20261001, split="dev", connector_profile=True)[0]
    episode = _episode(scenario, scenario["public"]["periods"][0]["period_id"])
    schema = await _wire_schema(episode)
    submission = _submission(episode)
    claim = submission["numeric_claims"][0]
    if invalid == "wrong_unit":
        claim["unit"] = "not-the-declared-unit"
    elif invalid == "unknown_fact":
        claim["fact"] = "invented.measurement"
    else:
        submission["evidence_refs"] = ["receipt://workflow/123"]

    with pytest.raises(ValidationError):
        validate(submission, schema)
    with pytest.raises(ValidationError):
        await episode.call("submit_analysis", submission)


async def test_well_formed_unread_source_is_admitted_then_rejected_by_scorer():
    scenario = build_scenarios(seed=20261001, split="dev", connector_profile=True)[0]
    period_id = scenario["public"]["periods"][0]["period_id"]
    episode = _episode(scenario, period_id)
    source = episode.public["catalog"][0]
    unread_ref = f"{source['adapter']}|{source['resource']}"
    submission = _submission(episode, source_ref=unread_ref)

    validate(submission, await _wire_schema(episode))
    await episode.call("submit_analysis", submission)
    score = score_submission(
        scenario, period_id, submission, inspected_refs=set(), asked_owner_topics=set()
    )

    assert score["valid_submission"]
    assert not score["provenance_complete"]
    assert any(item["uninspected_refs"] == [unread_ref]
               for item in score["citation_diagnostics"])


def test_legacy_schema_and_public_inputs_are_not_mutated():
    scenario = build_scenarios(seed=20261001, split="dev", connector_profile=True)[0]
    period_id = scenario["public"]["periods"][0]["period_id"]
    public = public_episode(scenario, period_id)
    original_public = deepcopy(public)
    original_model_schema = _Submission.model_json_schema()
    expected_legacy = deepcopy(original_model_schema)
    expected_legacy["properties"]["recipients"]["items"]["enum"] = [
        item["key"] for item in public["destinations"]
    ]
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    adapter.set_period(public["period"], datetime.fromisoformat(public["period"]["as_of"]))
    episode = RecurringEpisode(public, adapter, reporting_contract=False)
    opt_in = RecurringEpisode(public, adapter, reporting_contract=True)

    assert episode.submission_schema() == expected_legacy
    opt_in.submission_schema()
    assert public == original_public
    assert _Submission.model_json_schema() == original_model_schema


@pytest.mark.parametrize("malformation", ["missing_definition", "missing_unit"])
def test_opt_in_schema_rejects_missing_public_definitions_or_units(malformation):
    scenario = build_scenarios(seed=20261001, split="dev", connector_profile=True)[0]
    episode = _episode(scenario, scenario["public"]["periods"][0]["period_id"])
    definitions = episode.public["submission_contract"]["numeric_definitions"]
    fact = next(iter(definitions))
    if malformation == "missing_definition":
        del definitions[fact]
    else:
        del definitions[fact]["unit"]

    with pytest.raises(ValueError):
        episode.submission_schema()
