"""A caller-supplied anchor does not prove a frontier-agent discovery event."""

from tests.test_onboarding import NoResourceRankingJudger, SupersetCatalogDouble, make_server, tool


async def test_direct_caller_selection_records_catalog_validation_not_agent_inspection(tmp_path):
    class CatalogWithoutInspection(SupersetCatalogDouble):
        async def inspect(self, source):
            raise AssertionError("Explicit draft setup unexpectedly inspected source data")

    server = make_server(tmp_path, catalog=CatalogWithoutInspection(), judger=NoResourceRankingJudger())
    result = await tool(server, "onboard_insight_card")(
        what_to_watch="Explain checkout activity", why_watch="Weekly operations briefing",
        selected_sources=[{"ref": "superset|dashboard:7"}],
        watch_for=[], questions=[], delivery_methods=[], response_mode="full",
    )
    card = result["card"]
    review = result["review"]
    receipt = review["discovery_receipt"]
    assert card["status"] == "draft"
    assert [(source["adapter"], source["resource"]) for source in card["sources"]] == [("superset", "dashboard:7")]
    assert receipt["evaluator"] == "caller-source-selection"
    assert result["discovery"]["candidate_strategy"] == "caller-selected"
    assert receipt["catalog_provider"] == "authorized-adapter-catalog"
    assert receipt["candidate_refs"] == ["superset|dashboard:7"]
    selected = review["source_candidates"][0]
    assert selected["selected"] is True
    assert "prior inspection is not verified" in selected["reason"]
    assert "caller-selected" in selected["retrieval_signals"]
    assert "Exact source references were supplied by the caller; prior search, inspection and caller type are not verified." in result["discovery"]["warnings"]
