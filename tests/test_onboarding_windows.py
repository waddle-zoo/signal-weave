"""Offline window-contract regressions through MCP JSON dispatch and real stores."""

import json
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from signalweave.compiler import base_plan
from signalweave.diagnostics import analyze_comparison
from signalweave.models import InsightCard, ResourceContract, SourceRef
from signalweave.onboarding import InsightAuthoringService, resolve_comparison_windows
from tests.test_diagnostics import comparison
from tests.test_onboarding import (
    BoundedAnchorCatalogDouble,
    ExplicitAnchorJevDouble,
    SupersetCatalogDouble,
    make_server,
    tool,
)

CUSTOM = "fiscal/4-4-5:prior closed cycle@v2 – UTC"
AUTHORING = ["draft_insight_card", "propose_insight_card", "onboard_insight_card"]


def catalog_with_windows(windows=None):
    catalog = SupersetCatalogDouble()
    catalog.resources[0].contract.available_comparison_windows = (
        ["previous_period"] if windows is None else windows
    )
    # Keep the secondary fixture undeclared so tests can exercise mixed
    # required-source compatibility without manufacturing a shared window.
    catalog.resources[1].contract = ResourceContract()
    catalog.resources[2].contract = ResourceContract()
    return catalog


def arguments(name, **overrides):
    args = {
        "title": "Window contract", "what_to_watch": "Checkout conversion",
        "why_watch": "Decide whether the owner should respond.",
        "questions": ["Is there a material decline?"],
        "evidence_requirements": {"question:1": False},
        "retrieval_mode": "fixed", "investigation_mode": "none",
    }
    if name == "draft_insight_card":
        args["sources"] = [{
            "key": "metric", "adapter": "superset", "resource": "dashboard:7", "label": "Metric",
        }]
    else:
        args["selected_sources"] = [{"ref": "superset|dashboard:7"}]
    return {**args, **overrides}


async def dispatch(server, name, args):
    result = await server.call_tool(name, args)
    payload = result[1] if isinstance(result, tuple) else json.loads(
        next(item.text for item in result if getattr(item, "type", None) == "text")
    )
    return payload.get("proposal", payload)


def windows_blocker(review):
    return next((b for b in review["blockers"] if b["code"] == "comparison-window-mismatch"), None)


@pytest.mark.parametrize("name", AUTHORING)
@pytest.mark.parametrize("window", ["previous_period", CUSTOM, "Previous complete reporting week"])
async def test_dispatch_defaults_expose_exact_declarations_and_preserve_requirements(tmp_path, name, window):
    catalog = catalog_with_windows([window])
    server = make_server(tmp_path, catalog=catalog, sqlite=True)
    response = await dispatch(server, name, arguments(name))
    assert response["card"]["comparison_windows"] == response["plan"]["comparison_windows"] == [window]
    assert response["card"]["evidence_requirements"] == {"question:1": False}
    card_id = response["card"]["id"]
    review = (await dispatch(server, "review_insight_card", {"card_id": card_id}))["review"]
    selected = next(c for c in review["source_candidates"] if c["selected"])
    assert selected["available_comparison_windows"] == [window]
    assert selected["metadata"]["available_comparison_windows"] == [window]
    assert windows_blocker(review) is None
    assert (await dispatch(server, "approve_insight_card", {"card_id": card_id}))["status"] == "approved"
    restarted = make_server(tmp_path, catalog=catalog, sqlite=True)
    assert tool(restarted, "get_insight_card")(card_id)["comparison_windows"] == [window]


@pytest.mark.parametrize("name", AUTHORING)
@pytest.mark.parametrize("windows", [["Previous complete reporting week"], ["PREVIOUS_PERIOD"],
                                      ["previous_period "], ["previous_period", "unsupported"]])
async def test_dispatch_mismatch_cannot_be_confirmed_or_silently_filtered(tmp_path, name, windows):
    server = make_server(tmp_path, catalog=catalog_with_windows())
    response = await dispatch(server, name, arguments(name, comparison_windows=windows))
    assert response["card"]["comparison_windows"] == windows
    card_id = response["card"]["id"]
    review = (await dispatch(server, "review_insight_card", {"card_id": card_id}))["review"]
    blocker = windows_blocker(review)
    assert blocker["severity"] == "block"
    assert blocker["refs"] == ["superset|dashboard:7"]
    assert "requested" in blocker["message"] and "available" in blocker["message"]
    before = tool(server, "get_insight_card")(card_id)
    with pytest.raises(Exception, match="comparison-window-mismatch"):
        await dispatch(server, "approve_insight_card", {
            "card_id": card_id, "source_selection_fingerprint": review["source_selection_fingerprint"],
            "source_selection_reason": "Owner confirms this source.",
        })
    assert tool(server, "get_insight_card")(card_id) == before


