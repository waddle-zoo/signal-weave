"""Projection tests for owner review of card-wide source dependencies."""

import pytest

from evaluations import bootstrap_owner_review as reviewer
from evaluations.bootstrap_agent_trial import canonical


def _inputs():
    return {
        "public": {
            "brief": "Use commerce sales as the decision basis; support is context only.",
            "glossary": {},
            "destinations": [{"key": "owner", "label": "Business owner",
                              "destination": "slack://owner"}],
            "submission_contract": {
                "numeric_definitions": {
                    "collections.baseline": {
                        "definition": (
                            "Canonical collections require all expected bank partitions closed "
                            "and the bank watermark at the reporting cutoff. Without independent "
                            "historical closure attestation, partial or stale data cannot validate "
                            "even the baseline. A printed amount alone is not a canonical total."
                        ),
                        "unit": "USD",
                    },
                },
                "private_label": "PRIVATE_SUBMISSION_LABEL",
                "future_periods": [{"expected_outcome": "PRIVATE_FUTURE_OUTCOME"}],
            },
            "private_label": "PRIVATE_EXPECTED_NOTIFY",
        },
        "owner_answers": {
            "source_scope": "Commerce sales is needed for every decision; support is corroborating context.",
        },
        "artifact": {
            "notes": "Review the sales close under the owner's policy.",
            "private_label": "PRIVATE_CARD_LABEL",
            "card": {
                "decision_guidance": "Apply the owner's sales policy.",
                "sources": [
                    {"key": "sales", "adapter": "company_mcp", "resource": "sales",
                     "required": True, "required_comparison_keys": []},
                    {"key": "support", "adapter": "company_mcp", "resource": "support",
                     "required": False, "required_comparison_keys": []},
                ],
                "private_label": "PRIVATE_CARD_DECISION",
            },
        },
        "source_context": {
            "catalog": [
                {"adapter": "company_mcp", "resource": "sales", "title": "Sales",
                 "description": "Monthly sales totals.",
                 "contract": {"roles": ["primary"]}},
                {"adapter": "company_mcp", "resource": "support", "title": "Support",
                 "description": "Support context.",
                 "contract": {"roles": ["diagnostic", "corroborates"]}},
            ],
            "inspected_sources": [],
        },
    }


def _scalar_comparison(**updates):
    return {
        "key": "sales-monthly",
        "metric": "net_sales",
        "definition": "Settled commerce sales, excluding refunds.",
        "population": "Commerce transactions",
        "unit": "USD",
        "comparison_window": "previous_28_days",
        "coverage": "complete",
        "comparable": True,
        "detail": "All eligible days and regions are represented.",
        "query_refs": ["query:sales-monthly"],
        **updates,
    }


def test_review_payload_projects_required_flags_roles_and_no_private_labels():
    inputs = _inputs()
    payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], inputs["artifact"], inputs["source_context"]
    )

    bindings = {binding["key"]: binding
                for binding in payload["execution_contract"]["source_bindings"]}
    assert bindings["sales"]["required"] is True
    assert bindings["support"]["required"] is False
    assert payload["source_context"]["catalog"][0]["contract"]["roles"] == ["primary"]
    assert payload["source_context"]["catalog"][1]["contract"]["roles"] == [
        "diagnostic", "corroborates",
    ]
    projected = canonical(payload)
    assert "PRIVATE_EXPECTED_NOTIFY" not in projected
    assert "PRIVATE_CARD_LABEL" not in projected
    assert "PRIVATE_CARD_DECISION" not in projected
    assert "PRIVATE_SUBMISSION_LABEL" not in projected
    assert "PRIVATE_FUTURE_OUTCOME" not in projected


