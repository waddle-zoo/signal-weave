from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from evaluations import native_cadence_trial as trial
from evaluations.bootstrap_agent_trial import Audit
from evaluations.bootstrap_scenarios import public_scenario


def cadence_scenario():
    periods = []
    labels = {}
    year, month = 2025, 1
    classes = ["quiet", "ordinary", "ordinary", "investigate", "ordinary", "ordinary",
               "notify", "ordinary", "ordinary", "missing", "ordinary", "ordinary"]
    for index, category in enumerate(classes):
        as_of = datetime(year, month, 28).isoformat() + "+00:00"
        period_id = f"month-{index + 1:02d}"
        periods.append({"period_id": period_id, "as_of": as_of, "snapshots": {}})
        labels[period_id] = {
            "class": category,
            "recipients": ([] if category == "quiet" else
                           ["analytics"] if category == "investigate" else
                           ["leadership"] if category == "notify" else
                           ["data-trust"] if category == "missing" else []),
        }
        month += 1
        if month == 13:
            year, month = year + 1, 1
    scenario = {
        "scenario_id": "hypatia-test",
        "public": {
            "company": {"name": "Hypatia"}, "brief": "Monitor approved monthly business signals.",
            "glossary": {}, "owner_topics": ["policy"], "owner_answers": {"policy": "Use the approved card."},
            "destinations": [
                {"key": "analytics", "label": "Analytics", "destination": "slack://mock-analytics"},
                {"key": "leadership", "label": "Leadership", "destination": "slack://mock-leadership"},
                {"key": "data-trust", "label": "Data trust", "destination": "slack://mock-data-trust"},
            ],
            "catalog": [], "onboarding": {"period_id": "onboarding", "as_of": "2024-12-28T00:00:00+00:00", "snapshots": {}},
            "periods": periods, "numeric_vocabulary": [],
            "submission_contract": {"outcomes": ["ignore", "investigate", "notify", "insufficient_data"]},
        },
        "private": {"periods": labels},
    }
    return scenario, {"pilot_indices": [0, 3, 6, 9]}


def test_load_cadence_fixture_imports_real_package_module():
    scenario, registration = trial.load_cadence_fixture()
    assert len(scenario["public"]["periods"]) == 12
    assert registration["pilot_indices"] == [0, 3, 6, 9]


def test_registration_selects_private_labeled_stage_gate_periods_not_first_four():
    scenario, registration = cadence_scenario()
    selected = trial.select_periods(scenario, registration, cases=4)
    assert [row["index"] for row in selected] == [0, 3, 6, 9]
    assert [row["label"]["class"] for row in selected] == [
        "quiet", "investigate", "notify", "missing",
    ]
    assert [row["period"]["period_id"] for row in selected] == [
        "month-01", "month-04", "month-07", "month-10",
    ]


@pytest.mark.parametrize("registration", [{}, {"pilot_indices": [0, 1, 2]},
                                            {"pilot_indices": [0, 1, 1, 3]},
                                            {"pilot_indices": [0, 1, 2, 12]}])
def test_invalid_stage_gate_registration_is_rejected(registration):
    scenario, _ = cadence_scenario()
    with pytest.raises(ValueError):
        trial.select_periods(scenario, registration, cases=4)


def test_full_run_selection_requires_explicit_twelve_case_request():
    scenario, registration = cadence_scenario()
    selected = trial.select_periods(scenario, registration, cases=12)
    assert [row["index"] for row in selected] == list(range(12))


def test_outbox_is_local_and_quiet_has_zero_messages():
    scenario, _ = cadence_scenario()
    destinations = scenario["public"]["destinations"]
    quiet, messages = trial.make_outbox_submission(
        {"outcome": "ignore", "recipients": [], "summary": "", "evidence_refs": []},
        destinations=destinations,
        allowed_outcomes=scenario["public"]["submission_contract"]["outcomes"],
        inspected_refs=set(), period_id="month-01", arm="treatment",
    )
    assert quiet["outcome"] == "ignore"
    assert messages == []


def test_actionable_outbox_resolves_one_message_per_canonical_recipient():
    scenario, _ = cadence_scenario()
    submission, messages = trial.make_outbox_submission(
        {"outcome": "investigate", "recipients": ["analytics", "leadership"],
         "summary": "Month 4 for the approved sales scope declined; compare the channel drivers next.",
         "evidence_refs": ["company_mcp|monthly-sales"]},
        destinations=scenario["public"]["destinations"],
        allowed_outcomes=scenario["public"]["submission_contract"]["outcomes"],
        inspected_refs={"company_mcp|monthly-sales"}, period_id="month-04", arm="baseline",
    )
    assert submission["recipients"] == ["analytics", "leadership"]
    assert len(messages) == 2
    assert {item["destination"] for item in messages} == {
        "slack://mock-analytics", "slack://mock-leadership",
    }
    assert all(item["owner"] == "caller_owned_agent" for item in messages)
    assert all(item["sink"] == "local_mock_outbox" for item in messages)
    assert all(item["external_send_attempted"] is False for item in messages)


@pytest.mark.parametrize("mutation", [
    {"recipients": ["unknown"]},
    {"evidence_refs": ["company_mcp|not-inspected"]},
    {"summary": "word " * 121},
    {"evidence_refs": []},
])
def test_actionable_outbox_rejects_unresolved_or_unsupported_payload(mutation):
    scenario, _ = cadence_scenario()
    arguments = {"outcome": "notify", "recipients": ["leadership"],
                 "summary": "Month 7 needs review.", "evidence_refs": ["company_mcp|sales"]}
    arguments.update(mutation)
    with pytest.raises(ValueError):
        trial.make_outbox_submission(
            arguments, destinations=scenario["public"]["destinations"],
            allowed_outcomes=scenario["public"]["submission_contract"]["outcomes"],
            inspected_refs={"company_mcp|sales"}, period_id="month-07", arm="treatment",
        )


def test_outbox_accepts_only_current_receipt_key_and_rejects_previous_period_receipts():
    scenario, _ = cadence_scenario()
    current = "hypatia-test/month-04"
    args = {"outcome": "investigate", "recipients": ["analytics"],
            "summary": "Month 4 merits review.", "evidence_refs": [f"receipt:{current}"]}
    kwargs = {"destinations": scenario["public"]["destinations"],
              "allowed_outcomes": scenario["public"]["submission_contract"]["outcomes"],
              "period_id": "month-04", "arm": "treatment"}
    submission, messages = trial.make_outbox_submission(
        args, inspected_refs={f"receipt:{current}"}, **kwargs,
    )
    assert submission["evidence_refs"] == [f"receipt:{current}"]
    assert len(messages) == 1
    args["evidence_refs"] = ["receipt:hypatia-test/month-01"]
    with pytest.raises(ValueError, match="current-run receipt"):
        trial.make_outbox_submission(
            args, inspected_refs={f"receipt:{current}"}, **kwargs,
        )


