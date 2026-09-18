from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from .models import (
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

    def save(self, receipt: DecisionReceipt) -> None: ...


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
    """Safe default for tests; production runtimes use the durable JSON store."""

    def __init__(self) -> None:
        self._receipts: dict[str, DecisionReceipt] = {}

    def get_by_idempotency_key(self, key: str) -> DecisionReceipt | None:
        return self._receipts.get(key)

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
