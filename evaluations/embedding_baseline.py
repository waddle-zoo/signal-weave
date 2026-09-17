"""Optional embedding-plus-reasoning baseline for apples-to-apples evaluation.

The adapter speaks the common OpenAI-compatible ``/embeddings`` shape and either
``/chat/completions`` or ``/responses`` for the decision. It is deliberately not
part of the product runtime: it exists so a team can compare Jev with the model
and provider it already uses, using the same normalized card and source snapshots.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from signalweave.compiler import base_plan
from signalweave.models import (
    Evidence,
    InsightCard,
    InsightPlan,
    InsightResult,
    Observation,
    Outcome,
    QuestionResult,
    QuestionStatus,
    WatchResult,
    WatchStatus,
)
from signalweave.typesafe_adapter import JudgerMetrics


class EmbeddingReasoningJudger:
    """Retrieve source observations with embeddings, then ask a model for JSON."""

    name = "embedding-reasoning"
    item_threshold = 0.70

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
        responses_api: bool = False,
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
        self.responses_api = responses_api
        self.metrics = JudgerMetrics()

    async def compile_plan(
        self, state: dict[str, Any], card: InsightCard
    ) -> dict[str, Any]:
        """Hold plan compilation constant so judgment quality is isolated."""
        del state
        plan = base_plan(card)
        return {"capabilities": plan.capabilities, "baseline": plan.comparison_windows[0]}

    async def judge(
        self,
        state: dict[str, Any],
        card: InsightCard,
        plan: InsightPlan,
        observations: list[Observation],
    ) -> InsightResult:
        documents = [self._document(observation) for observation in observations]
        query = "\n".join([card.what_to_watch, card.why_watch, *card.watch_for, *card.questions])
        ranked = await self._rank(query, documents)
        retrieved_indices = ranked[: self.top_k]
        retrieved = [documents[index] for index in retrieved_indices]
        retrieved_keys = {
            (
                documents[index]["source_key"],
                documents[index]["subject_id"],
                documents[index]["metric"],
            )
            for index in retrieved_indices
        }
        retrieved_evidence = [
            item
            for item in state["evidence"]
            if "metric" not in item.get("values", {})
            or (
                item["source_key"],
                item["subject_id"],
                item.get("values", {}).get("metric"),
            )
            in retrieved_keys
        ]
        payload = {
            "card": {
                "title": card.title,
                "what_to_watch": card.what_to_watch,
                "why_watch": card.why_watch,
                "watch_for": card.watch_for,
                "questions": card.questions,
                "delivery_methods": [
                    method.model_dump(mode="json") for method in card.delivery_methods
                ],
            },
            "retrieved_observations": retrieved,
            "retrieved_evidence": retrieved_evidence,
            "retrieved_observation_count": len(retrieved),
            "total_observation_count": len(observations),
        }
        result = await self._reason(payload)
        try:
            outcome = Outcome(result["outcome"])
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError("baseline response must contain a valid outcome") from error
        available_outcomes = {
            Outcome.IGNORE,
            Outcome.INVESTIGATE,
            Outcome.INSUFFICIENT_DATA,
            *(method.outcome for method in card.delivery_methods),
        }
        if outcome not in available_outcomes:
            outcome = Outcome.INVESTIGATE
        confidence = result.get("confidence")
        if confidence is not None:
            confidence = max(0.0, min(float(confidence), 1.0))
        watch_results = self._watch_results(card, result.get("watch_results"))
        question_results = self._question_results(card, result.get("question_results"))
        return InsightResult(
            card_id=card.id,
            outcome=outcome,
            delivery_methods=[
                method for method in card.delivery_methods if method.outcome == outcome
            ],
            summary=(
                f"Embedding retrieval supplied {len(retrieved)} of {len(observations)} "
                f"observations across {len(plan.selected_source_keys)} sources; "
                f"{len(watch_results)} watch items and {len(question_results)} questions were checked."
            ),
            rationale=str(result.get("rationale") or "Embedding-plus-reasoning baseline result."),
            confidence=confidence,
            probabilities={
                str(key): max(0.0, min(1.0, float(value)))
                for key, value in (result.get("probabilities") or {}).items()
            },
            watch_results=watch_results,
            question_results=question_results,
            evidence=[Evidence.model_validate(item) for item in retrieved_evidence],
            observations=[Observation.model_validate(doc) for doc in retrieved],
            source_keys=plan.selected_source_keys,
            evaluator=self.name,
        )

    @classmethod
    def _watch_results(
        cls, card: InsightCard, raw_results: Any
    ) -> list[WatchResult]:
        by_key = {
            str(item.get("key")): item
            for item in (raw_results if isinstance(raw_results, list) else [])
            if isinstance(item, dict)
        }
        results: list[WatchResult] = []
        for index, item in enumerate(card.watch_for):
            raw_probability = by_key.get(f"watch_{index}", {}).get("probability", 0.5)
            probability = max(0.0, min(1.0, float(raw_probability)))
            status = (
                WatchStatus.PRESENT
                if probability >= cls.item_threshold
                else WatchStatus.ABSENT
                if probability <= 1 - cls.item_threshold
                else WatchStatus.UNKNOWN
            )
            results.append(
                WatchResult(
                    key=f"watch_{index}",
                    watch_for=item,
                    status=status,
                    probability=probability,
                )
            )
        return results

    @classmethod
    def _question_results(
        cls, card: InsightCard, raw_results: Any
    ) -> list[QuestionResult]:
        by_key = {
            str(item.get("key")): item
            for item in (raw_results if isinstance(raw_results, list) else [])
            if isinstance(item, dict)
        }
        results: list[QuestionResult] = []
        for index, question in enumerate(card.questions):
            raw_probability = by_key.get(f"question_{index}", {}).get("probability", 0.5)
            probability = max(0.0, min(1.0, float(raw_probability)))
            status = (
                QuestionStatus.SUPPORTED
                if probability >= cls.item_threshold
                else QuestionStatus.NOT_SUPPORTED
                if probability <= 1 - cls.item_threshold
                else QuestionStatus.UNKNOWN
            )
            results.append(
                QuestionResult(
                    key=f"question_{index}",
                    question=question,
                    status=status,
                    probability=probability,
                )
            )
        return results

    @staticmethod
    def _document(observation: Observation) -> dict[str, Any]:
        return {
            "source_key": observation.source_key,
            "subject_id": observation.subject_id,
            "subject_label": observation.subject_label,
            "subject_type": observation.subject_type,
            "metric": observation.metric,
            "unit": observation.unit,
            "current": observation.current,
            "baseline": observation.baseline,
            "previous": observation.previous,
            "change_pct": observation.change_pct,
            "comparison_baselines": observation.comparison_baselines,
            "dimensions": observation.dimensions,
            "freshness": observation.freshness,
            "attributes": observation.attributes,
        }

    async def _rank(self, query: str, documents: list[dict[str, Any]]) -> list[int]:
        if not documents:
            return []
        texts = [query] + [self._text(document) for document in documents]
        body = await self._post("/embeddings", {"model": self.embedding_model, "input": texts})
        vectors = [item["embedding"] for item in sorted(body["data"], key=lambda item: item["index"])]
        query_vector = vectors[0]
        scores = [
            (self._cosine(query_vector, vector), index)
            for index, vector in enumerate(vectors[1:])
        ]
        return [index for _score, index in sorted(scores, reverse=True)]

    async def _reason(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.responses_api:
            body = await self._post(
                "/responses",
                {
                    "model": self.model,
                    "instructions": (
                        "Classify an insight card over retrieved evidence. Return only the "
                        "requested JSON schema. Use only the configured outcomes and delivery "
                        "methods. Never invent evidence, destinations, or facts."
                    ),
                    "input": json.dumps(payload, separators=(",", ":")),
                    "store": False,
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "insight_result",
                            "strict": True,
                            "schema": self._response_schema(),
                        }
                    },
                },
            )
            content = body.get("output_text")
            if not isinstance(content, str):
                content = self._response_output_text(body)
            if not content:
                raise ValueError("baseline Responses API returned no output text")
            return self._parse_json(content)
        body = await self._post(
            "/chat/completions",
            {
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Classify an insight card over retrieved evidence. Return JSON only "
                            "with keys outcome, rationale, confidence, watch_results, "
                            "question_results, probabilities. Use only configured outcomes "
                            "and delivery methods. Never invent evidence or facts."
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
        return self._parse_json(content)

    @staticmethod
    def _response_schema() -> dict[str, Any]:
        probability_item = {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "probability": {"type": "number"},
            },
            "required": ["key", "probability"],
            "additionalProperties": False,
        }
        return {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": [outcome.value for outcome in Outcome],
                },
                "rationale": {"type": "string"},
                "confidence": {"type": "number"},
                "watch_results": {"type": "array", "items": probability_item},
                "question_results": {"type": "array", "items": probability_item},
                "probabilities": {
                    "type": "object",
                    "additionalProperties": {"type": "number"},
                },
            },
            "required": [
                "outcome",
                "rationale",
                "confidence",
                "watch_results",
                "question_results",
                "probabilities",
            ],
            "additionalProperties": False,
        }

    @staticmethod
    def _response_output_text(body: dict[str, Any]) -> str:
        for item in body.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    return content["text"]
        return ""

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
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
        if response.is_error:
            try:
                detail = response.json().get("error", {})
            except ValueError:
                detail = response.text[:500]
            raise httpx.HTTPStatusError(
                f"{response.status_code} {detail}",
                request=response.request,
                response=response,
            )
        body = response.json()
        usage = body.get("usage", {})
        self.metrics.requests += 1
        self.metrics.record_tokens(
            usage.get("prompt_tokens") or usage.get("input_tokens"),
            usage.get("completion_tokens") or usage.get("output_tokens"),
        )
        return body

    @staticmethod
    def _text(document: dict[str, Any]) -> str:
        return " ".join(
            str(document.get(key) or "")
            for key in (
                "subject_label",
                "metric",
                "unit",
                "freshness",
                "dimensions",
                "attributes",
            )
        )

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = sum(value * value for value in left) ** 0.5
        right_norm = sum(value * value for value in right) ** 0.5
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
