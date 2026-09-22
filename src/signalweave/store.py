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

    def claim(self, receipt: DecisionReceipt) -> bool: ...

    def save(self, receipt: DecisionReceipt) -> None: ...


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