def test_outbox_normalizes_valid_current_receipt_and_card_source_aliases():
    scenario, _ = cadence_scenario()
    current = "hypatia-test/month-04"
    canonical_refs = {f"receipt:{current}", "company_mcp|monthly-sales"}
    args = {"outcome": "investigate", "recipients": ["analytics"],
            "summary": "The archived close merits a channel review.",
            "evidence_refs": ["receipt-actual-04", "approved-sales"]}
    submission, messages = trial.make_outbox_submission(
        args, destinations=scenario["public"]["destinations"],
        allowed_outcomes=scenario["public"]["submission_contract"]["outcomes"],
        inspected_refs=canonical_refs,
        evidence_aliases={"receipt-actual-04": f"receipt:{current}",
                          "approved-sales": "company_mcp|monthly-sales"},
        period_id="month-04", arm="treatment",
    )
    assert submission["evidence_refs"] == [
        f"receipt:{current}", "company_mcp|monthly-sales"]
    assert messages[0]["evidence_refs"] == submission["evidence_refs"]

    with pytest.raises(ValueError, match="successful current-run receipt"):
        trial.make_outbox_submission(
            {**args, "evidence_refs": ["receipt-old"]},
            destinations=scenario["public"]["destinations"],
            allowed_outcomes=scenario["public"]["submission_contract"]["outcomes"],
            inspected_refs=canonical_refs,
            evidence_aliases={"receipt-actual-04": f"receipt:{current}"},
            period_id="month-04", arm="treatment",
        )


def test_quiet_cannot_route_and_duplicate_recipients_are_rejected():
    scenario, _ = cadence_scenario()
    base = {"outcome": "ignore", "recipients": ["leadership"],
            "summary": "", "evidence_refs": []}
    with pytest.raises(ValueError, match="quiet"):
        trial.make_outbox_submission(
            base, destinations=scenario["public"]["destinations"], allowed_outcomes=["ignore"],
            inspected_refs=set(), period_id="month-01", arm="treatment",
        )
    base.update(outcome="notify", recipients=["leadership", "leadership"])
    with pytest.raises(ValueError, match="unique"):
        trial.make_outbox_submission(
            base, destinations=scenario["public"]["destinations"], allowed_outcomes=["notify"],
            inspected_refs=set(), period_id="month-01", arm="treatment",
        )


class FakeServer:
    def __init__(self):
        names = ["search_catalog", "inspect_resource", "get_insight_card",
                 "evaluate_insight_card", "get_decision_receipt"]
        self.tools = [SimpleNamespace(name=name, description="shared description",
                                     inputSchema={"type": "object", "properties": {}})
                      for name in names]

    async def list_tools(self):
        return self.tools

    async def call_tool(self, *_args, **_kwargs):
        raise AssertionError("shared source tools must use the fixture SourceRegistry")


def _public_for_session(scenario):
    return {"scenario_id": scenario["scenario_id"], **scenario["public"]}


@pytest.mark.asyncio
async def test_both_arms_keep_source_tools_and_identical_finish_contract_without_forced_native_use():
    scenario, _ = cadence_scenario()
    public = _public_for_session(scenario)
    adapter = SimpleNamespace(name="company_mcp", audit=Audit(), inspected=set(), catalog=[],
                              period_context={"period_id": "month-01", "as_of": "2025-01-28T00:00:00+00:00"})
    server = FakeServer()
    treatment = trial.CadenceSession(
        public, adapter, server, True, arm="treatment", guidance_mode=trial.OPTIONAL_TOOL_MODE)
    baseline = trial.CadenceSession(
        public, adapter, server, False, arm="baseline", guidance_mode=trial.OPTIONAL_TOOL_MODE)
    treatment.phase = baseline.phase = "monitoring"
    t_specs, b_specs = await treatment.specs(), await baseline.specs()
    t_by_name, b_by_name = ({item["name"]: item for item in specs} for specs in (t_specs, b_specs))
    common_source_names = {"search_catalog", "inspect_resource"}
    assert common_source_names <= t_by_name.keys()
    assert common_source_names <= b_by_name.keys()
    assert t_by_name["search_catalog"] == b_by_name["search_catalog"]
    assert t_by_name["inspect_resource"] == b_by_name["inspect_resource"]
    assert set(trial.OPTIONAL_NATIVE_TOOLS) <= t_by_name.keys()
    assert not (set(trial.OPTIONAL_NATIVE_TOOLS) & b_by_name.keys())
    assert t_by_name["finish_run"] == b_by_name["finish_run"]
    assert "submit_analysis" not in t_by_name and "submit_analysis" not in b_by_name
    assert "numeric_claims" not in t_by_name["finish_run"]["parameters"]["properties"]
    assert "not required" in t_by_name["evaluate_insight_card"]["description"]
    assert "call evaluate_insight_card once" not in t_by_name["search_catalog"]["description"]
    assert trial.product_use_status("treatment", 0, 0) == "product_not_used"
    assert trial.product_use_status("treatment", 1, 0) == "native_attempt_failed"
    assert trial.product_use_status("treatment", 1, 1) == "native_current_result_available"
    assert trial.product_use_status("baseline", 1, 1) == "not_applicable"


@pytest.mark.asyncio
async def test_production_guided_mode_matches_actual_default_profile_and_keeps_receipt_paging(tmp_path):
    from signalweave.mcp_server import AGENT_PROFILE_TOOLS, create_mcp
    from tests.test_local_investigation import make_runtime

    scenario, _ = cadence_scenario()
    public = trial.public_scenario(scenario)
    adapter = trial.PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    runtime, _, _ = make_runtime(tmp_path)
    server = create_mcp(runtime)
    installed = {tool.name: tool for tool in await server.list_tools()}
    assert set(trial.PRODUCTION_NATIVE_TOOLS) <= AGENT_PROFILE_TOOLS <= installed.keys()

    treatment = trial.CadenceSession(public, adapter, server, True, arm="treatment")
    baseline = trial.CadenceSession(public, adapter, server, False, arm="baseline")
    treatment.phase = baseline.phase = "monitoring"
    treatment_specs, baseline_specs = await treatment.specs(), await baseline.specs()
    treatment_by_name = {spec["name"]: spec for spec in treatment_specs}
    baseline_by_name = {spec["name"]: spec for spec in baseline_specs}

    assert set(trial.PRODUCTION_NATIVE_TOOLS) <= treatment_by_name.keys()
    assert not (set(trial.PRODUCTION_NATIVE_TOOLS) & baseline_by_name.keys())
    for name in trial.PRODUCTION_NATIVE_TOOLS:
        assert treatment_by_name[name]["description"] == installed[name].description
        assert treatment_by_name[name]["parameters"] == installed[name].inputSchema
    for name in ("search_catalog", "inspect_resource"):
        assert treatment_by_name[name] == baseline_by_name[name]
        assert treatment_by_name[name]["description"] == installed[name].description
        assert treatment_by_name[name]["parameters"] == installed[name].inputSchema
    assert {"result_path", "offset", "limit"} <= (
        treatment_by_name["get_decision_receipt"]["parameters"]["properties"].keys())
    assert not ({"onboard_insight_card", "review_insight_card", "approve_insight_card"}
                & treatment_by_name.keys())
    assert treatment.native_results == []
    assert "at most 120 words" in trial.PRODUCTION_COMMON_INSTRUCTIONS
    assert trial._monitoring_instructions(baseline) == trial.PRODUCTION_COMMON_INSTRUCTIONS
    assert trial._monitoring_instructions(treatment).endswith(server.instructions)


