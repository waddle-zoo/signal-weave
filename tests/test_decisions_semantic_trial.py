from decimal import Decimal

import pytest

from evaluations.decisions_semantic_trial import (
    Episode,
    grade,
    grade_conflict,
    grade_policy,
    grade_review,
    has_owner_routes,
    save_ledger_snapshot,
)


class Company:
    name = "company"
    metric_id = "retail.net_revenue"
    unit = "USD"
    canonical_resource = "metric:net-revenue"
    current_period = "2026-09"
    previous_period = "2026-08"
    business_policy = "Notify Finance on a comparable decline exceeding ten percent."

    def expected(self):
        return {"current": Decimal("800.01"), "previous": Decimal("1000"),
                "change_pct": Decimal("-19.999")}

    def notes(self):
        return [{"body": "The source-owned Finance definition"}]


def submission():
    return {"metric_id": "retail.net_revenue", "unit": "USD",
            "source_refs": ["company|metric:net-revenue"], "current": 800.01,
            "previous": 1000, "definition_revision": "r3",
            "current_period": "2026-09", "previous_period": "2026-08",
            "outcome": "notify", "recipients": ["agent://finance"], "resolution_status": "resolved"}


def test_independent_checks_accept_the_frozen_measurement_not_its_prose():
    assert all(grade(submission(), Company()).values())
    assert not grade({}, Company())["submitted"]


def test_self_assessed_resolution_is_not_a_numeric_correctness_oracle():
    actual = {**submission(), "resolution_status": "unresolved"}
    assert all(grade(actual, Company()).values())
    # Material caveats and whether the brief answers the question require the
    # separately preregistered independent prose review, not this model label.
    assert not grade_conflict(submission())["no_definitive_resolution"]


def test_old_onboarding_amounts_and_policy_fail_after_source_measurements_change(tmp_path):
    from evaluations.semantic_company import SemanticCompany

    company = SemanticCompany(tmp_path, "retail")
    company.set_condition("decline")
    old = company.expected()
    actual = {**submission(), "current": float(old["current"]), "previous": float(old["previous"])}
    assert all(grade(actual, company).values())
    company.set_condition("quiet")
    assert not grade(actual, company)["current"]
    assert not grade(actual, company)["outcome"]
    new = company.expected()
    actual.update(current=float(new["current"]), previous=float(new["previous"]),
                  outcome="ignore", recipients=[])
    assert all(grade(actual, company).values())


@pytest.mark.parametrize("field,value", [
    ("metric_id", "retail.gross_revenue"), ("unit", "EUR"),
    ("source_refs", ["company|metric:revenue-deprecated"]),
    ("current", 0.80001), ("previous", 999.99),
    ("current_period", "2026-08"), ("previous_period", "2026-07"),
    ("definition_revision", "r2"), ("outcome", "ignore"),
    ("recipients", ["agent://sales"]),
])
def test_checker_rejects_wrong_basis_scale_revision_period_or_action(field, value):
    actual = {**submission(), field: value}
    assert not all(grade(actual, Company()).values())


@pytest.mark.parametrize("value", [True, False, None, "800.01", float("nan"), float("inf")])
def test_amount_check_does_not_accept_nonfinite_or_non_numeric_values(value):
    assert not grade({**submission(), "current": value}, Company())["current"]


@pytest.mark.asyncio
async def test_baseline_keeps_company_tools_and_the_same_reviewed_brief():
    brief = {"card": {"id": "reviewed-card"}, "context": {"entries": [{"id": "reviewed-meaning"}]}}
    reader = Episode(Company(), None, notes=brief)
    tools = await reader.specs()
    assert {tool["name"] for tool in tools} == {
        "search_company_assets", "read_company_asset", "read_finance_notes", "submit_report",
    }
    notes = await reader.call("read_finance_notes", {})
    assert notes["reviewed_brief"] is brief
    assert notes["source_notes"] == Company().notes()
    assert notes["destinations"] == [{"key": "finance", "label": "Finance", "destination": "agent://finance"}]
    with pytest.raises(ValueError, match="Unknown company tool"):
        await reader.call("evaluate_insight_card", {})


@pytest.mark.asyncio
async def test_live_agent_uses_actual_native_tool_schemas_without_replacing_company_tools():
    class Native:
        async def list_tools(self):
            from mcp.types import Tool

            return [Tool(name="evaluate_insight_card", description="Native contract",
                         inputSchema={"type": "object", "properties": {"card_id": {"type": "string"}}})]

    reader = Episode(Company(), Native())
    tools = {tool["name"]: tool for tool in await reader.specs()}
    assert tools["evaluate_insight_card"]["description"] == "Native contract"
    assert {"search_company_assets", "read_company_asset", "read_finance_notes", "submit_report"} <= tools.keys()