@pytest.mark.parametrize("name", AUTHORING)
async def test_mcp_schema_and_dispatch_reject_explicit_empty_windows(tmp_path, name):
    server = make_server(tmp_path)
    spec = next(spec for spec in await server.list_tools() if spec.name == name)
    field = spec.inputSchema["properties"]["comparison_windows"]
    array = next(item for item in field["anyOf"] if item.get("type") == "array")
    assert array["minItems"] == 1 and array["maxItems"] == 20
    assert "available_comparison_windows" in json.dumps(field)
    assert "not required_comparison_keys" in json.dumps(field)
    if name == "draft_insight_card":
        description = spec.inputSchema["$defs"]["SourceRef"]["properties"]["required_comparison_keys"]["description"]
        assert "analytical_comparisons[].key" in description
        assert "NOT comparison_window" in description
        assert "do not invent" in description
    validator = Draft202012Validator(spec.inputSchema)
    assert not list(validator.iter_errors(arguments(name, comparison_windows=[CUSTOM])))
    assert list(validator.iter_errors(arguments(name, comparison_windows=[])))
    with pytest.raises(Exception, match="at least 1 item"):
        await dispatch(server, name, arguments(name, comparison_windows=[]))
    assert server._test_runtime.card_store.list_cards() == []


@pytest.mark.parametrize("optional", [False, True])
async def test_required_intersection_and_optional_mismatch(tmp_path, optional):
    catalog = catalog_with_windows([CUSTOM, "previous_period"])
    catalog.resources[1].contract.available_comparison_windows = ["year_over_year", CUSTOM]
    server = make_server(tmp_path, catalog=catalog)
    args = arguments("onboard_insight_card", selected_sources=[
        {"ref": "superset|dashboard:7"}, {"ref": "superset|dashboard:8", "required": not optional},
    ])
    response = await dispatch(server, "onboard_insight_card", args)
    assert response["card"]["comparison_windows"] == (sorted([CUSTOM, "previous_period"]) if optional else [CUSTOM])
    review = (await dispatch(server, "review_insight_card", {"card_id": response["card"]["id"]}))["review"]
    assert windows_blocker(review) is None
    assert any("Optional source comparison-window mismatch" in w for w in review["warnings"]) == optional


@pytest.mark.parametrize("name", AUTHORING)
async def test_empty_required_intersection_rejects_defaults_and_blocks_explicit_review(tmp_path, name):
    catalog = catalog_with_windows()
    catalog.resources[1].contract.available_comparison_windows = [CUSTOM]
    server = make_server(tmp_path, catalog=catalog)
    args = arguments(name)
    if name == "draft_insight_card":
        args["sources"].append({"key": "other", "adapter": "superset", "resource": "dashboard:8", "label": "Other"})
    else:
        args["selected_sources"].append({"ref": "superset|dashboard:8"})
    with pytest.raises(Exception, match="required sources have no common"):
        await dispatch(server, name, args)
    assert server._test_runtime.card_store.list_cards() == []
    response = await dispatch(server, name, {**args, "comparison_windows": ["previous_period"]})
    review = (await dispatch(server, "review_insight_card", {"card_id": response["card"]["id"]}))["review"]
    assert windows_blocker(review)["severity"] == "block"


@pytest.mark.parametrize("name", AUTHORING)
async def test_undeclared_sources_warn_without_blocking_or_inferring(tmp_path, name):
    server = make_server(tmp_path, catalog=catalog_with_windows([]))
    args = arguments(name)
    response = await dispatch(server, name, args)
    assert response["card"]["comparison_windows"] == ["previous_period", "trailing_4_period_average"]
    card_id = response["card"]["id"]
    review = (await dispatch(server, "review_insight_card", {"card_id": card_id}))["review"]
    assert any("undeclared" in w and "unverified" in w for w in review["warnings"])
    assert windows_blocker(review) is None
    assert (await dispatch(server, "approve_insight_card", {"card_id": card_id}))["status"] == "approved"