@pytest.mark.asyncio
async def test_finish_run_normalizes_current_native_receipt_and_source_aliases_without_refetch():
    scenario, _ = cadence_scenario()
    public = _public_for_session(scenario)
    card, response = _card_and_native_response()
    expected_key = f"{public['scenario_id']}/month-01"
    response["receipt"].update(idempotency_key=expected_key, receipt_id="receipt-current-01")
    response["result"].update(source_keys=[], evidence=[], observations=[])
    response["resources"] = []
    receipt_page = {
        "status": "found", "receipt": response["receipt"],
        "result_page": {"path": ["evidence"], "kind": "list", "items": [
            {"source_key": "approved-sales", "values": {"current": 12}},
        ]},
    }
    adapter = SimpleNamespace(name="company_mcp", audit=Audit(), inspected=set(), catalog=[],
                              period_context={"period_id": "month-01"})
    session = trial.CadenceSession(public, adapter, FakeServer(), True, arm="treatment")
    session.phase = "monitoring"
    session.shared_card = card
    session.current_idempotency_key = expected_key
    session.native_results = [
        {"name": "evaluate_insight_card", "returned": True, "result": response},
        {"name": "get_decision_receipt", "arguments": {"receipt_id": "receipt-current-01"},
         "returned": True, "result": receipt_page},
    ]

    result = await session.call("finish_run", {
        "outcome": "investigate", "recipients": ["analytics"],
        "summary": "The archived close merits a channel review.",
        "evidence_refs": ["receipt-current-01", "approved-sales"],
    })

    expected_refs = [f"receipt:{expected_key}", "company_mcp|monthly-sales"]
    assert result["recorded"] is True
    assert session.submission["evidence_refs"] == expected_refs
    assert session.outbox[0]["evidence_refs"] == expected_refs
    assert session.agent_inspected == set()
    assert adapter.inspected == set()


@pytest.mark.asyncio
async def test_both_source_inspection_key_aliases_resolve_to_the_inspected_canonical_ref():
    scenario, _ = cadence_scenario()
    public = _public_for_session(scenario)
    adapter = SimpleNamespace(name="company_mcp", audit=Audit(), inspected=set(), catalog=[],
                              period_context={"period_id": "month-01"})

    class LocalRegistry:
        def __init__(self):
            self.calls = 0

        async def inspect(self, source, **_kwargs):
            self.calls += 1
            adapter.inspected.add(f"{source.adapter}|{source.resource}")
            return SimpleNamespace(model_dump=lambda mode: {"source_key": source.key, "error": None})

    registry = LocalRegistry()
    session = trial.CadenceSession(
        public, adapter, FakeServer(), False, arm="baseline", registry=registry)
    session.phase = "monitoring"
    canonical_ref = "company_mcp|monthly-sales"
    await session.call("inspect_resource", {"adapter": "company_mcp", "resource": "monthly-sales"})
    resource_key_alias = next(key for key, ref in session.evidence_aliases.items()
                              if ref == canonical_ref and key.startswith("inspect-"))
    await session.call("inspect_source", {"ref": canonical_ref})

    for alias in (resource_key_alias, "monthly-sales"):
        session.submission = None
        session.outbox = []
        await session.call("finish_run", {
            "outcome": "investigate", "recipients": ["analytics"],
            "summary": "The inspected archive merits a channel review.",
            "evidence_refs": [alias],
        })
        assert session.submission["evidence_refs"] == [canonical_ref]
    assert registry.calls == 2


@pytest.mark.asyncio
async def test_current_inspected_snapshot_and_nested_evidence_urls_are_citable():
    scenario, _ = cadence_scenario()
    public = _public_for_session(scenario)
    adapter = SimpleNamespace(name="company_mcp", audit=Audit(), inspected=set(), catalog=[],
                              period_context={"period_id": "month-01"})

    class URLRegistry:
        async def inspect(self, source, **_kwargs):
            ref = f"{source.adapter}|{source.resource}"
            adapter.inspected.add(ref)
            return SimpleNamespace(model_dump=lambda mode: {
                "source_key": source.key,
                "source_url": f"simulation-ledger://{source.resource}/snapshot",
                "error": None,
                "evidence": [{"source_key": source.key,
                              "source_url": f"simulation-ledger://{source.resource}/evidence"}],
            })

    session = trial.CadenceSession(
        public, adapter, FakeServer(), False, arm="baseline", registry=URLRegistry())
    session.phase = "monitoring"
    await session.call("inspect_resource", {"adapter": "company_mcp", "resource": "monthly-sales"})
    await session.call("inspect_source", {"ref": "company_mcp|monthly-sales"})

    aliases = [
        "simulation-ledger://monthly-sales/snapshot",
        "simulation-ledger://monthly-sales/evidence",
    ]
    await session.call("finish_run", {
        "outcome": "investigate", "recipients": ["analytics"],
        "summary": "The inspected monthly sales source merits review.",
        "evidence_refs": aliases,
    })
    assert session.submission["evidence_refs"] == ["company_mcp|monthly-sales"]
    assert session.outbox[0]["evidence_refs"] == ["company_mcp|monthly-sales"]

    with pytest.raises(ValueError, match="inspected or a successful current-run receipt"):
        await session.call("finish_run", {
            "outcome": "investigate", "recipients": ["analytics"],
            "summary": "An unsupported citation must still fail.",
            "evidence_refs": [*aliases, "company_mcp|not-inspected"],
        })


@pytest.mark.asyncio
async def test_ambiguous_current_source_url_is_not_a_valid_citation():
    scenario, _ = cadence_scenario()
    public = _public_for_session(scenario)
    adapter = SimpleNamespace(name="company_mcp", audit=Audit(), inspected=set(), catalog=[],
                              period_context={"period_id": "month-01"})
    shared_url = "simulation-ledger://shared/current"

    class AmbiguousURLRegistry:
        async def inspect(self, source, **_kwargs):
            adapter.inspected.add(f"{source.adapter}|{source.resource}")
            return SimpleNamespace(model_dump=lambda mode: {
                "source_key": source.key, "source_url": shared_url, "error": None,
            })

    session = trial.CadenceSession(
        public, adapter, FakeServer(), False, arm="baseline", registry=AmbiguousURLRegistry())
    session.phase = "monitoring"
    for resource in ("monthly-sales", "support-backlog"):
        await session.call("inspect_resource", {"adapter": "company_mcp", "resource": resource})

    assert session.source_url_refs[shared_url] == {
        "company_mcp|monthly-sales", "company_mcp|support-backlog",
    }
    with pytest.raises(ValueError, match="inspected or a successful current-run receipt"):
        await session.call("finish_run", {
            "outcome": "investigate", "recipients": ["analytics"],
            "summary": "The ambiguous source needs review.", "evidence_refs": [shared_url],
        })


@pytest.mark.asyncio
async def test_both_arms_route_shared_catalog_and_inspection_to_same_local_fixture_registry():
    scenario, _ = cadence_scenario()
    public = _public_for_session(scenario)
    adapter = SimpleNamespace(name="company_mcp", audit=Audit(), inspected=set(), catalog=[],
                              period_context={"period_id": "month-01"})
    server = FakeServer()

    class LocalRegistry:
        def __init__(self):
            self.calls = []

        async def search_resources(self, query, **kwargs):
            self.calls.append(("search", query, kwargs))
            return SimpleNamespace(model_dump=lambda mode: {
                "resources": [], "total_count": 0, "has_more": False,
                "provider": "fixture", "strategy": "fixture",
            })

        async def inspect(self, source, **kwargs):
            self.calls.append(("inspect", source, kwargs))
            return SimpleNamespace(model_dump=lambda mode: {
                "adapter": source.adapter, "resource": source.resource,
                "source_key": source.key, "error": None,
            })

    registries = []
    for arm, treatment in (("baseline", False), ("treatment", True)):
        session = trial.CadenceSession(public, adapter, server, treatment, arm=arm)
        session.phase = "monitoring"
        session.registry = LocalRegistry()
        registries.append(session.registry)
        assert await session.call("search_catalog", {"query": "sales", "limit": 5}) == {
            "resources": [], "total_count": 0, "has_more": False,
            "provider": "fixture", "strategy": "fixture",
        }
        inspected = await session.call("inspect_resource", {
            "adapter": "company_mcp", "resource": "monthly-sales",
        })
        assert inspected["resource"] == "monthly-sales"
        assert session.agent_inspected == {"company_mcp|monthly-sales"}
    assert [call[0] for call in registries[0].calls] == ["search", "inspect"]
    assert [call[0] for call in registries[1].calls] == ["search", "inspect"]
    assert all(call[2]["authorized_tenants"] == ["hypatia-test"]
               for registry in registries for call in registry.calls)


