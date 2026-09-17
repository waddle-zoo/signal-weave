import json

from signalweave.models import InsightCard, SourceRef
from signalweave.store import JsonInsightCardStore


def test_insight_card_store_writes_valid_catalog_atomically(tmp_path):
    path = tmp_path / "cards.json"
    store = JsonInsightCardStore(path)
    card = InsightCard(
        id="card-1",
        title="Sales pulse",
        what_to_watch="Sales movement.",
        why_watch="Decide whether Sales should act.",
        sources=[
            SourceRef(
                key="sales",
                adapter="superset",
                resource="dashboard:1",
                label="Sales dashboard",
            )
        ],
    )

    store.save_card(card)

    assert json.loads(path.read_text())["card-1"]["title"] == "Sales pulse"
    assert store.get_card("card-1").what_to_watch == "Sales movement."
    assert store.list_cards()[0].id == "card-1"
    assert list(tmp_path.glob("*.tmp")) == []
