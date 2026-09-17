"""Optional embedding-plus-reasoning baseline for apples-to-apples evaluation.

The adapter speaks the common OpenAI-compatible ``/embeddings`` and
``/chat/completions`` shape. It is deliberately not part of the product runtime:
it exists so a team can compare Jev with the model and provider it already uses,
using the same normalized dashboard state and safety gates.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .compiler import base_plan
from .models import Decision, MonitorCard, MonitorPlan, Observation, Outcome
from .typesafe_adapter import JudgerMetrics


class EmbeddingReasoningJudger:
    """Retrieve dashboard evidence with embeddings, then ask a model for JSON."""

    name = "embedding-reasoning"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        embedding_model: str,
        api_key: str | None = None,
        top_k: int = 8,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("BASELINE_BASE_URL is required for embedding-reasoning mode")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.embedding_model = embedding_model
        self.api_key = api_key
        self.top_k = max(1, min(top_k, 32))
        self.timeout = timeout
        self.transport = transport
        self.metrics = JudgerMetrics()

    async def compile_plan(self, state: dict[str, Any], card: MonitorCard) -> dict[str, Any]:
        """Hold plan compilation constant so the comparison isolates judgment quality."""
        plan = base_plan(card)
        return {"operations": plan.operations, "baseline": plan.comparison_windows[0]}

    async def judge(
        self,
        state: dict[str, Any],
        card: MonitorCard,
        plan: MonitorPlan,
        observations: list[Observation],
    ) -> Decision:
        documents = [self._document(observation) for observation in observations]
        query = card.intent
        ranked = await self._rank(query, documents)
        retrieved = [documents[index] for index in ranked[: self.top_k]]
        payload = {
            "monitor_intent": card.intent,
            "allowed_outcomes": [outcome.value for outcome in card.allowed_outcomes],
            "approved_recipients": [recipient.key for recipient in card.recipients],
            "retrieved_dashboard_cards": retrieved,
            "evidence": state["evidence"],
        }
        result = await self._reason(payload)
        try:
            outcome = Outcome(result["outcome"])
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError("baseline response must contain a valid outcome") from error
        if outcome not in card.allowed_outcomes:
            outcome = Outcome.INVESTIGATE
        confidence = result.get("confidence")
        if confidence is not None:
            confidence = max(0.0, min(float(confidence), 1.0))
        probabilities = result.get("probabilities") or {outcome.value: confidence or 0.0}
        return Decision(
            outcome=outcome,
            recipient_key=result.get("recipient_key"),
            rationale=str(result.get("rationale") or "Embedding-plus-reasoning baseline decision."),
            confidence=confidence,
            probabilities={str(key): float(value) for key, value in probabilities.items()},
            evidence=state["evidence"],
            observations=observations,
            monitor_id=card.id,
            dashboard_id=card.dashboard_id,
            evaluator=self.name,
        )

    @staticmethod
    def _document(observation: Observation) -> dict[str, Any]:
        return {
            "chart_id": observation.chart_id,
            "chart_title": observation.chart_title,
            "metric": observation.metric,
            "unit": observation.unit,
            "current": observation.current,
            "baseline": observation.baseline,
            "previous": observation.previous,
            "change_pct": observation.change_pct,
            "dimensions": observation.dimensions,
            "freshness": observation.freshness,
        }

    async def _rank(self, query: str, documents: list[dict[str, Any]]) -> list[int]:
        if not documents:
            return []
        texts = [query] + [self._text(document) for document in documents]
        body = await self._post("/embeddings", {"model": self.embedding_model, "input": texts})
        vectors = [item["embedding"] for item in sorted(body["data"], key=lambda item: item["index"])]
        query_vector = vectors[0]
        scores = [(self._cosine(query_vector, vector), index) for index, vector in enumerate(vectors[1:])]
        return [index for _score, index in sorted(scores, reverse=True)]

    async def _reason(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = await self._post(
            "/chat/completions",
            {
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Classify a monitoring event. Return JSON only with keys "
                            "outcome, recipient_key, rationale, confidence, probabilities. "
                            "Use only allowed outcomes and approved recipients. "
                            "Never invent evidence or recipients."
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("baseline response content must be a JSON string")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start, end = content.find("{"), content.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("baseline response was not valid JSON") from None
            return json.loads(content[start : end + 1])

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.post(self.base_url + path, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage", {})
        self.metrics.requests += 1
        self.metrics.record_tokens(usage.get("prompt_tokens"), usage.get("completion_tokens"))
        return body

    @staticmethod
    def _text(document: dict[str, Any]) -> str:
        return " ".join(
            str(document.get(key) or "")
            for key in ("chart_title", "metric", "unit", "freshness", "dimensions")
        )

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = sum(value * value for value in left) ** 0.5
        right_norm = sum(value * value for value in right) ** 0.5
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