@pytest.mark.parametrize("automatic_outcome", ["notify", "escalate"])
async def test_undeclared_sources_block_automatic_routes(tmp_path, automatic_outcome):
    server = make_server(tmp_path, catalog=catalog_with_windows([]))
    response = await dispatch(server, "onboard_insight_card", arguments(
        "onboard_insight_card",
        decision_guidance="Notify the owner only when the selected comparison is materially abnormal.",
        delivery_methods=[{
            "key": "owner",
            "outcome": automatic_outcome,
            "label": "Owner",
            "destination": "agent://owner",
        }],
    ))
    review = (await dispatch(server, "review_insight_card", {
        "card_id": response["card"]["id"],
    }))["review"]
    blocker = windows_blocker(review)
    assert blocker["severity"] == "block"
    assert "automatic" in blocker["message"]
    with pytest.raises(Exception, match="comparison-window-mismatch"):
        await dispatch(server, "approve_insight_card", {"card_id": response["card"]["id"]})


async def test_undeclared_optional_quality_source_does_not_block_required_metric_route(tmp_path):
    catalog = catalog_with_windows(["previous_period"])
    # This source is a point-in-time freshness/partition check, not a metric
    # comparison. It is intentionally not required for the numeric route.
    catalog.resources[1].contract = ResourceContract()
    server = make_server(tmp_path, catalog=catalog)
    response = await dispatch(server, "onboard_insight_card", arguments(
        "onboard_insight_card",
        selected_sources=[
            {"ref": "superset|dashboard:7", "key": "metric", "required": True},
            {"ref": "superset|dashboard:8", "key": "quality", "required": False},
        ],
        numeric_conditions=[{
            "text": "Notify on a material decline.",
            "source_key": "metric",
            "comparison_key": "checkout_conversion",
            "measurement": "delta",
            "threshold": -0.1,
            "comparator": "<=",
            "unit": "ratio",
        }],
        decision_guidance="Notify the owner on a material decline; ignore ordinary variation.",
        delivery_methods=[{
            "key": "owner",
            "outcome": "notify",
            "label": "Owner",
            "destination": "agent://owner",
        }],
    ))
    review = (await dispatch(server, "review_insight_card", {
        "card_id": response["card"]["id"],
    }))['review']
    assert windows_blocker(review) is None
    assert any("undeclared" in warning for warning in review["warnings"])
    assert (await dispatch(server, "approve_insight_card", {
        "card_id": response["card"]["id"],
    }))['status'] == "approved"


async def test_owner_can_confirm_undeclared_window_for_fixed_automatic_route(tmp_path):
    server = make_server(tmp_path, catalog=catalog_with_windows([]))
    response = await dispatch(server, "onboard_insight_card", arguments(
        "onboard_insight_card",
        decision_guidance="Notify the owner only when the selected comparison is materially abnormal.",
        delivery_methods=[{
            "key": "owner",
            "outcome": "notify",
            "label": "Owner",
            "destination": "agent://owner",
        }],
    ))
    card_id = response["card"]["id"]
    review = (await dispatch(server, "review_insight_card", {"card_id": card_id}))["review"]
    assert windows_blocker(review)["severity"] == "block"
    approval = await dispatch(server, "approve_insight_card", {
        "card_id": card_id,
        "source_selection_fingerprint": review["source_selection_fingerprint"],
        "source_selection_reason": (
            "The owner reviewed the fixed source and explicitly accepts previous_period "
            "as the source's comparison contract; runtime evidence must still support it."
        ),
    })
    assert approval["status"] == "approved"
    assert approval["onboarding_review"]["confirmed_blocker_codes"] == [
        "comparison-window-mismatch"
    ]


@pytest.mark.parametrize("name", ["propose_insight_card", "onboard_insight_card"])
async def test_selected_source_cannot_inject_comparison_windows(tmp_path, name):
    server = make_server(tmp_path, catalog=catalog_with_windows([]))
    args = arguments(name)
    args["selected_sources"][0]["available_comparison_windows"] = ["caller-injected"]
    with pytest.raises(Exception, match="available_comparison_windows"):
        await dispatch(server, name, args)


@pytest.mark.parametrize("name", ["propose_insight_card", "onboard_insight_card"])
async def test_automatic_selection_resolves_without_inspecting_snapshots(tmp_path, name):
    catalog = catalog_with_windows([CUSTOM])

    async def unexpected_inspection(source):
        pytest.fail("Authoring must use the descriptor, not inspect a source snapshot")

    catalog.inspect = unexpected_inspection
    server = make_server(tmp_path, catalog=catalog)
    args = arguments(name)
    args.pop("selected_sources")
    response = await dispatch(server, name, args)
    assert response["card"]["comparison_windows"] == [CUSTOM]