@pytest.mark.parametrize(("arm", "treatment"), [("baseline", False), ("treatment", True)])
@pytest.mark.asyncio
async def test_failed_primary_read_is_citable_for_data_trust_but_not_quiet_proof(arm, treatment):
    scenario, _ = cadence_scenario()
    public = _public_for_session(scenario)
    adapter = SimpleNamespace(name="company_mcp", audit=Audit(), inspected=set(),
                              successful_inspected_refs=set(), catalog=_card_catalog(),
                              period_context={"period_id": "month-01"})

    class FailedReadRegistry:
        async def inspect(self, source, **kwargs):
            adapter.inspected.add(f"{source.adapter}|{source.resource}")
            return SimpleNamespace(model_dump=lambda mode: {
                "adapter": source.adapter, "resource": source.resource,
                "source_key": source.key, "error": {"code": "unavailable"},
            })

    session = trial.CadenceSession(public, adapter, FakeServer(), treatment, arm=arm)
    session.phase = "monitoring"
    session.registry = FailedReadRegistry()
    session.shared_card = _card_and_native_response()[0]
    session.current_idempotency_key = "hypatia-test/month-01"
    inspected = await session.call("inspect_resource", {
        "adapter": "company_mcp", "resource": "monthly-sales",
    })
    assert inspected["error"] == {"code": "unavailable"}

    evidence_mode, proof_refs = trial._evidence_proof(
        session, expected_key=session.current_idempotency_key)
    assert (evidence_mode, proof_refs) == ("none", [])
    quiet_score = trial._expected_score(
        {"outcome": "ignore", "recipients": [], "summary": "", "evidence_refs": []},
        {"class": "quiet", "recipients": []}, [],
        evidence_mode=evidence_mode, proof_refs=proof_refs,
    )
    assert quiet_score["quiet_grade_eligible"] is False
    assert quiet_score["outcome_correct"] is None

    recorded = await session.call("finish_run", {
        "outcome": "insufficient_data", "recipients": ["data-trust"],
        "summary": "The monthly sales source is unavailable for this archived close.",
        "evidence_refs": ["company_mcp|monthly-sales"],
    })
    assert recorded["recorded"] is True
    assert session.outbox[0]["recipient_key"] == "data-trust"
    assert session.outbox[0]["evidence_refs"] == ["company_mcp|monthly-sales"]


def test_prompt_contains_no_private_labels_or_precomputed_bundle():
    scenario, registration = cadence_scenario()
    selected = trial.select_periods(scenario, registration, cases=4)[0]
    public = _public_for_session(scenario)
    adapter = SimpleNamespace(name="company_mcp", audit=Audit(), inspected=set(), catalog=[],
                              period_context={"period_id": selected["period"]["period_id"],
                                              "as_of": selected["period"]["as_of"]})
    session = trial.CadenceSession(public, adapter, FakeServer(), True, arm="treatment")
    session.phase = "monitoring"
    prompt = trial._episode_prompt(session, selected["period"])
    assert "signalweave_evaluation" not in prompt
    assert "periods" not in prompt["business"]
    assert "class" not in prompt and "quiet" not in str(prompt)
    assert prompt["evaluation_idempotency_key"] == "hypatia-test/month-01"
    assert "simulation_as_of" in trial.COMMON_INSTRUCTIONS
    assert "archived monthly-close replay" in trial.COMMON_INSTRUCTIONS


@pytest.mark.asyncio
async def test_real_fixture_session_schemas_and_prompts_exclude_future_period_payloads():
    scenario, _ = trial.load_cadence_fixture()
    full_public = public_scenario(scenario)
    assert full_public["numeric_vocabulary"] == []
    current_period = full_public["periods"][0]
    onboarding_period = full_public["onboarding"]
    future_period = full_public["periods"][1]
    raw_markers = {
        future_period["period_id"],
        json.dumps(next(iter(future_period["snapshots"].values()))["observations"][0], sort_keys=True),
        json.dumps(next(iter(current_period["snapshots"].values()))["observations"][0], sort_keys=True),
        json.dumps(next(iter(onboarding_period["snapshots"].values()))["observations"][0], sort_keys=True),
    }
    private_markers = {label["category"] for label in scenario["private"]["periods"].values()}

    for phase in ("onboarding", "monitoring"):
        period = onboarding_period if phase == "onboarding" else current_period
        for treatment in (False, True):
            adapter = trial.TimedSourceAdapter(full_public["catalog"], full_public["scenario_id"], Audit())
            adapter.set_period(period, datetime.now(timezone.utc))
            session = trial.CadenceSession(
                full_public, adapter, FakeServer(), treatment,
                arm="treatment" if treatment else "baseline",
            )
            session.phase = phase
            session.current_idempotency_key = f"{full_public['scenario_id']}/{period['period_id']}"
            specs = await session.specs()
            assert isinstance(specs, list)
            assert session.owner["owner_answers"] == full_public["owner_answers"]
            assert "owner_answers" not in session.public
            assert "periods" not in session.public and "onboarding" not in session.public
            public_context = json.dumps(session.public, sort_keys=True)
            assert not any(marker in public_context for marker in raw_markers)
            assert not any(marker in public_context for marker in private_markers)
            if phase == "onboarding":
                prompt = {"phase": phase, "business": session.public,
                          "period": adapter.period_context}
            else:
                prompt = trial._episode_prompt(session, period)
            serialized = json.dumps(prompt, sort_keys=True)
            assert not any(marker in serialized for marker in raw_markers)
            assert not any(marker in serialized for marker in private_markers)
            assert "periods" not in prompt["business"]
            assert "onboarding" not in prompt["business"]


