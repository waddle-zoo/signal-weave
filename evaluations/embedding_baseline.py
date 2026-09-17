"""Optional embedding-plus-reasoning baseline for apples-to-apples evaluation.

The adapter speaks the common OpenAI-compatible ``/embeddings`` shape and either
``/chat/completions`` or ``/responses`` for the decision. It is deliberately not
part of the product runtime: it exists so a team can compare Jev with the model
and provider it already uses, using the same normalized workflow state and safety
gates.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from semantic_monitor.compiler import base_plan
from semantic_monitor.models import Decision, MonitorPlan, MonitorWorkflow, Observation, Outcome
from semantic_monitor.typesafe_adapter import JudgerMetrics


class EmbeddingReasoningJudger:
    """Retrieve workflow evidence with embeddings, then ask a model for JSON."""

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
        self, state: dict[str, Any], workflow: MonitorWorkflow
    ) -> dict[str, Any]:
        """Hold plan compilation constant so the comparison isolates judgment quality."""
        plan = base_plan(workflow)
        return {"operations": plan.operations, "baseline": plan.comparison_windows[0]}

    async def judge(
        self,
        state: dict[str, Any],
        workflow: MonitorWorkflow,
        plan: MonitorPlan,
        observations: list[Observation],
    ) -> Decision:
        documents = [self._document(observation) for observation in observations]
        query = workflow.intent
        ranked = await self._rank(query, documents)
        retrieved = [documents[index] for index in ranked[: self.top_k]]
        payload = {
            "workflow_intent": workflow.intent,
            "allowed_outcomes": [outcome.value for outcome in workflow.allowed_outcomes],
            "approved_recipients": [recipient.key for recipient in workflow.recipients],
            "retrieved_source_observations": retrieved,
            "evidence": state["evidence"],
        }
        result = await self._reason(payload)
        try:
            outcome = Outcome(result["outcome"])
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError("baseline response must contain a valid outcome") from error
        if outcome not in workflow.allowed_outcomes:
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
            workflow_id=workflow.id,
            source_keys=[
                source["source_key"]
                for source in state.get("sources", [])
                if "source_key" in source
            ]
            or [source.key for source in workflow.sources],
            evaluator=self.name,
        )

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
        if self.responses_api:
            body = await self._post(
                "/responses",
                {
                    "model": self.model,
                    "instructions": (
                        "Classify a monitoring event. Return only the requested JSON schema. "
                        "Use only allowed outcomes and approved recipients. Never invent "
                        "evidence or recipients."
                    ),
                    "input": json.dumps(payload, separators=(",", ":")),
                    "store": False,
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "monitor_decision",
                            "strict": True,
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "outcome": {
                                        "type": "string",
                                        "enum": [outcome.value for outcome in Outcome],
                                    },
                                    "recipient_key": {"type": ["string", "null"]},
                                    "rationale": {"type": "string"},
                                    "confidence": {"type": "number"},
                                },
                                "required": [
                                    "outcome",
                                    "recipient_key",
                                    "rationale",
                                    "confidence",
                                ],
                                "additionalProperties": False,
                            },
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
        return self._parse_json(content)

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
            for key in ("subject_label", "metric", "unit", "freshness", "dimensions")
        )

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = sum(value * value for value in left) ** 0.5
        right_norm = sum(value * value for value in right) ** 0.5
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