async def test_undeclared_required_context_does_not_erase_known_defaults(tmp_path):
    server = make_server(tmp_path, catalog=catalog_with_windows([CUSTOM]))
    args = arguments("draft_insight_card")
    args["sources"].append({
        "key": "context", "adapter": "superset", "resource": "dashboard:8", "label": "Context",
    })
    response = await dispatch(server, "draft_insight_card", args)
    assert response["card"]["comparison_windows"] == [CUSTOM]
    review = (await dispatch(server, "review_insight_card", {"card_id": response["card"]["id"]}))["review"]
    assert windows_blocker(review) is None
    assert any("undeclared" in w and "superset|dashboard:8" in w for w in review["warnings"])


async def test_declaration_change_invalidates_review_confirmation(tmp_path):
    catalog = catalog_with_windows()
    server = make_server(tmp_path, catalog=catalog)
    card_id = (await dispatch(server, "draft_insight_card", arguments("draft_insight_card")))["card"]["id"]
    review = (await dispatch(server, "review_insight_card", {"card_id": card_id}))["review"]
    catalog.resources[0].contract.available_comparison_windows.append(CUSTOM)
    before = tool(server, "get_insight_card")(card_id)
    with pytest.raises(Exception, match="stale or missing"):
        await dispatch(server, "approve_insight_card", {
            "card_id": card_id, "source_selection_fingerprint": review["source_selection_fingerprint"],
            "source_selection_reason": "Confirm selected source.",
        })
    assert tool(server, "get_insight_card")(card_id) == before


async def test_reauthorized_anchor_outside_bounded_discovery_retains_windows(tmp_path):
    catalog = BoundedAnchorCatalogDouble()
    catalog.resources[-1].contract.available_comparison_windows = [CUSTOM]
    server = make_server(tmp_path, ExplicitAnchorJevDouble(), catalog=catalog)
    args = arguments("draft_insight_card")
    args["sources"][0]["resource"] = "dashboard:42"
    card_id = (await dispatch(server, "draft_insight_card", args))["card"]["id"]
    review = (await dispatch(server, "review_insight_card", {"card_id": card_id, "limit": 1}))["review"]
    selected = next(c for c in review["source_candidates"] if c["selected"])
    assert "authorized-revalidation" in selected["retrieval_signals"]
    assert selected["available_comparison_windows"] == [CUSTOM]
    assert windows_blocker(review) is None


@pytest.mark.parametrize("windows", [[], ["outside-card"]])
async def test_cached_plan_windows_cannot_bypass_model_or_review(tmp_path, windows, monkeypatch):
    server = make_server(tmp_path, catalog=catalog_with_windows())
    card_id = (await dispatch(server, "draft_insight_card", arguments("draft_insight_card")))["card"]["id"]
    card = server._test_runtime.card_store.get_card(card_id)
    plan = base_plan(card).model_copy(update={"comparison_windows": windows})
    tampered = card.model_copy(update={"compiled_plan": plan})
    compile_plan = AsyncMock(side_effect=AssertionError("Invalid cache must fail before Jev compilation"))
    monkeypatch.setattr(server._test_runtime.engine.judger, "compile_plan", compile_plan)
    with pytest.raises(ValueError, match="compiled_plan comparison windows must be a nonempty subset of card windows"):
        await server._test_runtime.engine.compile(tampered)
    compile_plan.assert_not_called()
    with pytest.raises(ValidationError, match="comparison_windows|comparison windows"):
        InsightCard.model_validate(tampered.model_dump())
    authoring = InsightAuthoringService(server._test_runtime.sources, server._test_runtime.engine)
    discovery = await authoring.discover("Checkout conversion")
    review = authoring.build_onboarding_review(tampered, discovery).model_dump(mode="json")
    assert windows_blocker(review)["severity"] == "block"


def test_declaration_validation_and_exact_runtime_matching():
    contract = ResourceContract(available_comparison_windows=[CUSTOM])
    assert ResourceContract.model_validate_json(contract.model_dump_json()) == contract
    for invalid in [[""], ["  "], ["x"] * 21]:
        with pytest.raises(ValidationError):
            ResourceContract(available_comparison_windows=invalid)
    source = SourceRef(key="metric", adapter="test", resource="opaque", label="Metric")
    with pytest.raises(ValueError, match="nonempty"):
        resolve_comparison_windows([], [source], {})
    measured = comparison(comparison_window=CUSTOM)
    assert analyze_comparison("metric", measured, comparison_window=CUSTOM).status == "complete"
    assert analyze_comparison("metric", measured, comparison_window="previous_period").status == "insufficient_data"
    incomplete = measured.model_copy(update={"coverage": "partial"})
    assert analyze_comparison("metric", incomplete, comparison_window=CUSTOM).status == "insufficient_data"
