"""Guard the paired trial before any live credits are spent."""

import copy
import json

import pytest

from evaluations.bootstrap_agent_trial import Audit
from evaluations.business_outcome_cases import cases
from evaluations.business_outcome_trial import (
    BusinessSession,
    public_company,
    retained_onboarding_cost,
    review_packet,
    run_trial,
    summarize,
    validated_retained_card,
)
from evaluations.first_report_probes import DEFAULT_APPROVED_RUN
from evaluations.first_report_trial import PeriodAdapter


def session(treatment=False):
    company = cases()[0]
    audit = Audit()
    adapter = PeriodAdapter(company["descriptors"], audit, company["sources"])
    adapter.set_period(company["periods"][0])
    return BusinessSession(company=company, adapter=adapter, server=None, audit=audit,
                           treatment=treatment, card_id="test")


async def payload(subject):
    current = await subject.call("current_period", {})
    inspected = await subject.call("inspect_source", {"source_key": subject.company["sources"][0]["key"]})
    return {"period_id": current["period_id"], "status": "complete", "outcome": "notify",
            "recipients": [subject.company["destinations"][0]["key"]],
            "analysis_refs": [{"source_key": a["source_key"], "comparison_key": a["comparison_key"]}
                              for a in inspected["analyses"]],
            "narrative": "Observed accounting change; no causal conclusion."}


def test_public_company_excludes_private_labels_without_mutating_truth():
    company = cases()[0]
    assert "oracle" not in json.dumps(public_company(company))
    assert "oracle" in company["periods"][0]


async def test_no_future_period_or_oracle_in_tool_projection():
    subject = session()
    for name, args in (("current_period", {}), ("catalog", {}),
                       ("inspect_source", {"source_key": subject.company["sources"][0]["key"]})):
        text = json.dumps(await subject.call(name, args))
        assert "oracle" not in text
        assert all(p["id"] not in text for p in subject.company["periods"][1:])
    assert "oracle" not in json.dumps(subject.company)


async def test_sequential_submission_requires_fresh_inspection_and_period_id():
    subject = session()
    first = await payload(subject)
    response = await subject.call("submit_report", first)
    assert response["next_period"]["period_id"] != first["period_id"]
    assert subject.submission is None
    with pytest.raises(ValueError, match="current period"):
        await subject.call("submit_report", first)
    first["period_id"] = response["next_period"]["period_id"]
    with pytest.raises(ValueError, match="Inspect every"):
        await subject.call("submit_report", first)
    while subject.submission is None:
        await subject.call("submit_report", await payload(subject))
    assert len(subject.runs) == 4
    assert len(subject.deliveries) == 4
    with pytest.raises(ValueError, match="All periods"):
        await subject.call("submit_report", first)
    assert len(subject.deliveries) == 4


@pytest.mark.parametrize("field,value,match", [
    ("recipients", ["invented"], "directory"),
    ("narrative", " ", "narrative"),
])
async def test_both_arms_reject_invalid_delivery_payload(field, value, match):
    subject = session()
    request = await payload(subject)
    request[field] = value
    with pytest.raises(ValueError, match=match):
        await subject.call("submit_report", request)
    assert not subject.runs and not subject.deliveries


async def test_treatment_replay_and_writer_cannot_change_authoritative_result(monkeypatch):
    subject = session(True)
    request = await payload(subject)
    analyses = list(subject.inspected_analyses.values())
    authoritative = {"status": "complete", "outcome": "notify", "recipients": request["recipients"],
                     "analyses": analyses, "narrative": "Source-backed report"}
    calls = []

    async def dispatch(*args):
        calls.append(args)
        return {"report": {"status": "complete"}, "report_markdown": "Source-backed report"}

    monkeypatch.setattr("evaluations.business_outcome_trial.dispatch", dispatch)
    monkeypatch.setattr("evaluations.business_outcome_trial.native_submission", lambda *_: copy.deepcopy(authoritative))
    monkeypatch.setattr("evaluations.business_outcome_trial.build_briefing_writer_input",
                        lambda report, markdown, recipients: {"report": report, "recipients": recipients})
    async def create_briefing(*args, **kwargs):
        return {"writer_status": "accepted"}
    monkeypatch.setattr("evaluations.business_outcome_trial.create_briefing", create_briefing)
    first = await subject.call("evaluate_workflow", {})
    assert await subject.call("evaluate_workflow", {}) == first
    assert len(calls) == 2  # one run and one receipt replay; no second evaluation
    assert subject.native_meta["replay_exact_no_calls"]
    with pytest.raises(ValueError, match="cannot change"):
        await subject.call("submit_report", {**request, "outcome": "ignore"})
    with pytest.raises(ValueError, match="Retain every"):
        await subject.call("submit_report", {**request, "analysis_refs": []})
    await subject.call("submit_report", request)
    assert subject.runs[0]["submission"]["analyses"] == analyses
    assert subject.native is None


async def test_baseline_never_has_signalweave_tool():
    subject = session()
    assert "evaluate_workflow" not in {t["name"] for t in await subject.specs()}
    with pytest.raises(ValueError, match="baseline"):
        await subject.call("evaluate_workflow", {})