@pytest.mark.asyncio
async def test_dry_run_records_registration_selected_stage_gate_without_private_labels(tmp_path, monkeypatch):
    scenario, registration = cadence_scenario()
    monkeypatch.setattr(trial, "verify_binary", lambda _: {"source_sha256": "722"})
    monkeypatch.setattr(trial, "_git_sha", lambda: "a" * 40)
    monkeypatch.setattr(trial, "_file_hash", lambda _: "b" * 64)
    report = await trial.run_trial(
        scenario, registration, binary=tmp_path / "signalweave", key_file=None,
        output=tmp_path / "trial", cases=4, live=False,
    )
    assert report["status"] == "dry_run"
    assert report["protocol"]["selected_indices"] == [0, 3, 6, 9]
    assert report["protocol"]["selected_period_ids"] == ["month-01", "month-04", "month-07", "month-10"]
    assert "retrospective monthly-close review" in report["protocol"]["study_scope"]
    assert "No real scheduler" in report["protocol"]["scheduler_claim"]
    assert report["protocol"]["tool_limits_per_episode"] == {
        "max_tool_calls": 100, "timeout_seconds": trial.RECURRING_TIMEOUT_SECONDS,
    }
    assert report["protocol"]["onboarding_episode_limits"] == {
        "max_tool_calls": 100, "timeout_seconds": trial.ONBOARDING_TIMEOUT_SECONDS,
    }
    assert report["protocol"]["replay_clock"]["freshness_claim"].startswith("Gateway replay receipt")
    assert "local typed SourceRegistry" in report["protocol"]["shared_source_transport"]
    assert "transport responses only" in (
        report["protocol"]["native_measurement_semantics"]["jev_successes"])
    assert "not judgment correctness" in (
        report["protocol"]["native_measurement_semantics"]["native_valid_current_results"])
    guidance = report["protocol"]["treatment_guidance"]
    assert guidance["mode"] == trial.PRODUCTION_GUIDED_MODE
    assert "initialize.instructions verbatim" in guidance["treatment_instructions"]
    assert "passed unchanged" in guidance["tool_definition_strategy"]
    assert guidance["mutation_tools_exposed"] == []
    assert guidance["excluded_default_profile_tools"] == [
        "onboard_insight_card", "review_insight_card", "approve_insight_card"]
    assert "120 words" in trial.PRODUCTION_COMMON_INSTRUCTIONS
    assert report["protocol"]["narrative_review_protocol"] == {
        "max_tool_calls": 2,
        "schema_correction_retries": 1,
        "required_fields": ["message_id", "verdict", "rationale"],
        "issues_optional_default": [],
        "missing_verdict_or_rationale_is_failure": True,
        "positive_verdict_forced": False,
    }
    assert "quiet" not in (tmp_path / "trial" / "report.json").read_text()


@pytest.mark.asyncio
async def test_live_path_passes_separate_onboarding_and_recurring_timeout_budgets(tmp_path, monkeypatch):
    scenario, registration = cadence_scenario()
    key_file = tmp_path / "jev.key"
    key_file.write_text("offline-test-key", encoding="utf-8")
    card = {"id": "approved-card", "version": 1, "status": "approved",
            "sources": [], "delivery_methods": []}

    class LocalServer(FakeServer):
        instructions = ""

        async def call_tool(self, name, _arguments):
            assert name == "get_insight_card"
            return [], card

    server = LocalServer()

    class ServerContext:
        async def __aenter__(self):
            return server

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(trial, "verify_binary", lambda _: {"source_sha256": "722"})
    monkeypatch.setattr(trial, "_git_sha", lambda: "a" * 40)
    monkeypatch.setattr(trial, "_file_hash", lambda _: "b" * 64)

    async def fake_assert_profile(_server):
        return []

    monkeypatch.setattr(trial, "assert_default_agent_profile", fake_assert_profile)
    monkeypatch.setattr(trial, "installed_server", lambda **_kwargs: ServerContext())
    episode_calls = []
    onboarding_prompt = []

    async def fake_codex_episode(session, **kwargs):
        episode_calls.append((session.phase, session.arm, kwargs["max_tool_calls"],
                              kwargs["timeout_seconds"]))
        if session.phase == "onboarding":
            onboarding_prompt.append(kwargs["instructions_override"])
            session.setup_complete = True
            session.card_id = card["id"]
            session.notes = "Use the owner's approved policy."
            session.owner_topics.add("policy")
            session.data_signoff = {"status": "ready"}
            return {"status": "complete", "exit_code": 0, "foreign_tools": [],
                    "error": None, "tool_calls": 0}
        if session.arm == "baseline":
            session.submission = {"outcome": "ignore", "recipients": [],
                                  "summary": "", "evidence_refs": []}
            return {"status": "complete", "exit_code": 0, "foreign_tools": [],
                    "error": None, "tool_calls": 0}
        raise RuntimeError("stop after capturing the treatment episode timeout")

    monkeypatch.setattr(trial, "codex_episode", fake_codex_episode)
    report = await trial.run_trial(
        scenario, registration, binary=tmp_path / "signalweave", key_file=key_file,
        output=tmp_path / "live-timeout-capture", cases=4, live=True,
    )

    assert report["onboarding_complete"] is True
    owner_channel_instruction = (
        "For this simulation, the human owner is available through ask_owner; use it for missing "
        "business answers. An ordinary chat question receives no simulated reply. Do not infer "
        "policy from reviewer output."
    )
    assert len(onboarding_prompt) == 1
    assert owner_channel_instruction in onboarding_prompt[0]
    assert "call ask_owner for every" not in onboarding_prompt[0].lower()
    assert episode_calls == [
        ("onboarding", "treatment", 100, 900),
        ("monitoring", "baseline", 100, 360),
        ("monitoring", "treatment", 100, 360),
    ]


@pytest.mark.asyncio
async def test_narrative_review_instructions_require_one_structured_tool_handoff(monkeypatch):
    message = {"period_id": "month-01", "recipient_key": "leadership",
               "summary": "Archived January sales were below the comparison period.",
               "evidence_refs": ["company_mcp|sales"]}
    evidence = {"month-01": {"as_of": "2025-01-28T00:00:00+00:00",
                              "sources": {"company_mcp|sales": {"status": "ok"}}}}
    captured = {}

    async def fake_episode(session, **kwargs):
        captured.update(kwargs)
        specs = await session.specs()
        assert [spec["name"] for spec in specs] == ["review_messages"]
        review_schema = specs[0]["parameters"]["properties"]["reviews"]["items"]
        assert review_schema["required"] == ["message_id", "verdict", "rationale"]
        rows = [{"message_id": "M01", "verdict": "needs_attention",
                 "rationale": "The text does not name the baseline period."}]
        await session.call("review_messages", {"reviews": rows})
        return {"status": "complete", "final_message": "Structured review submitted."}

    monkeypatch.setattr(trial, "codex_episode", fake_episode)
    result = await trial._review_messages(
        [message], public={"brief": "Review monthly sales."}, card={}, notes="",
        evidence_by_period=evidence, audit=Audit(), budget=trial.RequestBudget(0))

    instructions = captured["instructions_override"]
    assert "Submit exactly one structured row" in instructions
    assert "at most one schema-correction retry" in instructions
    assert "supported, needs_attention, or cannot_assess" in instructions
    assert "do not force a positive verdict" in instructions.lower()
    assert captured["max_tool_calls"] == 2
    assert result["status"] == "completed"
    assert result["reviews"][0]["verdict"] == "needs_attention"
    assert result["reviews"][0]["issues"] == []


@pytest.mark.asyncio
async def test_narrative_review_allows_one_schema_retry_without_changing_verdict(monkeypatch):
    message = {"period_id": "month-01", "recipient_key": "leadership",
               "summary": "Archived January sales were below the comparison period.",
               "evidence_refs": ["company_mcp|sales"]}
    evidence = {"month-01": {"as_of": "2025-01-28T00:00:00+00:00",
                              "sources": {"company_mcp|sales": {"status": "ok"}}}}
    attempts = []
    captured = {}

    async def fake_episode(session, **kwargs):
        captured.update(kwargs)
        first = {"message_id": "M01", "verdict": "needs_attention"}
        attempts.append(first)
        with pytest.raises(ValueError, match="rationale"):
            await session.call("review_messages", {"reviews": [first]})
        corrected = {**first, "rationale": "The message omits the baseline period."}
        attempts.append(corrected)
        await session.call("review_messages", {"reviews": [corrected]})
        return {"status": "complete", "final_message": "Structured review submitted."}

    monkeypatch.setattr(trial, "codex_episode", fake_episode)
    result = await trial._review_messages(
        [message], public={"brief": "Review monthly sales."}, card={}, notes="",
        evidence_by_period=evidence, audit=Audit(), budget=trial.RequestBudget(0))

    assert captured["max_tool_calls"] == 2
    assert len(attempts) == 2
    assert attempts[0]["verdict"] == attempts[1]["verdict"] == "needs_attention"
    assert result["status"] == "completed"
    assert result["reviews"][0]["issues"] == []


