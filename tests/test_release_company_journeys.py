import inspect
import json
import stat
from datetime import datetime

import pytest

from evaluations.bootstrap_agent_trial import (
    Audit,
    PublicSourceAdapter,
)
from evaluations.bootstrap_agent_trial import (
    agent_context as runner_agent_context,
)
from evaluations.bootstrap_scenarios import public_scenario, score_submission
from evaluations.installed_workflow_trial import run_trial
from evaluations.release_company_journeys import (
    _COMPANIES,
    AGENT_TOOLS,
    CERTIFIED_BINARY_SHA256,
    CERTIFIED_SOURCE_SHA256,
    CERTIFIED_VERSION,
    MAX_REPORT_CHARS,
    ask_owner,
    journeys,
    make_binary_preflight,
    pilot_scenarios,
    protocol,
    score_owner_clarification,
    score_report,
    score_report_first,
    to_installed_trial_scenario,
)
from signalweave.mcp_source import MCPConnection
from signalweave.models import SourceRef


def test_six_journeys_have_twenty_four_diverse_later_episodes_and_valid_dates():
    scenarios = journeys()
    assert len(scenarios) == 6
    assert len({item["public"]["family"] for item in scenarios}) == 6
    assert sum(len(item["public"]["periods"]) for item in scenarios) == 24
    for item in scenarios:
        assert len(item["public"]["periods"]) == 4
        assert len({period["period_id"] for period in item["public"]["periods"]}) == 4
        timestamps = [datetime.fromisoformat(period["as_of"]) for period in
                      [item["public"]["onboarding"], *item["public"]["periods"]]]
        assert timestamps == sorted(timestamps)
        assert all(timestamp.tzinfo is not None for timestamp in timestamps)
    assert any(label["decision"] == "ignore" for item in scenarios
               for label in item["private"]["episodes"].values())
    assert any(label["decision"] == "notify" for item in scenarios
               for label in item["private"]["episodes"].values())
    assert any(label["decision"] == "insufficient_data" for item in scenarios
               for label in item["private"]["episodes"].values())


def test_native_superset_snapshots_keep_weak_contract_and_source_gaps_visible():
    scenarios = journeys()
    superset = [snapshot for scenario in scenarios
                for period in [scenario["public"]["onboarding"], *scenario["public"]["periods"]]
                for snapshot in period["snapshots"].values()
                if snapshot["adapter"] == "superset"]
    assert superset
    assert all(snapshot["metadata"]["transport_kind"] == "synthetic_superset_chart_snapshot"
               for snapshot in superset)
    assert all(snapshot["source_url"] is None for snapshot in superset)
    assert all(snapshot["metadata"]["fixture_source"] == "synthetic" for snapshot in superset)
    assert all(not snapshot["contract"].get("roles") for snapshot in superset)
    assert any("error" in snapshot for scenario in scenarios
               for period in scenario["public"]["periods"]
               for snapshot in period["snapshots"].values())
    assert any(label["source_error_slots"] for scenario in scenarios
               for label in scenario["private"]["episodes"].values())
    assert any(label.get("known_data_gap") for scenario in scenarios
               for label in scenario["private"]["episodes"].values())


@pytest.mark.asyncio
async def test_all_six_journeys_and_all_24_periods_run_through_source_and_scorer_contracts():
    scenarios = journeys()
    assert len(scenarios) == 6
    assert sum(len(item["public"]["periods"]) for item in scenarios) == 24
    scored_episode_count = 0

    for source_scenario in scenarios:
        shared = to_installed_trial_scenario(source_scenario)
        visible = runner_agent_context(public_scenario(shared))
        assert visible["company"] == shared["public"]["company"]
        assert "owner_answers" not in visible
        assert "periods" not in visible

        public = public_scenario(shared)
        audit = Audit()
        adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
        all_periods = [public["onboarding"], *public["periods"]]
        for period in all_periods:
            adapter.set_period(period, datetime.fromisoformat(period["as_of"]))
            assert set(period["snapshots"]) == {
                f"{source['adapter']}|{source['resource']}" for source in public["catalog"]
            }
            for ref, snapshot in period["snapshots"].items():
                source = next(item for item in public["catalog"]
                              if f"{item['adapter']}|{item['resource']}" == ref)
                inspected = await adapter.inspect(SourceRef(
                    key=ref, adapter=source["adapter"], resource=source["resource"],
                    label=source["title"],
                ))
                assert inspected.adapter == snapshot["adapter"]
                assert inspected.resource == snapshot["resource"]

        assert len(shared["private"]["periods"]) == 4
        for period in public["periods"]:
            period_id = period["period_id"]
            label = shared["private"]["periods"][period_id]
            claims = [
                {"fact": fact, "value": fact_value["value"], "unit": fact_value["unit"],
                 "evidence_refs": fact_value["evidence_refs"]}
                for fact, fact_value in label["numeric_facts"].items()
            ]
            result = score_submission(
                shared, period_id,
                {"outcome": label["outcome"], "recipients": label["recipients"],
                 "evidence_refs": label["required_evidence_refs"], "numeric_claims": claims,
                 "claims": [], "summary": "Source-checked synthetic contract submission."},
                inspected_refs=set(period["snapshots"]),
                asked_owner_topics=set(label["required_owner_topics"]),
            )
            assert result["valid_submission"] is True, (shared["scenario_id"], period_id, result)
            assert result["exact"] is True, (shared["scenario_id"], period_id, result)
            scored_episode_count += 1

    assert scored_episode_count == 24