def test_public_measurement_definition_reaches_review_separate_from_owner_policy():
    inputs = _inputs()
    payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], inputs["artifact"], inputs["source_context"]
    )

    definition = inputs["public"]["submission_contract"]["numeric_definitions"][
        "collections.baseline"
    ]
    assert payload["measurement_definitions"]["definitions"] == {
        "collections.baseline": definition,
    }
    assert "numeric_definitions" not in payload["owner_policy"]
    assert payload["measurement_definitions"]["purpose"] == (
        "Authoritative public measurement meaning and validity only; not observed results "
        "or business action policy."
    )
    instructions = reviewer.REVIEW_INSTRUCTIONS
    assert "Compare the artifact only with" not in instructions
    assert "measurement_definitions only for declared metric meaning, units" in instructions
    assert "owner thresholds and boundaries against the metric's declared meaning and unit" in instructions
    assert "do not reject it merely because it is not repeated in owner_policy" in instructions
    assert "those must come from owner_policy" in instructions
    assert "not what action to take" in instructions
    assert "request actual owner clarification instead of silently choosing" in instructions
    assert "request clarification instead of inventing a branch" in instructions


def test_missing_public_measurement_definitions_are_optional():
    assert reviewer.project_measurement_definitions({}) == {}
    assert reviewer.project_measurement_definitions({"submission_contract": {}}) == {}
    assert reviewer.project_measurement_definitions({
        "submission_contract": {"numeric_definitions": None},
    }) == {}


@pytest.mark.parametrize(
    "invalid",
    [
        [],
        "not-an-object",
        {"metric": None},
        {"metric": {}},
        {"metric": {"unit": "USD"}},
        {"metric": {"definition": ""}},
        {"metric": {"definition": "   "}},
        {"metric": {"definition": 7}},
        {"metric": {"definition": "valid", "unit": ""}},
        {"metric": {"definition": "valid", "unit": 7}},
        {"metric": {"definition": "valid", "private_label": "hidden"}},
        {"metric": {"definition": "x" * (reviewer.MAX_CONTEXT_TEXT + 1)}},
        {" " * 3: {"definition": "valid"}},
        {"m" * 201: {"definition": "valid"}},
        {1: {"definition": "valid"}},
        {f"metric-{index}": {"definition": "valid"}
         for index in range(reviewer.MAX_NUMERIC_DEFINITIONS + 1)},
    ],
)
def test_public_measurement_definition_projection_rejects_malformed_or_unbounded_entries(invalid):
    with pytest.raises(ValueError):
        reviewer.project_measurement_definitions({
            "submission_contract": {"numeric_definitions": invalid},
        })


def test_measurement_definition_projection_allows_definition_without_optional_unit():
    assert reviewer.project_measurement_definitions({
        "submission_contract": {
            "numeric_definitions": {"metric.current": {"definition": "Current value."}},
        },
    }) == {"metric.current": {"definition": "Current value."}}


def test_required_source_default_stays_true_and_baseline_notes_need_no_card_bindings():
    inputs = _inputs()
    source = inputs["artifact"]["card"]["sources"][0]
    source.pop("required")
    card_payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], inputs["artifact"], inputs["source_context"]
    )
    assert card_payload["execution_contract"]["source_bindings"][0]["required"] is True

    baseline_payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], {"notes": "Baseline owner-policy notes."},
        inputs["source_context"],
    )
    assert baseline_payload["execution_contract"]["source_bindings"] == []
    assert baseline_payload["execution_contract"]["numeric_bindings"] == []


@pytest.mark.parametrize("invalid", [None, 0, 1, "true"])
def test_source_required_flag_must_be_boolean(invalid):
    inputs = _inputs()
    inputs["artifact"]["card"]["sources"][0]["required"] = invalid
    with pytest.raises(ValueError, match="required must be boolean"):
        reviewer.review_payload(
            inputs["public"], inputs["owner_answers"], inputs["artifact"], inputs["source_context"]
        )


def test_reviewer_explains_global_source_gate_without_role_or_all_required_heuristics():
    instructions = reviewer.REVIEW_INSTRUCTIONS
    assert "global prerequisite for every" in instructions
    assert "forces insufficient_data" in instructions
    assert "Assess each required flag against the original owner brief, glossary and owner_answers" in instructions
    assert "but do not make every source optional" in instructions
    assert "Do not infer requiredness from source roles" in instructions
    assert "have no source bindings or required flags to demand" in instructions
    assert "A quality binding on required=false is advisory" in instructions
    assert "do not accept it as satisfying an owner-wide requirement" in instructions