@pytest.mark.parametrize("row", [
    {"message_id": "M01", "rationale": "There is a reason."},
    {"message_id": "M01", "verdict": "supported"},
])
@pytest.mark.asyncio
async def test_narrative_review_rejects_missing_verdict_or_rationale(row):
    session = trial._MessageReviewSession(["M01"])
    with pytest.raises(ValueError):
        await session.call("review_messages", {"reviews": [row]})
    assert session.submission is None


@pytest.mark.asyncio
async def test_narrative_prose_without_structured_review_is_not_counted_as_review(monkeypatch):
    message = {"period_id": "month-01", "recipient_key": "leadership",
               "summary": "Archived January sales were below the comparison period.",
               "evidence_refs": ["company_mcp|sales"]}
    evidence = {"month-01": {"as_of": "2025-01-28T00:00:00+00:00",
                              "sources": {"company_mcp|sales": {"status": "ok"}}}}

    async def prose_only(_session, **_kwargs):
        return {"status": "complete", "final_message": "Looks good."}

    monkeypatch.setattr(trial, "codex_episode", prose_only)
    result = await trial._review_messages(
        [message], public={"brief": "Review monthly sales."}, card={}, notes="",
        evidence_by_period=evidence, audit=Audit(), budget=trial.RequestBudget(0))

    assert result["status"] == "no_structured_submission"
    assert result["reviews"] == []
    assert result["episode"]["final_message"] == "Looks good."


@pytest.mark.asyncio
async def test_narrative_schema_rejection_preserves_raw_failure_without_quality_pass(monkeypatch):
    message = {"period_id": "month-01", "recipient_key": "leadership",
               "summary": "Archived January sales were below the comparison period.",
               "evidence_refs": ["company_mcp|sales"]}
    evidence = {"month-01": {"as_of": "2025-01-28T00:00:00+00:00",
                              "sources": {"company_mcp|sales": {"status": "ok"}}}}
    raw_episode = {
        "status": "failed", "error": "no_structured_submission",
        "final_message": "The single review submission was rejected because one row omitted issues. I did not retry.",
        "tool_calls": 1,
    }

    async def rejected_submission(_session, **_kwargs):
        return raw_episode

    monkeypatch.setattr(trial, "codex_episode", rejected_submission)
    result = await trial._review_messages(
        [message], public={"brief": "Review monthly sales."}, card={}, notes="",
        evidence_by_period=evidence, audit=Audit(), budget=trial.RequestBudget(0))

    assert result["status"] == "not_completed"
    assert result["reviews"] == []
    assert result["episode"] == raw_episode


def test_private_label_scoring_keeps_missing_and_quiet_mapping_explicit():
    expected = trial.expected_result({"class": "missing", "recipients": ["data-trust"]})
    assert expected == ("insufficient_data", ["data-trust"], "missing")
    score = trial._expected_score(
        {"outcome": "ignore", "recipients": [], "summary": "", "evidence_refs": []},
        {"class": "quiet", "recipients": []}, [],
    )
    assert score["outcome_correct"] is None
    assert score["routing_correct"] is None
    assert score["outbox_count_correct"] is None
    assert score["quiet_grade_eligible"] is False
    assert score["expected_outbox_count"] == score["actual_outbox_count"] == 0
    supported = trial._expected_score(
        {"outcome": "ignore", "recipients": [], "summary": "", "evidence_refs": []},
        {"class": "quiet", "recipients": []}, [],
        evidence_mode="primary_source_inspected_current_run",
        proof_refs=["company_mcp|monthly-sales"],
    )
    assert supported["outcome_correct"] is True
    assert supported["quiet_grade_eligible"] is True
    assert supported["primary_current_proof"] is True
    partial = trial._expected_score(
        {"outcome": "ignore", "recipients": [], "summary": "", "evidence_refs": []},
        {"class": "quiet", "recipients": []}, [],
        evidence_mode="none", proof_refs=["company_mcp|one-of-two-primary-sources"],
    )
    assert partial["outcome_correct"] is None
    assert partial["primary_current_proof"] is False


def _card_and_native_response(idempotency_key="hypatia-test/month-01"):
    card = {"id": "card-1", "version": 3, "sources": [
        {"key": "approved-sales", "adapter": "company_mcp", "resource": "monthly-sales",
         "required": True},
        {"key": "optional-quality", "adapter": "company_mcp", "resource": "quality",
         "required": False},
    ]}
    response = {
        "receipt": {"receipt_id": f"receipt-{idempotency_key.rsplit('/', 1)[-1]}",
                    "idempotency_key": idempotency_key, "card_id": "card-1",
                    "card_version": 3, "status": "delivery_disabled",
                    "delivery_mode": "shadow", "delivery_enabled": False},
        "result": {"card_id": "card-1", "outcome": "ignore",
                   "source_keys": ["approved-sales"],
                   "evidence": [{"source_key": "approved-sales"}], "observations": []},
        "resources": [{"source_key": "approved-sales", "error": None}],
    }
    return card, response


def _card_catalog():
    return [
        {"adapter": "company_mcp", "resource": "monthly-sales",
         "contract": {"roles": ["primary"]}},
        {"adapter": "company_mcp", "resource": "quality",
         "contract": {"roles": ["corroborates"]}},
    ]


def test_quiet_evidence_proof_maps_card_alias_and_rejects_stale_receipt_or_wrong_card():
    card, response = _card_and_native_response()
    key = "hypatia-test/month-01"
    refs = trial._card_primary_refs(card, _card_catalog())
    assert refs == {"approved-sales": "company_mcp|monthly-sales"}
    assert trial._native_primary_refs(response, card, key, refs) == {"company_mcp|monthly-sales"}
    assert trial._native_primary_refs(response, card, "hypatia-test/month-04", refs) == set()
    wrong_version = {**response, "receipt": {**response["receipt"], "card_version": 2}}
    assert trial._native_primary_refs(wrong_version, card, key, refs) == set()
    failed_source = {**response, "resources": [{"source_key": "approved-sales", "error": "unavailable"}],
                     "result": {**response["result"], "evidence": [], "observations": []}}
    assert trial._native_primary_refs(failed_source, card, key, refs) == set()


def test_evidence_mode_requires_successful_current_primary_source_or_native_bundle():
    card, response = _card_and_native_response()
    key = "hypatia-test/month-01"
    session = SimpleNamespace(
        shared_card=card,
        adapter=SimpleNamespace(successful_inspected_refs=set(), catalog=_card_catalog()),
        native_results=[{"returned": True, "result": response}],
    )
    assert trial._evidence_proof(session, expected_key=key) == (
        "native_bundle_current_run", ["company_mcp|monthly-sales"])
    session.native_results = [{"returned": True,
                               "result": _card_and_native_response("hypatia-test/month-04")[1]}]
    assert trial._evidence_proof(session, expected_key=key) == ("none", [])
    session.native_results = []
    session.adapter.successful_inspected_refs = {"company_mcp|monthly-sales"}
    assert trial._evidence_proof(session, expected_key=key) == (
        "primary_source_inspected_current_run", ["company_mcp|monthly-sales"])