@pytest.mark.parametrize("condition,outcome,routes", [
    ("quiet", "ignore", []), ("decline", "notify", ["agent://finance"]),
    ("gap", "insufficient_data", ["agent://finance"]), ("definition_conflict", "investigate", ["agent://finance"]),
])
def test_policy_gate_checks_decision_recipient_provider_and_no_send(condition, outcome, routes):
    packet = {"result": {"outcome": outcome, "evaluator": "openai-decisions",
                          "delivery_methods": [{"destination": route} for route in routes]},
              "receipt": {"delivery_enabled": False}}
    assert all(grade_policy(condition, packet).values())
    packet["result"]["outcome"] = "notify" if condition != "decline" else "ignore"
    assert not grade_policy(condition, packet)["outcome"]
    packet["result"]["outcome"] = outcome
    packet["result"]["delivery_methods"] = [{"destination": "agent://unrelated-team"}]
    assert not grade_policy(condition, packet)["recipient"]
    packet["result"]["evaluator"] = "offline-heuristic"
    assert not grade_policy(condition, packet)["provider"]
    packet["receipt"]["delivery_enabled"] = True
    assert not grade_policy(condition, packet)["shadow"]


@pytest.mark.parametrize("condition", ["gap", "definition_conflict"])
def test_conservative_enum_without_owner_route_does_not_pass_review_policy(condition):
    packet = {"result": {"outcome": "insufficient_data", "evaluator": "openai-decisions", "delivery_methods": []},
              "receipt": {"delivery_enabled": False}}
    assert not grade_policy(condition, packet)["recipient"]


@pytest.mark.asyncio
async def test_review_delivery_is_explicit_local_once_and_requires_actual_matching_brief():
    ordinary = Episode(Company(), None)
    with pytest.raises(ValueError, match="Unknown"):
        await ordinary.call("send_finance_review", {})
    episode = Episode(Company(), None, review_delivery=True)
    assert "send_finance_review" in {tool["name"] for tool in await episode.specs()}
    message = "Finance: source coverage is incomplete; investigate the gap before drawing a revenue conclusion."
    actual = {**submission(), "outcome": "insufficient_data", "resolution_status": "unresolved",
              "message": message, "uncertainties": ["Missing coverage"]}
    assert not grade_review(episode, Company())["delivered_once"]
    with pytest.raises(ValueError, match="owner-supplied"):
        await episode.call("send_finance_review", {"destination": "agent://leadership", "message": message,
                                                   "source_refs": actual["source_refs"]})
    result = await episode.call("send_finance_review", {"destination": "agent://finance", "message": message,
                                                      "source_refs": actual["source_refs"]})
    assert result["delivered"] and not result["human_acknowledged"]
    episode.submission = actual
    assert all(grade_review(episode, Company()).values())
    episode.submission = {**actual, "outcome": "investigate"}
    assert all(grade_review(episode, Company()).values())
    episode.submission = {**actual, "message": "A different report was submitted"}
    assert not grade_review(episode, Company())["delivery_matches_brief"]
    with pytest.raises(ValueError, match="already"):
        await episode.call("send_finance_review", {"destination": "agent://finance", "message": message,
                                                  "source_refs": actual["source_refs"]})


def test_onboarding_preserves_all_owner_routes_without_extra_destinations_or_duplicates():
    card = {"delivery_methods": [{"outcome": outcome, "destination": "agent://finance"}
                                  for outcome in ("notify", "investigate", "insufficient_data")]}
    assert has_owner_routes(card)
    assert not has_owner_routes({"delivery_methods": card["delivery_methods"][:-1]})
    for extra in ({"outcome": "notify", "destination": "agent://leadership"},
                  {"outcome": "notify", "destination": "agent://finance"}):
        assert not has_owner_routes({"delivery_methods": [*card["delivery_methods"], extra]})


def test_phase_backup_preserves_actual_ledger_before_later_conditions(tmp_path):
    from evaluations.semantic_company import SemanticCompany

    company = SemanticCompany(tmp_path, "saas")
    company.set_condition("decline")
    old = company.expected()
    record = save_ledger_snapshot(company, tmp_path, "initial")
    company.publish_measurement_refresh()
    with company._connect() as db:
        assert company._data_snapshot_id(db) != record["data_snapshot_id"]
    import hashlib
    import sqlite3

    path = tmp_path / record["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
    with sqlite3.connect(path) as db:
        assert company._data_snapshot_id(db) == record["data_snapshot_id"]
        assert db.execute("SELECT DISTINCT activity_bp FROM transactions WHERE period='2026-09'").fetchall() == [(8200,)]
    assert company.expected() != old
    with pytest.raises(FileExistsError):
        save_ledger_snapshot(company, tmp_path, "initial")


def test_conflict_gate_keeps_attributed_facts_without_claiming_a_reconciled_answer():
    actual = {**submission(), "resolution_status": "unresolved", "outcome": "investigate",
              "uncertainties": ["Finance r3 and the competing invoice-month definition differ; ask the owners to reconcile."]}
    assert all(grade_conflict(actual, Company()).values())
    # Known r3 amounts need not disappear; their interpretation remains unresolved.
    assert actual["current"] == 800.01
    assert not grade_conflict({**actual, "resolution_status": "resolved"})["no_definitive_resolution"]
    assert not grade_conflict({**actual, "outcome": "notify"})["unresolved"]
    assert not grade_conflict({**actual, "recipients": ["agent://leadership"]})["only_authorized_review_audience"]
    assert not grade_conflict({**actual, "uncertainties": []})["uncertainty_explicit"]
    assert not grade_conflict({**actual, "current": 9999}, Company())["attributed_current"]
    assert not grade_conflict({**actual, "unit": "EUR"}, Company())["attributed_basis"]
    assert not grade_conflict({**actual, "source_refs": []}, Company())["source_attribution"]
