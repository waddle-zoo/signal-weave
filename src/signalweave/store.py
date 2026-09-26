from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import Protocol

from .models import (
    CertificationRecord,
    DecisionFeedback,
    DecisionReceipt,
    InsightCard,
    InsightCardStatus,
    MetricQueryCard,
    QueryCardStatus,
)


class InsightCardStore(Protocol):
    def get_card(self, card_id: str) -> InsightCard: ...

    def list_cards(self) -> list[InsightCard]: ...

    def save_card(self, card: InsightCard) -> None: ...

    def set_card_status(self, card_id: str, status: InsightCardStatus) -> InsightCard: ...


class MetricQueryCardStore(Protocol):
    def get_card(self, card_id: str) -> MetricQueryCard: ...

    def list_cards(self) -> list[MetricQueryCard]: ...

    def save_card(self, card: MetricQueryCard) -> None: ...

    def set_card_status(self, card_id: str, status: QueryCardStatus) -> MetricQueryCard: ...


class DecisionReceiptStore(Protocol):
    def get_by_idempotency_key(self, key: str) -> DecisionReceipt | None: ...

    def get_by_receipt_id(self, receipt_id: str) -> DecisionReceipt | None: ...

    def claim(self, receipt: DecisionReceipt) -> bool: ...

    def save(self, receipt: DecisionReceipt) -> None: ...