def test_quiet_proof_needs_only_publicly_declared_primary_not_required_context_sources():
    scenario, _ = trial.load_cadence_fixture()
    catalog = scenario["public"]["catalog"]
    card = {"sources": [
        {"key": f"card-source-{index}", "adapter": item["adapter"],
         "resource": item["resource"], "required": True}
        for index, item in enumerate(catalog)
    ]}
    expected_primary = {
        f"{item['adapter']}|{item['resource']}"
        for item in catalog if "primary" in item["contract"]["roles"]
    }
    refs = trial._card_primary_refs(card, catalog)
    assert set(refs.values()) == expected_primary
    assert len(expected_primary) == 1

    adapter = SimpleNamespace(
        catalog=catalog, successful_inspected_refs=set(expected_primary),
    )
    session = SimpleNamespace(shared_card=card, adapter=adapter, native_results=[])
    evidence_mode, proof_refs = trial._evidence_proof(session, expected_key="northstar/month-01")
    assert evidence_mode == "primary_source_inspected_current_run"
    assert set(proof_refs) == expected_primary
    quiet_score = trial._expected_score(
        {"outcome": "ignore", "recipients": [], "summary": "", "evidence_refs": []},
        {"class": "quiet", "recipients": []}, [],
        evidence_mode=evidence_mode, proof_refs=proof_refs,
    )
    assert quiet_score["quiet_grade_eligible"] is True


def test_native_usage_classifies_success_not_just_provider_attempt_and_exposes_receipt_ref():
    card, response = _card_and_native_response()
    key = "hypatia-test/month-01"
    session = SimpleNamespace(native_results=[{"returned": True, "result": response}])
    assert trial._native_success_count(session, card, key) == 1
    assert trial._current_receipt_refs(session, card, key) == {f"receipt:{key}"}
    stale = _card_and_native_response("hypatia-test/month-04")[1]
    session.native_results = [{"returned": True, "result": stale}]
    assert trial._native_success_count(session, card, key) == 0
    assert trial._current_receipt_refs(session, card, key) == set()


def test_native_receipt_and_source_aliases_require_current_receipt_card_binding():
    card, response = _card_and_native_response()
    key = "hypatia-test/month-01"
    session = SimpleNamespace(native_results=[{"returned": True, "result": response}])
    assert trial._current_native_evidence_aliases(session, card, key) == {
        response["receipt"]["receipt_id"]: f"receipt:{key}",
        "approved-sales": "company_mcp|monthly-sales",
    }

    stale = _card_and_native_response("hypatia-test/month-04")[1]
    session.native_results = [{"returned": True, "result": stale}]
    assert trial._current_native_evidence_aliases(session, card, key) == {}
    wrong_version = {**response, "receipt": {**response["receipt"], "card_version": 2}}
    session.native_results = [{"returned": True, "result": wrong_version}]
    assert trial._current_native_evidence_aliases(session, card, key) == {}
    wrong_card = {**response, "receipt": {**response["receipt"], "card_id": "other-card"}}
    session.native_results = [{"returned": True, "result": wrong_card}]
    assert trial._current_native_evidence_aliases(session, card, key) == {}


def test_paged_receipt_aliases_use_actual_receipt_id_and_only_card_bound_source_keys():
    card, response = _card_and_native_response()
    key = "hypatia-test/month-01"
    receipt_id = response["receipt"]["receipt_id"]
    page_response = {
        "status": "found",
        "receipt": response["receipt"],
        "result_page": {
            "path": ["evidence"], "kind": "list", "items": [
                {"source_key": "approved-sales",
                 "source_url": "simulation-ledger://sales/current", "values": {"current": 12}},
                {"source_key": "not-on-the-frozen-card",
                 "source_url": "simulation-ledger://foreign/current", "values": {"current": 99}},
            ],
        },
    }
    call = {"name": "get_decision_receipt", "arguments": {"receipt_id": receipt_id},
            "returned": True, "result": page_response}
    session = SimpleNamespace(native_results=[call])

    assert trial._current_native_evidence_aliases(session, card, key) == {
        receipt_id: f"receipt:{key}",
        "approved-sales": "company_mcp|monthly-sales",
        "simulation-ledger://sales/current": "company_mcp|monthly-sales",
    }

    invalid_calls = [
        {**call, "result": {**page_response, "receipt": {
            **page_response["receipt"], "idempotency_key": "hypatia-test/month-04"}}},
        {**call, "result": {**page_response, "receipt": {
            **page_response["receipt"], "card_version": 2}}},
        {**call, "result": {**page_response, "receipt": {
            **page_response["receipt"], "card_id": "other-card"}}},
        {**call, "arguments": {"receipt_id": "receipt-from-another-window"}},
        {**call, "result": {**page_response, "status": "missing"}},
    ]
    for invalid in invalid_calls:
        session.native_results = [invalid]
        assert trial._current_native_evidence_aliases(session, card, key) == {}


def test_current_native_result_maps_nested_evidence_urls_only_for_card_sources():
    card, response = _card_and_native_response()
    key = "hypatia-test/month-01"
    response["result"]["evidence"] = [
        {"source_key": "approved-sales", "source_url": "simulation-ledger://sales/evidence"},
        {"source_key": "foreign-key", "source_url": "simulation-ledger://foreign/evidence"},
    ]
    session = SimpleNamespace(native_results=[{"name": "evaluate_insight_card", "returned": True,
                                               "result": response}])

    assert trial._current_native_evidence_aliases(session, card, key) == {
        response["receipt"]["receipt_id"]: f"receipt:{key}",
        "approved-sales": "company_mcp|monthly-sales",
        "simulation-ledger://sales/evidence": "company_mcp|monthly-sales",
    }

    stale = {**response, "receipt": {**response["receipt"],
                                      "idempotency_key": "hypatia-test/month-04"}}
    session.native_results = [{"name": "evaluate_insight_card", "returned": True, "result": stale}]
    assert trial._current_native_evidence_aliases(session, card, key) == {}


def test_native_transport_result_and_policy_judgment_are_scored_separately():
    scenario, _ = cadence_scenario()
    card, response = _card_and_native_response()
    key = "hypatia-test/month-07"
    response["receipt"]["idempotency_key"] = key
    response["result"].update(outcome="insufficient_data", delivery_methods=[])
    calls = [
        {"name": "evaluate_insight_card", "returned": True, "result": response},
        {"name": "get_decision_receipt", "returned": True, "result": response},
        {"name": "get_decision_receipt", "returned": True, "result": response},
    ]
    judgment = trial._native_judgment_score(
        calls, card, scenario["private"]["periods"]["month-07"],
        scenario["public"]["destinations"], key)
    assert trial._native_success_count(SimpleNamespace(native_results=calls), card, key) == 3
    assert trial.product_use_status("treatment", len(calls), 3) == "native_current_result_available"
    assert judgment == {
        "observed": True, "receipt_count": 1,
        "actual_outcome": "insufficient_data", "expected_outcome": "notify",
        "outcome_correct": False, "actual_recipients": [],
        "expected_recipients": ["leadership"], "routing_correct": False,
    }
    recovered = trial._expected_score(
        {"outcome": "notify", "recipients": ["leadership"], "summary": "Review the current close.",
         "evidence_refs": ["company_mcp|monthly-sales"]},
        scenario["private"]["periods"]["month-07"],
        [{"recipient_key": "leadership"}],
    )
    assert recovered["outcome_correct"] is True
    assert recovered["routing_correct"] is True


