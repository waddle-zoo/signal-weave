from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from .models import InsightCard, InsightCardStatus


class InsightCardStore(Protocol):
    def get_card(self, card_id: str) -> InsightCard: ...

    def list_cards(self) -> list[InsightCard]: ...

    def save_card(self, card: InsightCard) -> None: ...

    def set_card_status(self, card_id: str, status: InsightCardStatus) -> InsightCard: ...


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
