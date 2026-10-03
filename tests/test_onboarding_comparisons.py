import pytest
from pydantic import ValidationError

from signalweave.models import ResourceContract
from signalweave.store import SQLiteInsightCardStore
from tests.test_onboarding import BundleJevDouble, SupersetCatalogDouble, make_server, tool


@pytest.mark.parametrize("explicit_selection", [False, True])
async def test_onboarding_persists_reviewed_catalog_comparison_keys(tmp_path, explicit_selection):
    catalog = SupersetCatalogDouble()
    expected = ["activity-breakdown", "rate-breakdown"]
    catalog.resources[0].contract = ResourceContract(required_comparison_keys=expected)
    server = make_server(tmp_path, catalog=catalog, sqlite=True)
    response = await tool(server, "onboard_insight_card")(
        what_to_watch="Checkout conversion and revenue changes.",
        why_watch="Understand the measured movement.",
        # Caller fields cannot clear or replace the reviewed catalog obligations.
        selected_sources=[{
            "ref": "superset|dashboard:7",
        }] if explicit_selection else None,
        delivery_methods=[{
            "key": "owner", "outcome": "notify", "label": "Owner", "destination": "agent://owner",
        }],
        retrieval_mode="fixed",
    )
    assert response["card"]["sources"][0]["required_comparison_keys"] == expected
    assert response["card"]["status"] == "draft"
    stored = SQLiteInsightCardStore(tmp_path / "signalweave.db").get_card(response["card"]["id"])
    assert stored.sources[0].required_comparison_keys == expected

    # These obligations survive restart and cannot disappear with a later catalog edit.
    catalog.resources[0].contract.required_comparison_keys.clear()
    assert stored.sources[0].required_comparison_keys == expected
    preview = await tool(server, "simulate_insight_card")(stored.id)
    assert preview["card"]["sources"][0]["required_comparison_keys"] == expected
    # The source returns a valid observation but omits both required comparisons.
    assert preview["result"]["outcome"] == "insufficient_data"


async def test_legacy_catalog_does_not_infer_requirements_from_snapshot_or_caller(tmp_path):
    catalog = SupersetCatalogDouble()
    original_inspect = catalog.inspect

    async def inspect(source):
        snapshot = await original_inspect(source)
        snapshot.contract = ResourceContract(required_comparison_keys=["snapshot-injected"])
        return snapshot

    catalog.inspect = inspect
    server = make_server(tmp_path, catalog=catalog)
    response = await tool(server, "onboard_insight_card")(
        what_to_watch="Checkout conversion changes.",
        why_watch="Review the measured movement.",
        selected_sources=[{
            "ref": "superset|dashboard:7",
        }],
        retrieval_mode="fixed",
    )
    source = response["card"]["sources"][0]
    assert source["required_comparison_keys"] == []
    preview = await tool(server, "simulate_insight_card")(response["card"]["id"])
    assert preview["card"]["sources"][0]["required_comparison_keys"] == []
    assert preview["result"]["outcome"] != "insufficient_data"


async def test_related_source_keeps_catalog_keys_without_becoming_required(tmp_path):
    catalog = SupersetCatalogDouble()
    catalog.resources[0].contract = ResourceContract(required_comparison_keys=["new-catalog-key"])
    catalog.resources[1].contract = ResourceContract(required_comparison_keys=["related-breakdown"])
    server = make_server(tmp_path, BundleJevDouble(), catalog=catalog)
    drafted = await tool(server, "draft_insight_card")(
        title="Growth with finance context",
        what_to_watch="Checkout conversion and related finance signals.",
        why_watch="Understand the measured movement.",
        sources=[{
            "key": "anchor", "adapter": "superset", "resource": "dashboard:7",
            "label": "Growth", "required_comparison_keys": ["reviewed-anchor-key"],
        }],
        retrieval_mode="expand",
    )
    resolved = await tool(server, "resolve_insight_sources")(drafted["card"]["id"])
    anchor, related = resolved["bundle"]["selected_sources"]
    assert anchor["required_comparison_keys"] == ["reviewed-anchor-key"]
    assert related["required_comparison_keys"] == ["related-breakdown"]
    assert related["required"] is False


def test_catalog_comparison_keys_are_optional_bounded_and_serialize():
    assert ResourceContract().required_comparison_keys == []
    contract = ResourceContract(required_comparison_keys=["activity-breakdown"])
    assert ResourceContract.model_validate_json(contract.model_dump_json()) == contract
    with pytest.raises(ValidationError):
        ResourceContract(required_comparison_keys=[f"comparison-{index}" for index in range(21)])


async def test_selected_source_cannot_inject_comparison_requirements(tmp_path):
    server = make_server(tmp_path)
    with pytest.raises(Exception, match="required_comparison_keys"):
        await tool(server, "onboard_insight_card")(
            what_to_watch="Checkout conversion changes.",
            why_watch="Review the measured movement.",
            selected_sources=[{
                "ref": "superset|dashboard:7",
                "required_comparison_keys": ["caller-injected"],
            }],
            retrieval_mode="fixed",
        )