class DecisionFeedbackStore(Protocol):
    def get(self, feedback_id: str) -> DecisionFeedback | None: ...

    def save(self, feedback: DecisionFeedback) -> None: ...

    def list(
        self,
        *,
        card_id: str | None = None,
        receipt_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> list[DecisionFeedback]: ...


class InMemoryDecisionFeedbackStore:
    """Test and embedded-runtime implementation for append-only feedback."""

    def __init__(self) -> None:
        self._feedback: dict[str, DecisionFeedback] = {}

    def save(self, feedback: DecisionFeedback) -> None:
        existing = self._feedback.get(feedback.feedback_id)
        if existing is not None and existing != feedback:
            raise ValueError(f"decision feedback already exists: {feedback.feedback_id}")
        self._feedback[feedback.feedback_id] = feedback

    def get(self, feedback_id: str) -> DecisionFeedback | None:
        return self._feedback.get(feedback_id)

    def list(
        self,
        *,
        card_id: str | None = None,
        receipt_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> list[DecisionFeedback]:
        return [
            item
            for item in self._feedback.values()
            if (card_id is None or item.card_id == card_id)
            and (receipt_id is None or item.receipt_id == receipt_id)
            and (idempotency_key is None or item.idempotency_key == idempotency_key)
        ]


class JsonDecisionFeedbackStore:
    """Atomic JSON store for local shadow feedback fixtures."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, feedback: DecisionFeedback) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        records = self._load()
        payload = feedback.model_dump(mode="json")
        existing = records.get(feedback.feedback_id)
        if existing is not None and existing != payload:
            raise ValueError(f"decision feedback already exists: {feedback.feedback_id}")
        records[feedback.feedback_id] = payload
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = temporary.name
                temporary.write(json.dumps(records, indent=2) + "\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def get(self, feedback_id: str) -> DecisionFeedback | None:
        item = self._load().get(feedback_id)
        return DecisionFeedback.model_validate(item) if item is not None else None

    def list(
        self,
        *,
        card_id: str | None = None,
        receipt_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> list[DecisionFeedback]:
        items = [DecisionFeedback.model_validate(item) for item in self._load().values()]
        return [
            item
            for item in items
            if (card_id is None or item.card_id == card_id)
            and (receipt_id is None or item.receipt_id == receipt_id)
            and (idempotency_key is None or item.idempotency_key == idempotency_key)
        ]

    def _load(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"Decision feedback catalog must contain a JSON object: {self.path}")
        return payload


class CertificationReportStore(Protocol):
    """Durable append-only lookup for bootstrap and evaluation evidence."""

    def save(self, record: CertificationRecord) -> None: ...

    def get(self, report_id: str) -> CertificationRecord: ...

    def list(self, *, subject_id: str | None = None) -> list[CertificationRecord]: ...


class InMemoryCertificationReportStore:
    """Test and embedded-runtime implementation of the certification store."""

    def __init__(self) -> None:
        self._records: dict[str, CertificationRecord] = {}

    def save(self, record: CertificationRecord) -> None:
        existing = self._records.get(record.report_id)
        if existing is not None and existing != record:
            raise ValueError(f"certification report already exists: {record.report_id}")
        self._records[record.report_id] = record

    def get(self, report_id: str) -> CertificationRecord:
        try:
            return self._records[report_id]
        except KeyError as error:
            raise KeyError(f"Unknown certification report: {report_id}") from error

    def list(self, *, subject_id: str | None = None) -> list[CertificationRecord]:
        return [
            record
            for record in self._records.values()
            if subject_id is None or record.subject_id == subject_id
        ]


class JsonInsightCardStore:
    """Small atomic catalog for user-authored insight card contracts."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save_card(self, card: InsightCard) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        cards = self._load()
        cards[card.id] = card.model_dump(mode="json")
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = temporary.name
                temporary.write(json.dumps(cards, indent=2) + "\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def get_card(self, card_id: str) -> InsightCard:
        cards = self._load()
        if card_id not in cards:
            raise KeyError(f"Unknown insight card: {card_id}")
        return InsightCard.model_validate(cards[card_id])

    def set_card_status(self, card_id: str, status: InsightCardStatus) -> InsightCard:
        card = self.get_card(card_id)
        updated = card.model_copy(update={"status": status})
        self.save_card(updated)
        return updated

    def list_cards(self) -> list[InsightCard]:
        return [InsightCard.model_validate(item) for item in self._load().values()]

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"Insight card catalog must contain a JSON object: {self.path}")
        return payload


class JsonMetricQueryCardStore:
    """Atomic JSON catalog for plain-language metric query cards."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save_card(self, card: MetricQueryCard) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        cards = self._load()
        cards[card.id] = card.model_dump(mode="json")
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = temporary.name
                temporary.write(json.dumps(cards, indent=2) + "\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def get_card(self, card_id: str) -> MetricQueryCard:
        cards = self._load()
        if card_id not in cards:
            raise KeyError(f"Unknown metric query card: {card_id}")
        return MetricQueryCard.model_validate(cards[card_id])

    def set_card_status(self, card_id: str, status: QueryCardStatus) -> MetricQueryCard:
        card = self.get_card(card_id)
        updated = card.model_copy(update={"status": status})
        self.save_card(updated)
        return updated

    def list_cards(self) -> list[MetricQueryCard]:
        return [MetricQueryCard.model_validate(item) for item in self._load().values()]

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"Metric query card catalog must contain a JSON object: {self.path}")
        return payload


class InMemoryDecisionReceiptStore:
    """Safe default for tests; production runtimes use the durable SQLite store."""

    def __init__(self) -> None:
        self._receipts: dict[str, DecisionReceipt] = {}
        self._lock = threading.Lock()

    def get_by_idempotency_key(self, key: str) -> DecisionReceipt | None:
        return self._receipts.get(key)

    def get_by_receipt_id(self, receipt_id: str) -> DecisionReceipt | None:
        return next(
            (receipt for receipt in self._receipts.values() if receipt.receipt_id == receipt_id),
            None,
        )

    def claim(self, receipt: DecisionReceipt) -> bool:
        with self._lock:
            if receipt.idempotency_key in self._receipts:
                return False
            self._receipts[receipt.idempotency_key] = receipt
            return True

    def save(self, receipt: DecisionReceipt) -> None:
        existing = self._receipts.get(receipt.idempotency_key)
        if existing and existing.receipt_id != receipt.receipt_id:
            raise ValueError(f"idempotency key already belongs to receipt {existing.receipt_id}")
        self._receipts[receipt.idempotency_key] = receipt


class JsonDecisionReceiptStore:
    """Atomic durable decision receipts keyed by caller-supplied idempotency key."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def get_by_idempotency_key(self, key: str) -> DecisionReceipt | None:
        payload = self._load()
        item = payload.get(key)
        return DecisionReceipt.model_validate(item) if item is not None else None

    def get_by_receipt_id(self, receipt_id: str) -> DecisionReceipt | None:
        item = next(
            (payload for payload in self._load().values() if payload.get("receipt_id") == receipt_id),
            None,
        )
        return DecisionReceipt.model_validate(item) if item is not None else None

    def claim(self, receipt: DecisionReceipt) -> bool:
        # JSON remains useful for small local fixtures. Production runtimes use
        # SQLite so this insert is protected by a database uniqueness constraint.
        if self.get_by_idempotency_key(receipt.idempotency_key) is not None:
            return False
        self.save(receipt)
        return True

    def save(self, receipt: DecisionReceipt) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        receipts = self._load()
        existing = receipts.get(receipt.idempotency_key)
        if existing is not None and existing.get("receipt_id") != receipt.receipt_id:
            raise ValueError(
                f"idempotency key already belongs to receipt {existing.get('receipt_id')}"
            )
        receipts[receipt.idempotency_key] = receipt.model_dump(mode="json")
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = temporary.name
                temporary.write(json.dumps(receipts, indent=2) + "\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _load(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"Decision receipt catalog must contain a JSON object: {self.path}")
        return payload


class JsonCertificationReportStore:
    """Atomic JSON store for small local certification histories."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, record: CertificationRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        records = self._load()
        existing = records.get(record.report_id)
        if existing is not None and existing != record.model_dump(mode="json"):
            raise ValueError(f"certification report already exists: {record.report_id}")
        records[record.report_id] = record.model_dump(mode="json")
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = temporary.name
                temporary.write(json.dumps(records, indent=2) + "\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def get(self, report_id: str) -> CertificationRecord:
        item = self._load().get(report_id)
        if item is None:
            raise KeyError(f"Unknown certification report: {report_id}")
        return CertificationRecord.model_validate(item)

    def list(self, *, subject_id: str | None = None) -> list[CertificationRecord]:
        records = [CertificationRecord.model_validate(item) for item in self._load().values()]
        return [record for record in records if subject_id is None or record.subject_id == subject_id]

    def _load(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"Certification report catalog must contain a JSON object: {self.path}")
        return payload


class SQLiteInsightCardStore:
    """Durable single-file card store with transactional updates."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS insight_cards ("
                "id TEXT PRIMARY KEY, payload TEXT NOT NULL"
                ")"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def save_card(self, card: InsightCard) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO insight_cards (id, payload) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
                (card.id, json.dumps(card.model_dump(mode="json"))),
            )

    def get_card(self, card_id: str) -> InsightCard:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM insight_cards WHERE id = ?", (card_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown insight card: {card_id}")
        return InsightCard.model_validate(json.loads(row[0]))

    def set_card_status(self, card_id: str, status: InsightCardStatus) -> InsightCard:
        card = self.get_card(card_id)
        updated = card.model_copy(update={"status": status})
        self.save_card(updated)
        return updated

    def list_cards(self) -> list[InsightCard]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM insight_cards ORDER BY id"
            ).fetchall()
        return [InsightCard.model_validate(json.loads(row[0])) for row in rows]


