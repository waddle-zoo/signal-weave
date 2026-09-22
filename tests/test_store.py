import json

from signalweave.models import (
    CertificationRecord,
    DecisionReceipt,
    InsightCard,
    Outcome,
    ReceiptStatus,
    SourceRef,
)
from signalweave.store import (
    JsonInsightCardStore,
    SQLiteCertificationReportStore,
    SQLiteDecisionReceiptStore,
    SQLiteInsightCardStore,
    SQLiteMetricQueryCardStore,
)


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


def test_sqlite_card_store_survives_a_new_store_instance(tmp_path):
    path = tmp_path / "signalweave.db"
    card = InsightCard(
        id="card-sqlite",
        title="Sales pulse",
        what_to_watch="Sales movement.",
        why_watch="Decide whether Sales should act.",
    )

    SQLiteInsightCardStore(path).save_card(card)

    reopened = SQLiteInsightCardStore(path)
    assert reopened.get_card(card.id).title == "Sales pulse"
    assert reopened.list_cards()[0].id == card.id


def test_sqlite_receipt_claim_is_atomic_across_store_instances(tmp_path):
    path = tmp_path / "signalweave.db"
    first = SQLiteDecisionReceiptStore(path)
    second = SQLiteDecisionReceiptStore(path)
    receipt = DecisionReceipt(
        receipt_id="receipt-1",
        idempotency_key="daily:1",
        card_id="card-1",
        card_version=1,
        actor="scheduler",
        status=ReceiptStatus.PREPARED,
    )

    assert first.claim(receipt) is True
    assert second.claim(receipt.model_copy(update={"receipt_id": "receipt-2"})) is False

    completed = receipt.model_copy(
        update={"status": ReceiptStatus.DELIVERY_DISABLED, "outcome": Outcome.IGNORE}
    )
    first.save(completed)
    assert second.get_by_idempotency_key("daily:1").status == ReceiptStatus.DELIVERY_DISABLED


def test_sqlite_metric_query_store_survives_a_new_store_instance(tmp_path):
    from signalweave.models import MetricQueryCard

    path = tmp_path / "signalweave.db"
    card = MetricQueryCard(
        id="metric-signups",
        title="Monthly signups",
        question="How many signups did we have by month?",
        why="Track growth performance.",
    )

    SQLiteMetricQueryCardStore(path).save_card(card)

    reopened = SQLiteMetricQueryCardStore(path)
    assert reopened.get_card(card.id).question == card.question


def test_sqlite_certification_report_store_is_durable_and_append_only(tmp_path):
    path = tmp_path / "signalweave.db"
    record = CertificationRecord(
        report_id="card_workflow:orders:run-1",
        kind="card_workflow",
        subject_id="orders",
        subject_version="3",
        status="approved",
        dataset_ids=["northstar-holdout-v1"],
        input_digest="input-digest",
        label_digest="label-digest",
        report={"outcome_accuracy": 1.0},
    )

    SQLiteCertificationReportStore(path).save(record)
    reopened = SQLiteCertificationReportStore(path)

    assert reopened.get(record.report_id).report["outcome_accuracy"] == 1.0
    assert reopened.list(subject_id="orders")[0].dataset_ids == ["northstar-holdout-v1"]