def test_preapproval_review_checks_scope_intent_without_demanding_approval_field():
    inputs = _inputs()
    inputs["owner_answers"]["source_scope"] = (
        "Sales is the metric population; Support is separate corroborating context."
    )
    inputs["source_context"]["catalog"][0]["contract"]["scope"] = "Generated monthly sales ledger."
    inputs["source_context"]["catalog"][1]["contract"]["scope"] = "Separate support backlog."
    payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], inputs["artifact"], inputs["source_context"]
    )

    instructions = reviewer.REVIEW_INSTRUCTIONS
    assert "This review runs before the installed approve_insight_card call" in instructions
    assert "Do not reject solely because source_scope_confirmations is not yet on the draft or in notes" in instructions
    assert "selected source scopes against the original owner brief and owner_answers" in instructions
    assert "Leave exact-map validation to the installed approval call" in instructions
    assert "source_scope_confirmations" not in payload["artifact"]
    assert payload["source_context"]["catalog"][0]["contract"]["scope"] == "Generated monthly sales ledger."
    assert payload["source_context"]["catalog"][1]["contract"]["scope"] == "Separate support backlog."
    assert payload["owner_policy"]["owner_answers"] == inputs["owner_answers"]


@pytest.mark.parametrize(
    ("domain", "window", "coverage", "comparable"),
    [
        ("commerce", "previous_28_days", "complete", True),
        ("observability", "rolling_7_days", "partial", False),
        ("fulfillment", "previous_fiscal_quarter", "unknown", False),
    ],
)
def test_projection_preserves_typed_scalar_comparison_contracts(
    domain, window, coverage, comparable,
):
    inputs = _inputs()
    inputs["source_context"]["catalog"][0]["contract"].update({
        "domain": domain,
        "comparison_contracts": [
            _scalar_comparison(
                comparison_window=window, coverage=coverage, comparable=comparable,
            ),
        ],
        "untrusted_metadata": {"private_label": "PRIVATE_CONTRACT_LABEL"},
    })

    payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], inputs["artifact"], inputs["source_context"]
    )
    contract = payload["source_context"]["catalog"][0]["contract"]

    assert contract["domain"] == domain
    assert contract["comparison_contracts"] == [
        _scalar_comparison(
            comparison_window=window, coverage=coverage, comparable=comparable,
        ),
    ]
    assert "untrusted_metadata" not in contract


def test_missing_scalar_comparison_flags_remain_unknown_not_inferred():
    inputs = _inputs()
    source_contract = inputs["source_context"]["catalog"][0]["contract"]
    assert "comparison_contracts" not in reviewer.project_source_context(
        inputs["source_context"]
    )["catalog"][0]["contract"]
    scalar = _scalar_comparison()
    scalar.pop("coverage")
    scalar.pop("comparable")
    source_contract["comparison_contracts"] = [scalar]

    projected = reviewer.project_source_context(inputs["source_context"])
    contract = projected["catalog"][0]["contract"]["comparison_contracts"][0]

    assert contract["coverage"] == "unknown"
    assert contract["comparable"] is False


def test_scalar_coverage_binding_does_not_require_analytical_comparison_or_numeric_condition():
    inputs = _inputs()
    comparison_key = "sales-monthly"
    inputs["artifact"]["card"]["decision_guidance"] = (
        "Require a complete, comparable primary sales measurement for this policy."
    )
    inputs["artifact"]["card"]["sources"][0]["required_comparison_keys"] = [comparison_key]
    inputs["source_context"] = {
        "catalog": [],
        "inspected_sources": [{
            "ref": "company_mcp|sales",
            "adapter": "company_mcp",
            "resource": "sales",
            "title": "Sales",
            "contract": {
                "domain": "commerce",
                "comparison_contracts": [_scalar_comparison(key=comparison_key)],
            },
            "analytical_comparisons": [],
        }],
    }

    payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], inputs["artifact"], inputs["source_context"]
    )

    binding = payload["execution_contract"]["source_bindings"][0]
    inspected = payload["source_context"]["inspected_sources"][0]
    assert binding["required_comparison_keys"] == [comparison_key]
    assert inspected["contract"]["comparison_contracts"][0]["key"] == comparison_key
    assert inspected["analytical_comparisons"] == []
    assert payload["execution_contract"]["numeric_bindings"] == []
    assert "does not require numeric_conditions or decomposition" in reviewer.REVIEW_INSTRUCTIONS