class SQLiteMetricQueryCardStore:
    """Durable single-file store for plain-language metric query cards."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS metric_query_cards ("
                "id TEXT PRIMARY KEY, payload TEXT NOT NULL"
                ")"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def save_card(self, card: MetricQueryCard) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO metric_query_cards (id, payload) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
                (card.id, json.dumps(card.model_dump(mode="json"))),
            )

    def get_card(self, card_id: str) -> MetricQueryCard:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM metric_query_cards WHERE id = ?", (card_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown metric query card: {card_id}")
        return MetricQueryCard.model_validate(json.loads(row[0]))

    def set_card_status(self, card_id: str, status: QueryCardStatus) -> MetricQueryCard:
        card = self.get_card(card_id)
        updated = card.model_copy(update={"status": status})
        self.save_card(updated)
        return updated

    def list_cards(self) -> list[MetricQueryCard]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM metric_query_cards ORDER BY id"
            ).fetchall()
        return [MetricQueryCard.model_validate(json.loads(row[0])) for row in rows]


class SQLiteDecisionReceiptStore:
    """Durable receipt store with an atomic idempotency-key claim."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS decision_receipts ("
                "idempotency_key TEXT PRIMARY KEY, payload TEXT NOT NULL"
                ")"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def get_by_idempotency_key(self, key: str) -> DecisionReceipt | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM decision_receipts WHERE idempotency_key = ?", (key,)
            ).fetchone()
        return DecisionReceipt.model_validate(json.loads(row[0])) if row else None

    def get_by_receipt_id(self, receipt_id: str) -> DecisionReceipt | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM decision_receipts WHERE json_extract(payload, '$.receipt_id') = ?",
                (receipt_id,),
            ).fetchone()
        return DecisionReceipt.model_validate(json.loads(row[0])) if row else None

    def claim(self, receipt: DecisionReceipt) -> bool:
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO decision_receipts (idempotency_key, payload) VALUES (?, ?)",
                    (receipt.idempotency_key, json.dumps(receipt.model_dump(mode="json"))),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def save(self, receipt: DecisionReceipt) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM decision_receipts WHERE idempotency_key = ?",
                (receipt.idempotency_key,),
            ).fetchone()
            if row is not None:
                existing = DecisionReceipt.model_validate(json.loads(row[0]))
                if existing.receipt_id != receipt.receipt_id:
                    raise ValueError(
                        f"idempotency key already belongs to receipt {existing.receipt_id}"
                    )
            connection.execute(
                "INSERT INTO decision_receipts (idempotency_key, payload) VALUES (?, ?) "
                "ON CONFLICT(idempotency_key) DO UPDATE SET payload = excluded.payload",
                (receipt.idempotency_key, json.dumps(receipt.model_dump(mode="json"))),
            )