def test_missing_submissions_remain_failures_not_quiet_successes():
    companies = cases()[:1]
    summary = summarize([], companies)
    for arm in summary.values():
        assert arm["intended_periods"] == 4
        assert arm["submitted"] == arm["strict_passed"] == 0
        assert arm["review_required_proxy"] == 4
        assert arm["quiet_periods_correctly_suppressed"] == 0


def test_wrong_routing_and_useless_alerts_are_not_scored_as_success():
    companies = cases()[:1]
    for period in companies[0]["periods"]:
        period["oracle"].update(outcome="ignore", recipients=[])
    row = {"company": companies[0]["id"], "arm": "baseline", "episode": {"seconds": 1, "tool_calls": 2},
           "runs": [{"period": companies[0]["periods"][0]["id"], "source_reads": 1,
                     "submission": {"status": "complete", "outcome": "notify", "recipients": ["someone"],
                                    "analyses": [], "narrative": "Alert"}}]}
    result = summarize([row], companies)["baseline"]
    assert result["false_notification_periods"] == 1
    assert result["wrong_recipient_periods"] == 1
    assert result["strict_passed"] == 0


def test_review_packet_masks_arm_identity_and_preserves_missing_cases():
    packet, key = review_packet([], cases()[:1])
    assert len(packet["cases"]) == len(key) == 4
    for case in packet["cases"]:
        assert case["candidates"] == {"A": None, "B": None}
        assert set(key[case["id"]].values()) == {"baseline", "signalweave"}
        assert "expected" in case  # reviewer may see truth; test agents never do
    assert "signalweave" not in json.dumps(packet)


def test_retained_setup_cost_excludes_monitoring_and_keeps_failures():
    result = retained_onboarding_cost({"northstar-cart", "harbor-help", "redwood-fulfillment"})
    assert sum(c["jev"]["attempts"] for c in result["companies"].values()) == 28
    assert sum(c["openai"]["attempts"] for c in result["companies"].values()) == 4
    assert len(result["source_journal_sha256"]) == 2


async def test_actual_dry_manifest_separates_private_labels_and_validates_restored_context(tmp_path):
    output = tmp_path / "dry"
    assert (await run_trial(output))["paid_calls"] == 0
    manifest = json.loads((output / "manifest.json").read_text())
    assert "oracle" not in json.dumps(manifest["companies"])
    assert manifest["companies"] == [public_company(c) for c in cases()]
    expected = json.loads((output / "expected.json").read_text())
    assert expected == {c["id"]: {p["id"]: p["oracle"] for p in c["periods"]} for c in cases()}
    assert manifest["budget"] == {"jev_attempts": 12, "codex_episodes": 6}
    assert not (output / "events.jsonl").exists()


def test_restoration_requires_matching_successful_approval():
    row = json.loads((DEFAULT_APPROVED_RUN / "report.json").read_text())["results"][0]
    assert validated_retained_card(row).status.value == "approved"
    for mutation in ("status", "policy", "plan"):
        changed = copy.deepcopy(row)
        if mutation == "status":
            changed["approval"]["status"] = "rejected"
        elif mutation == "policy":
            changed["card"]["decision_guidance"] = "A different unapproved policy"
        else:
            changed["card"]["compiled_plan"]["card_version"] += 1
        with pytest.raises(ValueError):
            validated_retained_card(changed)


def test_duplicate_results_cannot_silently_replace_evidence():
    row = {"arm": "baseline", "company": cases()[0]["id"], "runs": [{"period": "p05"}]}
    with pytest.raises(ValueError, match="Duplicate"):
        summarize([row, row], cases())


async def test_actual_native_shape_projects_only_briefing_and_accepts_replay_metadata(monkeypatch):
    from signalweave.models import InsightCard, InsightResult, ResourceSnapshot
    from signalweave.reporting import build_investigation_report, render_investigation_report

    row = json.loads((DEFAULT_APPROVED_RUN / "report.json").read_text())["results"][0]
    native = copy.deepcopy(row["runs"][0]["native"])
    # Retained v2 predates intended_audience. Rebuild the current report contract
    # from its archived source inputs, as a current live evaluation does.
    rebuilt = build_investigation_report(
        InsightCard.model_validate(native["card"]), InsightResult.model_validate(native["result"]),
        [ResourceSnapshot.model_validate(r) for r in native["resources"]])
    native["report"] = rebuilt.model_dump(mode="json")
    native["report_markdown"] = render_investigation_report(rebuilt)
    native["result"]["report"] = native["report"]
    native["result"]["report_markdown"] = native["report_markdown"]
    calls = 0

    async def dispatch(*_):
        nonlocal calls
        response = copy.deepcopy(native)
        calls += 1
        if calls == 2:
            response["replayed"] = True
            response["receipt"]["status"] = "replayed"
            for field in ("card", "resources", "retrieval", "plan"):
                response.pop(field, None)
        return response

    monkeypatch.setattr("evaluations.business_outcome_trial.dispatch", dispatch)
    subject = session(True)
    result = await subject.call("evaluate_workflow", {})
    assert set(result) == {"period_id", "writer_input"}
    writer = result["writer_input"]
    assert not {"card", "resources", "plan", "report_markdown"} & set(writer)
    assert writer["report"]["numeric_claims"] == native["report"]["numeric_claims"]
    assert writer["configured_recipient_keys"] == ["commerce-owner"]
    assert subject.native_meta["replay_exact_no_calls"]