@pytest.mark.parametrize("count, succeeds", [(100, True), (101, False)])
def test_scalar_comparison_contract_list_has_a_100_item_bound(count, succeeds):
    inputs = _inputs()
    inputs["source_context"]["catalog"][0]["contract"]["comparison_contracts"] = [
        _scalar_comparison(key=f"comparison-{index}") for index in range(count)
    ]

    if succeeds:
        projected = reviewer.project_source_context(inputs["source_context"])
        assert len(projected["catalog"][0]["contract"]["comparison_contracts"]) == 100
    else:
        with pytest.raises(ValueError, match="bounded list"):
            reviewer.project_source_context(inputs["source_context"])


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        {},
        {**_scalar_comparison(), "key": ""},
        {**_scalar_comparison(), "coverage": "all"},
        {**_scalar_comparison(), "query_refs": [""]},
    ],
)
def test_malformed_scalar_comparison_contracts_are_rejected(invalid):
    inputs = _inputs()
    inputs["source_context"]["catalog"][0]["contract"]["comparison_contracts"] = [invalid]

    with pytest.raises(ValueError):
        reviewer.project_source_context(inputs["source_context"])


@pytest.mark.parametrize("invalid", [None, {}, "not-a-list"])
def test_malformed_comparison_contract_container_is_rejected(invalid):
    inputs = _inputs()
    inputs["source_context"]["catalog"][0]["contract"]["comparison_contracts"] = invalid

    with pytest.raises(ValueError, match="bounded list"):
        reviewer.project_source_context(inputs["source_context"])


def test_scalar_contract_projection_drops_future_labels_and_raw_source_data():
    inputs = _inputs()
    contract = inputs["source_context"]["catalog"][0]["contract"]
    contract["comparison_contracts"] = [{
        **_scalar_comparison(),
        "private_label": "PRIVATE_FUTURE_NOTIFY",
        "future_rows": [{"value": "RAW_FUTURE_VALUE_9001"}],
        "segments": [{"segment": "RAW_SEGMENT_NAME"}],
    }]
    contract["private_label"] = "PRIVATE_SOURCE_LABEL"
    inputs["source_context"].update({
        "private_label": "PRIVATE_CONTEXT_LABEL",
        "future_snapshots": [{"expected_outcome": "PRIVATE_FUTURE_QUIET"}],
        "raw_observations": [{"value": "RAW_OBSERVATION_9002"}],
    })

    payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], inputs["artifact"], inputs["source_context"]
    )
    serialized = canonical(payload)

    for forbidden in (
        "PRIVATE_FUTURE_NOTIFY", "PRIVATE_SOURCE_LABEL", "PRIVATE_CONTEXT_LABEL",
        "PRIVATE_FUTURE_QUIET", "RAW_FUTURE_VALUE_9001", "RAW_SEGMENT_NAME",
        "RAW_OBSERVATION_9002", "future_snapshots", "raw_observations",
    ):
        assert forbidden not in serialized


def test_review_instructions_separate_relative_window_intent_from_example_dates():
    inputs = _inputs()
    inputs["source_context"]["catalog"][0]["contract"]["comparison_contracts"] = [
        _scalar_comparison(comparison_window="previous_28_days"),
    ]
    inputs["source_context"]["current_period"] = {
        "period_id": "onboarding-example",
        "as_of": "2026-08-31T00:00:00Z",
    }

    payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], inputs["artifact"], inputs["source_context"]
    )

    assert payload["source_context"]["catalog"][0]["contract"]["comparison_contracts"][0][
        "comparison_window"
    ] == "previous_28_days"
    assert payload["source_context"]["current_period"]["as_of"] == "2026-08-31T00:00:00Z"
    assert "onboarding example measurements and dates are not permanent date restrictions" in (
        reviewer.REVIEW_INSTRUCTIONS
    )
    assert "preserve a fixed date constraint only if the owner requested it" in (
        reviewer.REVIEW_INSTRUCTIONS
    )