class SQLiteDecisionFeedbackStore:
    """Durable append-only feedback store sharing the runtime SQLite database."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS decision_feedback ("
                "feedback_id TEXT PRIMARY KEY, payload TEXT NOT NULL"
                ")"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def save(self, feedback: DecisionFeedback) -> None:
        payload = json.dumps(feedback.model_dump(mode="json"), sort_keys=True)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM decision_feedback WHERE feedback_id = ?",
                (feedback.feedback_id,),
            ).fetchone()
            if row is not None and row[0] != payload:
                raise ValueError(f"decision feedback already exists: {feedback.feedback_id}")
            connection.execute(
                "INSERT INTO decision_feedback (feedback_id, payload) VALUES (?, ?) "
                "ON CONFLICT(feedback_id) DO UPDATE SET payload = excluded.payload",
                (feedback.feedback_id, payload),
            )

    def get(self, feedback_id: str) -> DecisionFeedback | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM decision_feedback WHERE feedback_id = ?",
                (feedback_id,),
            ).fetchone()
        return DecisionFeedback.model_validate(json.loads(row[0])) if row else None

    def list(
        self,
        *,
        card_id: str | None = None,
        receipt_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> list[DecisionFeedback]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM decision_feedback ORDER BY feedback_id"
            ).fetchall()
        items = [DecisionFeedback.model_validate(json.loads(row[0])) for row in rows]
        return [
            item
            for item in items
            if (card_id is None or item.card_id == card_id)
            and (receipt_id is None or item.receipt_id == receipt_id)
            and (idempotency_key is None or item.idempotency_key == idempotency_key)
        ]


class SQLiteCertificationReportStore:
    """Durable append-only SQLite store for certification evidence."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS certification_reports ("
                "report_id TEXT PRIMARY KEY, payload TEXT NOT NULL"
                ")"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def save(self, record: CertificationRecord) -> None:
        payload = json.dumps(record.model_dump(mode="json"), sort_keys=True)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM certification_reports WHERE report_id = ?",
                (record.report_id,),
            ).fetchone()
            if row is not None and row[0] != payload:
                raise ValueError(f"certification report already exists: {record.report_id}")
            connection.execute(
                "INSERT INTO certification_reports (report_id, payload) VALUES (?, ?) "
                "ON CONFLICT(report_id) DO UPDATE SET payload = excluded.payload",
                (record.report_id, payload),
            )

    def get(self, report_id: str) -> CertificationRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM certification_reports WHERE report_id = ?", (report_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown certification report: {report_id}")
        return CertificationRecord.model_validate(json.loads(row[0]))

    def list(self, *, subject_id: str | None = None) -> list[CertificationRecord]:
        with self._connect() as connection:
            if subject_id is None:
                rows = connection.execute(
                    "SELECT payload FROM certification_reports ORDER BY report_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT payload FROM certification_reports "
                    "WHERE json_extract(payload, '$.subject_id') = ? ORDER BY report_id",
                    (subject_id,),
                ).fetchall()
        return [CertificationRecord.model_validate(json.loads(row[0])) for row in rows]