def test_replay_capture_stamps_only_gateway_times_and_preserves_measurement_dates_and_cutoffs():
    scenario, _ = cadence_scenario()
    period = {"period_id": "month-01", "as_of": "2025-01-31T00:00:00+00:00",
              "snapshots": {"company_mcp|monthly-sales": {
                  "captured_at": "2025-02-01T00:00:00+00:00",
                  "source_captured_at": "2025-01-31T00:00:00+00:00",
                  "metadata": {"measurement_month": "2025-01",
                               "cutoff_at": "2025-01-31T00:00:00+00:00",
                               "freshness_asserted": False},
                  "observations": [{"attributes": {"event_time": "2025-01-30T12:00:00+00:00",
                                                       "month": "2025-01"}}],
              }}}
    original = __import__("copy").deepcopy(period)
    capture = datetime.now(timezone.utc)
    left = trial.TimedSourceAdapter(scenario["public"]["catalog"], "hypatia-test", Audit())
    right = trial.TimedSourceAdapter(scenario["public"]["catalog"], "hypatia-test", Audit())
    left.set_period(period, capture)
    right.set_period(period, capture)
    snapshot = left.snapshots["company_mcp|monthly-sales"]
    assert left.snapshots == right.snapshots
    assert snapshot["metadata"]["measurement_month"] == "2025-01"
    assert snapshot["metadata"]["cutoff_at"] == "2025-01-31T00:00:00+00:00"
    assert snapshot["observations"] == original["snapshots"]["company_mcp|monthly-sales"]["observations"]
    assert snapshot["metadata"]["native_cadence_replay"] == {
        "historical_fixture": True,
        "warehouse_freshness_asserted": False,
        "gateway_response_captured_at": capture.isoformat(),
        "original_saved_source_capture": "2025-01-31T00:00:00+00:00",
    }
    assert snapshot["captured_at"] == snapshot["source_captured_at"] == capture.isoformat()
    assert datetime.fromisoformat(snapshot["source_captured_at"]) <= datetime.now(timezone.utc)
    assert left.period_context == {
        "period_id": "month-01", "as_of": period["as_of"],
        "simulation_as_of": period["as_of"],
        "query_capture_at": capture.isoformat(), "time_basis": "historical_fixture_replay",
    }
    assert period == original


@pytest.mark.asyncio
async def test_owner_approval_uses_historical_current_period_and_finishes_onboarding():
    scenario, _ = cadence_scenario()
    public = _public_for_session(scenario)
    onboarding_period = public["onboarding"]
    capture = datetime.now(timezone.utc)
    adapter = trial.TimedSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    adapter.set_period(onboarding_period, capture)
    card = {"id": "approved-card", "version": 1, "status": "approved",
            "sources": [], "delivery_methods": []}
    reviewer_calls = []
    expected_current_period = {
        "period_id": onboarding_period["period_id"],
        "as_of": onboarding_period["as_of"],
    }

    class ApprovalServer(FakeServer):
        async def call_tool(self, name, arguments):
            assert name == "get_insight_card"
            assert arguments == {"card_id": card["id"]}
            return [], card

    async def reviewer(**kwargs):
        assert kwargs["source_context"]["current_period"] == expected_current_period
        reviewer_calls.append(kwargs)
        return {"approved": True, "reasons": []}

    session = trial.CadenceSession(
        public, adapter, ApprovalServer(), True, arm="treatment", owner_reviewer=reviewer,
    )
    session.notes = "Review the approved monthly policy against inspected source evidence."
    session.owner_topics.add("policy")
    session.adapter.inspected.add("company_mcp|monthly-sales")

    approval = await session.call(
        "request_synthetic_owner_approval", {"card_id": card["id"]},
    )
    assert approval["approved"] is True
    assert len(reviewer_calls) == 1
    current_period = reviewer_calls[0]["source_context"]["current_period"]
    assert current_period == expected_current_period
    assert adapter.period_context["as_of"] == adapter.period_context["simulation_as_of"]
    assert adapter.period_context["query_capture_at"] == capture.isoformat()
    assert adapter.period_context["query_capture_at"] != adapter.period_context["as_of"]

    result = await session.call("finish_setup", {"card_id": card["id"]})
    assert result["setup_complete"] is True
    assert session.setup_complete is True


def test_native_tool_error_count_survives_a_successful_retry():
    calls = [
        {"name": "evaluate_insight_card", "returned": False, "error_type": "TimeoutError"},
        {"name": "evaluate_insight_card", "returned": True, "result": {"status": "ok"}},
    ]
    assert trial._native_decision_tool_error_count(calls) == 1
    assert trial.product_use_status("treatment", native_attempts=2, native_valid_results=1) == (
        "native_current_result_available"
    )


def test_native_argument_validation_errors_come_from_audit_not_product_results():
    rejected_args = [
        {"card_id": "card-1", "idempotency_key": "missing-window"},
        {"card_id": "card-1", "window": 1},
    ]
    dispatched_validation_args = {"card_id": "card-1", "idempotency_key": "valid-window"}
    receipt_args = {"receipt_id": "receipt-1"}
    events = [
        {"kind": "tool.result", "name": "evaluate_insight_card", "arguments": args,
         "result": {"error": "ValidationError", "message": "argument schema mismatch"}}
        for args in rejected_args
    ] + [
        {"kind": "tool.result", "name": "evaluate_insight_card",
         "arguments": dispatched_validation_args,
         "result": {"error": "ValidationError", "message": "product-side validation"}},
        {"kind": "tool.result", "name": "get_decision_receipt", "arguments": receipt_args,
         "result": {"error": "RuntimeError", "message": "receipt lookup failed"}},
    ]
    dispatched = [
        {"name": "evaluate_insight_card", "arguments": dispatched_validation_args,
         "returned": False, "error_type": "ValidationError"},
        {"name": "get_decision_receipt", "arguments": receipt_args,
         "returned": False, "error_type": "RuntimeError"},
    ]

    assert trial._native_tool_argument_validation_error_count(events, dispatched) == 2
    assert trial._native_decision_tool_error_count(dispatched) == 2
    assert len([event for event in events if event["kind"] == "tool.result"
                and event["name"] in trial.NATIVE_DECISION_TOOLS]) == 4
    assert trial.product_use_status("treatment", native_attempts=len(dispatched),
                                    native_valid_results=0) == "native_attempt_failed"


def test_usage_separates_jev_attempts_responses_successes_and_errors():
    usage = trial._usage([
        {"kind": "api.request", "provider": "jev", "request_id": 1},
        {"kind": "api.error", "provider": "jev", "request_id": 1, "seconds": 1},
        {"kind": "api.request", "provider": "jev", "request_id": 2},
        {"kind": "api.response", "provider": "jev", "request_id": 2,
          "usage": {"input_tokens": 10, "output_tokens": 2}, "seconds": 2},
    ])
    assert usage["jev"]["attempts"] == 2
    assert usage["jev"]["responses"] == usage["jev"]["successes"] == 1
    assert usage["jev"]["errors"] == usage["jev"]["failed_attempts"] == 1
    assert usage["jev"]["unknown_usage"] == 1