def test_shared_runner_adapter_preserves_private_labels_and_only_known_owner_policy():
    scenario = journeys()[2]
    adapted = to_installed_trial_scenario(scenario, period_ids=["later-02"])
    assert list(adapted["private"]["periods"]) == ["later-02"]
    assert adapted["private"]["periods"]["later-02"]["outcome"] == "notify"
    assert "5%" in adapted["public"]["owner_answers"]["materiality"]
    assert scenario["private"]["owner_answers"]["materiality"]["known"] is True
    assert adapted["public"]["periods"][0]["period_id"] == "later-02"
    assert adapted["public"]["brief"] == scenario["public"]["brief"]


def test_all_six_installed_manifests_preserve_synthetic_source_adapter_identity():
    from evaluations.installed_trial_transport import _manifest

    for source_scenario in journeys():
        adapted = to_installed_trial_scenario(source_scenario)
        public = public_scenario(adapted)
        manifest = _manifest(public, "http://127.0.0.1:12345/synthetic")
        expected_refs = {
            f"{source['adapter']}|{source['resource']}" for source in public["catalog"]
        }
        manifest_refs = set()
        connection_names = set()
        for raw_connection in manifest["connections"]:
            connection = MCPConnection.model_validate(raw_connection)
            connection_names.add(connection.name)
            manifest_refs.update(resource.arguments["ref"] for resource in connection.resources)
        assert connection_names == {item["adapter"] for item in public["catalog"]}
        assert manifest_refs == expected_refs
        assert all(item["metadata"]["fixture_source"] == "synthetic"
                   for item in public["catalog"])
        for period in [public["onboarding"], *public["periods"]]:
            for snapshot in period["snapshots"].values():
                assert snapshot["source_url"] is None
                assert snapshot["metadata"]["fixture_source"] == "synthetic"


def test_unresolved_owner_policy_stays_unknown_until_real_hil_and_never_becomes_notify():
    unknown_policy_ids = {"journey-01", "journey-02", "journey-04", "journey-06"}
    for scenario in journeys():
        scenario_id = scenario["scenario_id"]
        if scenario_id in unknown_policy_ids:
            missing_topics = set(scenario["private"]["onboarding"]["alert_topics_missing"])
            assert missing_topics
            for topic in missing_topics:
                assert ask_owner(scenario, topic)["known"] is False
                after_report = ask_owner(scenario, topic, after_first_report=True)
                assert after_report["known"] is True
                assert after_report["stage"] == "post_first_report_owner_clarification"
                assert after_report["answer_source"] == "synthetic_owner_persona_hil"
                assert after_report["answer"] not in json.dumps(scenario["public"])

        for label in scenario["private"]["episodes"].values():
            if scenario_id in unknown_policy_ids and label["decision"] == "investigate":
                assert label["expected_recipients"] == []
                assert label["signal_decision"] == "notify"
                assert label["recommendation_authorized"] is False
                assert label["alert_policy_status"] == "unresolved"
                assert all(not scenario["private"]["owner_answers"][topic]["known"]
                           for topic in label["clarification_slots"])
            if label["decision"] == "notify":
                assert ask_owner(scenario, "materiality")["known"] is True
                assert ask_owner(scenario, "routing")["known"] is True


