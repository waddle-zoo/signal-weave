"""Acceptance regressions for stable onboarding source confirmation."""

import pytest
from test_onboarding import SupersetCatalogDouble, make_server, tool

from signalweave.models import ResourceDescriptor


class BoundaryRankingJev:
    """Change only confidence/order between the two native review calls."""

    name = "jev-boundary-stability-test"

    def __init__(self):
        self.reordered = False
        self.rank_calls = 0

    async def rank_resources(self, goal, resources):
        del goal
        self.rank_calls += 1
        scores = {f"dashboard:{number}": 0.90 - number / 100 for number in range(7, 18)}
        if self.reordered:
            scores["dashboard:17"] = 0.99
        return {
            f"{resource.adapter}|{resource.resource}": scores[resource.resource]
            for resource in resources
        }

    async def classify_resource_roles(self, goal, resources):
        del goal
        return {
            f"{resource.adapter}|{resource.resource}": {
                "role": "primary", "probability": 0.9,
            }
            for resource in resources
        }

    async def compile_plan(self, state, card):
        del state
        return {"capabilities": ["percent_change"], "baseline": card.comparison_windows[0]}


class BoundaryCatalog(SupersetCatalogDouble):
    def __init__(self):
        super().__init__()
        self.resources.extend(
            ResourceDescriptor(
                adapter="superset",
                resource=f"dashboard:{number}",
                kind="dashboard",
                title=f"Checkout operations {number}",
                description="Checkout conversion and growth health evidence.",
            )
            for number in range(10, 18)
        )


@pytest.mark.asyncio
async def test_review_approval_ignores_boundary_reranking(tmp_path):
    """Reranking an omitted candidate must not stale selected-source approval."""
    judger = BoundaryRankingJev()
    server = make_server(tmp_path, judger=judger, catalog=BoundaryCatalog())
    draft = await tool(server, "draft_insight_card")(
        title="Checkout conversion watch",
        what_to_watch="Checkout conversion for completed sessions.",
        why_watch="Decide whether Growth needs to respond.",
        watch_for=["Conversion drops materially."],
        decision_guidance="Ignore ordinary variation; notify Growth on a material drop.",
        sources=[{
            "key": "growth",
            "adapter": "superset",
            "resource": "dashboard:7",
            "label": "Growth overview",
        }],
        retrieval_mode="fixed",
        investigation_mode="none",
    )
    card_id = draft["card"]["id"]

    first = (await tool(server, "review_insight_card")(card_id))["review"]
    first_fingerprint = first["source_selection_fingerprint"]
    assert first_fingerprint
    assert "superset|dashboard:7" in first["selected_source_refs"]

    # The selected card source and its adapter evidence are unchanged. Only a
    # nonmaterial Jev score moves another candidate into the bounded top ten.
    judger.reordered = True

    approved = await tool(server, "approve_insight_card")(
        card_id,
        source_selection_fingerprint=first_fingerprint,
        source_selection_reason=(
            "Keep the selected completed-session checkout source; the ranking change "
            "does not alter the card's business evidence."
        ),
    )
    assert approved["status"] == "approved"
    assert judger.rank_calls == 2, (
        "approval did not perform its second native review; "
        f"returned fingerprint={first_fingerprint!r}"
    )


@pytest.mark.asyncio
async def test_proposal_retains_authorized_selected_ref_below_top_k(tmp_path):
    judger = BoundaryRankingJev()
    server = make_server(tmp_path, judger=judger, catalog=BoundaryCatalog())

    proposal = await tool(server, "propose_insight_card")(
        what_to_watch="Checkout conversion for completed sessions.",
        why_watch="Decide whether Growth needs to respond.",
        watch_for=["Conversion drops materially."],
        decision_guidance="Ignore ordinary variation; notify Growth on a material drop.",
        selected_sources=[{"ref": "superset|dashboard:17"}],
        limit=1,
    )

    card = proposal["proposal"]["card"]
    assert card["sources"][0]["resource"] == "dashboard:17"
    assert proposal["proposal"]["onboarding_review"]["selected_source_refs"] == [
        "superset|dashboard:17"
    ]
    assert judger.rank_calls == 1


@pytest.mark.asyncio
async def test_malformed_selected_ref_is_rejected_before_jev(tmp_path):
    judger = BoundaryRankingJev()
    server = make_server(tmp_path, judger=judger, catalog=BoundaryCatalog())

    with pytest.raises(ValueError, match=r"selected_sources\[0\]\.ref"):
        await tool(server, "propose_insight_card")(
            what_to_watch="Checkout conversion.",
            why_watch="Decide whether Growth should respond.",
            selected_sources=[{"ref": "dashboard:17"}],
        )

    assert judger.rank_calls == 0
    assert server._test_runtime.card_store.list_cards() == []

@pytest.mark.asyncio
async def test_off_top_k_selected_ref_cannot_bypass_catalog_acl(tmp_path):
    catalog = BoundaryCatalog()
    resource = next(item for item in catalog.resources if item.resource == "dashboard:17")
    catalog.resources[catalog.resources.index(resource)] = resource.model_copy(update={
        "contract": resource.contract.model_copy(update={"authorized": False}),
    })
    judger = BoundaryRankingJev()
    server = make_server(tmp_path, judger=judger, catalog=catalog)

    with pytest.raises(ValueError, match="authorized adapter catalog"):
        await tool(server, "propose_insight_card")(
            what_to_watch="Checkout conversion.",
            why_watch="Decide whether Growth should respond.",
            selected_sources=[{"ref": "superset|dashboard:17"}],
            limit=1,
        )

    assert judger.rank_calls == 0
    assert server._test_runtime.card_store.list_cards() == []


@pytest.mark.asyncio
async def test_selected_source_rejects_unknown_fields_before_jev(tmp_path):
    judger = BoundaryRankingJev()
    server = make_server(tmp_path, judger=judger, catalog=BoundaryCatalog())

    with pytest.raises(ValueError, match=r"selected_sources\[0\]\.unexpected"):
        await tool(server, "propose_insight_card")(
            what_to_watch="Checkout conversion.",
            why_watch="Decide whether Growth should respond.",
            selected_sources=[
                {"ref": "superset|dashboard:17", "unexpected": "ignored?"}
            ],
        )

    assert judger.rank_calls == 0
    assert server._test_runtime.card_store.list_cards() == []