def test_scope_and_window_rubric_checks_expected_population_and_intervals():
    scenarios = journeys()
    quiet = scenarios[0]
    good = score_report(
        quiet, "later-01",
        {"decision": "ignore", "recipients": [], "evidence_refs": [], "metrics": [],
         "scope": quiet["private"]["episodes"]["later-01"]["expected_scope"],
         "window": "previous complete 7 days"},
    )
    wrong_window = score_report(
        quiet, "later-01",
        {"decision": "ignore", "recipients": [], "evidence_refs": [], "metrics": [],
         "scope": quiet["private"]["episodes"]["later-01"]["expected_scope"],
         "window": "previous complete 14 days"},
    )
    wrong_scope = score_report(
        quiet, "later-01",
        {"decision": "ignore", "recipients": [], "evidence_refs": [], "metrics": [],
         "scope": "saas_customer_health", "window": "previous complete 7 days"},
    )
    assert good["dimensions"]["scope_window"] == 10
    assert wrong_window["dimensions"]["scope_window"] == 0
    assert wrong_scope["dimensions"]["scope_window"] == 0

    conflicted = scenarios[3]
    valid_conflict = score_report(
        conflicted, "later-03",
        {"decision": "insufficient_data", "recipients": [], "evidence_refs": [],
         "metrics": [], "scope": conflicted["private"]["episodes"]["later-03"]["expected_scope"],
         "window": "calendar month conflicts with billing rolling 7 days; not comparable"},
    )
    hidden_conflict = score_report(
        conflicted, "later-03",
        {"decision": "insufficient_data", "recipients": [], "evidence_refs": [],
         "metrics": [], "scope": conflicted["private"]["episodes"]["later-03"]["expected_scope"],
         "window": "previous 7 days"},
    )
    assert valid_conflict["dimensions"]["scope_window"] == 10
    assert hidden_conflict["dimensions"]["scope_window"] == 0


def test_pilot_selection_is_bounded_and_spans_quiet_and_actionable_pairs():
    two = pilot_scenarios(2)
    four = pilot_scenarios(4)
    assert [item["scenario_id"] for item in two] == ["journey-03", "journey-05"]
    assert sum(len(item["public"]["periods"]) for item in two) == 2
    assert sum(len(item["public"]["periods"]) for item in four) == 4
    assert [item["private"]["periods"][item["public"]["periods"][0]["period_id"]]["outcome"]
            for item in two] == ["notify", "ignore"]
    assert {period["period_id"] for item in four for period in item["public"]["periods"]} == {
        "later-01", "later-02"
    }


def test_shared_scorer_accepts_adapter_contract_and_public_view_hides_labels():
    scenario = pilot_scenarios(2)[0]
    shared_public = public_scenario(scenario)
    visible = runner_agent_context(shared_public)
    assert len(visible["company"]) > 0
    assert "owner_answers" not in visible
    assert "periods" not in visible
    assert "period" not in visible
    encoded = json.dumps(visible)
    assert "required_evidence_refs" not in encoded
    assert "expected_recipients" not in encoded

    period = scenario["public"]["periods"][0]
    label = scenario["private"]["periods"][period["period_id"]]
    claims = [
        {"fact": fact, "value": fact_value["value"], "unit": fact_value["unit"],
         "evidence_refs": fact_value["evidence_refs"]}
        for fact, fact_value in label["numeric_facts"].items()
    ]
    result = score_submission(
        scenario, period["period_id"],
        {"outcome": label["outcome"], "recipients": label["recipients"],
         "evidence_refs": label["required_evidence_refs"], "numeric_claims": claims,
         "claims": [], "summary": "Synthetic test submission."},
        inspected_refs=set(period["snapshots"]),
        asked_owner_topics=set(label["required_owner_topics"]),
    )
    assert result["valid_submission"] is True
    assert result["exact"] is True


def test_report_and_owner_questions_are_scored_in_the_correct_order():
    scenario = journeys()[0]
    label = scenario["private"]["onboarding"]
    required_refs = {
        f"{source['adapter']}|{source['resource']}"
        for source in _COMPANIES[0]["sources"] if source["slot"] in label["required"]
    }
    report = {
        "summary": "Paid-account net retention eased 2.5 points, mostly as expansion bookings cooled.",
        "scope": label["scope"], "window": label["window"],
        "evidence_refs": sorted(required_refs),
        "drivers": ["expansion revenue eased"],
        "recipient_action": "Share this scoped read with Customer Success; do not page automatically.",
        "automated_alert": False,
        # This must not count as a question asked: questions are a later action.
        "clarification_topics": ["materiality"],
    }
    scored = score_report_first(scenario, report, inspected_refs=required_refs)
    assert scored["dimensions"]["useful_report"] == 20
    assert "missing_policy_questions" not in scored["dimensions"]
    assert score_owner_clarification(
        scenario, asked_topics={"materiality"}, first_report_completed=True,
    )["exact"] is True
    assert score_owner_clarification(
        scenario, asked_topics={"materiality"}, first_report_completed=False,
    )["exact"] is False


def test_binary_preflight_requires_exact_parent_certificate(monkeypatch, tmp_path):
    identity = {"source_sha256": CERTIFIED_SOURCE_SHA256,
                "binary_sha256": CERTIFIED_BINARY_SHA256,
                "version": CERTIFIED_VERSION, "git_commit": "114614a",
                "dirty": True, "frozen": False}
    monkeypatch.setattr("scripts.binary_provenance.verify_binary", lambda _: identity)
    result = make_binary_preflight(
        tmp_path / "signalweave", CERTIFIED_SOURCE_SHA256,
        certified_binary_sha256=CERTIFIED_BINARY_SHA256,
        certified_version=CERTIFIED_VERSION,
        phase="live_setup",
    )
    assert result == {"phase": "live_setup", "status": "verified", "verification": identity}
    shared_gate = make_binary_preflight(
        tmp_path / "signalweave", CERTIFIED_SOURCE_SHA256,
        certified_binary_sha256=CERTIFIED_BINARY_SHA256,
        certified_version=CERTIFIED_VERSION,
        phase="shared_runner_gate",
    )
    assert shared_gate["status"] == "verified"
    with pytest.raises(ValueError, match="parent-certified fingerprint"):
        make_binary_preflight(
            tmp_path / "signalweave", "stale-source",
            certified_binary_sha256=CERTIFIED_BINARY_SHA256,
            certified_version=CERTIFIED_VERSION,
            phase="report_certification",
        )


def test_protocol_matches_shared_default_runner_and_model_contract():
    signature = inspect.signature(run_trial)
    for name in ("author_model", "author_effort", "recurring_agent_model",
                 "recurring_agent_effort", "reviewer_model", "reviewer_effort"):
        assert name in signature.parameters
    details = protocol()
    assert CERTIFIED_BINARY_SHA256 == (
        "6abe5f0e292a688a30c139f917e98cd6635bb4b6bb974597f23e3edfcda9d7b5"
    )
    assert CERTIFIED_SOURCE_SHA256 == (
        "9460d2e8e08a3e06de7309cf6c8d554b17043074d8fa9fe7fbdcee972c1298e2"
    )
    assert CERTIFIED_VERSION == "0.2.0rc2"
    assert details["profile"]["name"] == "agent"
    assert details["profile"]["tool_count"] == 10
    assert tuple(details["profile"]["tools"]) == AGENT_TOOLS
    assert details["bounded_pilot"]["runner"] == "evaluations.installed_workflow_trial.run_trial"
    assert "not measured" in details["bounded_pilot"]["status"]
    assert details["binary_provenance"]["certified_binary_sha256"] == CERTIFIED_BINARY_SHA256
    assert details["binary_provenance"]["status"] == "pending_preflight"
    assert details["bounded_pilot"]["synthetic_owner_hil_answers_in_fixture"] is True
    assert details["bounded_pilot"]["live_pilot_uses_synthetic_owner_hil"] is False
    assert MAX_REPORT_CHARS == 1_200


@pytest.mark.asyncio
async def test_live_wrapper_passes_explicit_luna_xhigh_and_private_artifacts(
    monkeypatch, tmp_path,
):
    from evaluations import installed_workflow_trial
    from evaluations.release_company_journeys import run_live_pilot

    identity = {"source_sha256": CERTIFIED_SOURCE_SHA256,
                "binary_sha256": CERTIFIED_BINARY_SHA256,
                "version": CERTIFIED_VERSION, "git_commit": "114614a",
                "dirty": True, "frozen": False}
    monkeypatch.setattr("evaluations.release_company_journeys.verify_certified_binary",
                        lambda *_args, **_kwargs: identity)
    captured = {}

    async def fake_run_trial(scenarios, **kwargs):
        captured["scenarios"] = scenarios
        captured["kwargs"] = kwargs
        return {"summary": {"completed": 0, "intended": 4}}

    monkeypatch.setattr(installed_workflow_trial, "run_trial", fake_run_trial)
    output = tmp_path / "pilot"
    await run_live_pilot(
        binary=tmp_path / "binary", key_file=tmp_path / "jev-key",
        output=output, pair_count=4, jev_budget=40,
    )
    assert captured["kwargs"]["jev_budget"] == 40
    assert captured["kwargs"]["live"] is True
    assert captured["kwargs"]["stage_gate"] == 4
    assert captured["kwargs"]["author_model"] == "gpt-6-luna"
    assert captured["kwargs"]["author_effort"] == "xhigh"
    assert captured["kwargs"]["recurring_agent_model"] == "gpt-6-luna"
    assert captured["kwargs"]["recurring_agent_effort"] == "xhigh"
    assert captured["kwargs"]["reviewer_model"] == "gpt-6-luna"
    assert captured["kwargs"]["reviewer_effort"] == "xhigh"
    assert sum(len(item["public"]["periods"]) for item in captured["scenarios"]) == 4
    preflight = json.loads((output / "preflight.json").read_text())
    assert preflight["private_labels_available_to_agent"] is False
    assert stat.S_IMODE((output / "preflight.json").stat().st_mode) == 0o600
    assert json.loads((output / "postflight.json").read_text())["same_as_preflight"] is True
