"""Decision backends for OpenAI Decisions and ChatGPT-plan Responses.

The Decisions API returns native typed probabilities. The ChatGPT-plan path is
Responses structured output and explicitly labels its model-estimated scores as
such; it is not presented as the Decisions API or as calibrated probabilities.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from collections.abc import Mapping
from typing import Any, Protocol

import httpx

from .models import (
    Evidence,
    InsightCard,
    InsightPlan,
    InsightResult,
    Observation,
    Outcome,
    QuestionResult,
    QuestionStatus,
    ResourceDescriptor,
    WatchResult,
    WatchStatus,
)
from .retrieval import resource_ref
from .typesafe_adapter import JevJudger, compact_json_value, estimate_json_tokens

DECISIONS_URL = "https://api.openai.com/v1/decisions"
RESPONSES_URL = "https://api.openai.com/v1/responses"
MAX_INPUT_TOKENS = 12_000
MAX_CANDIDATES = 40
_DIAGNOSTIC_TOKEN = re.compile(r"[A-Za-z0-9_.:/-]{1,120}\Z")


def _safe_diagnostic(value: Any) -> str | None:
    if isinstance(value, str) and _DIAGNOSTIC_TOKEN.fullmatch(value):
        return value
    return None


def _request_id(response: httpx.Response) -> str | None:
    return _safe_diagnostic(
        response.headers.get("openai-request-id") or response.headers.get("x-request-id")
    )


def _error_details(payload: Any) -> tuple[str | None, str | None, str]:
    if not isinstance(payload, Mapping):
        return None, None, "non-object response"
    error = payload.get("error")
    if isinstance(error, Mapping):
        code = _safe_diagnostic(error.get("code") or error.get("type"))
        param = _safe_diagnostic(error.get("param"))
        return code, param, "error object"
    if isinstance(error, str):
        return _safe_diagnostic(error), None, "error string"
    if "detail" in payload:
        return None, None, "detail object"
    return None, None, "JSON object"


def _http_failure(provider: str, response: httpx.Response) -> RuntimeError:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        payload = None
        body_shape = "non-JSON response"
    else:
        _code, _param, body_shape = _error_details(payload)
    code, param, _ = _error_details(payload)
    details = [f"HTTP {response.status_code}", body_shape]
    if code:
        details.append(f"code={code}")
    if param:
        details.append(f"param={param}")
    if request_id := _request_id(response):
        details.append(f"request_id={request_id}")
    return RuntimeError(f"{provider} request failed ({'; '.join(details)})")


def _event_error_code(event: Mapping[str, Any]) -> tuple[str | None, str | None]:
    response = event.get("response")
    error = response.get("error") if isinstance(response, Mapping) else event.get("error")
    if not isinstance(error, Mapping):
        return _safe_diagnostic(error), None
    return (
        _safe_diagnostic(error.get("code") or error.get("type")),
        _safe_diagnostic(error.get("param")),
    )


def _stream_failure(
    provider: str,
    *,
    event_type: str,
    request_id: str | None,
    code: str | None = None,
    param: str | None = None,
) -> RuntimeError:
    details = [event_type]
    if code:
        details.append(f"code={code}")
    if param:
        details.append(f"param={param}")
    if request_id:
        details.append(f"request_id={request_id}")
    return RuntimeError(f"{provider} request did not complete ({'; '.join(details)})")


class DecisionTransport(Protocol):
    name: str

    async def decide(
        self, input_text: str, questions: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]: ...


def _probability(value: Any) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        return None
    value = float(value)
    return value if 0.0 <= value <= 1.0 else None


def _probability_map(value: Any, choices: list[str]) -> dict[str, float] | None:
    if isinstance(value, list):
        names = [str(item.get("value")) for item in value if isinstance(item, Mapping)]
        if len(names) != len(value) or len(set(names)) != len(names):
            return None
        pairs = {
            str(item.get("value")): _probability(item.get("probability"))
            for item in value
            if isinstance(item, Mapping)
        }
    elif isinstance(value, Mapping):
        pairs = {str(key): _probability(item) for key, item in value.items()}
    else:
        return None
    if set(pairs) != set(choices) or any(item is None for item in pairs.values()):
        return None
    total = sum(float(item) for item in pairs.values())
    if not math.isclose(total, 1.0, abs_tol=0.02):
        return None
    return {key: float(item) / total for key, item in pairs.items()}


class OpenAIDecisionsTransport:
    """Small HTTP client for the native OpenAI Decisions endpoint."""

    name = "openai-decisions"

    def __init__(
        self,
        api_key: str,
        *,
        model: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 45.0,
    ) -> None:
        self.api_key = api_key
        configured_model = model or os.getenv("OPENAI_DECISIONS_MODEL", "gpt-6-luna")
        if configured_model != "gpt-6-luna":
            raise ValueError("OpenAI Decisions currently supports only gpt-6-luna")
        self.model = configured_model
        self.transport = transport
        self.timeout = timeout

    async def decide(
        self, input_text: str, questions: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        question_names = [item.get("name") for item in questions]
        if (
            not question_names
            or not all(isinstance(name, str) and name for name in question_names)
            or len(set(question_names)) != len(question_names)
        ):
            raise ValueError("OpenAI Decisions questions must have unique non-empty names")
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.post(
                DECISIONS_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": input_text, "questions": questions},
            )
        if response.status_code >= 400:
            raise _http_failure("OpenAI Decisions", response)
        try:
            payload = response.json()
            raw_answers = payload["answers"] if isinstance(payload, Mapping) else None
            if not isinstance(raw_answers, list):
                raise TypeError
            results: dict[str, dict[str, Any]] = {}
            by_name = {item["name"]: item for item in questions}
            for answer in raw_answers:
                if not isinstance(answer, Mapping):
                    raise TypeError
                name = answer.get("name")
                if not isinstance(name, str) or name not in by_name or name in results:
                    raise TypeError
                expected = by_name[name]
                if answer.get("type") == "refusal":
                    raise RuntimeError(f"OpenAI Decisions refused question {name!r}")
                if expected["type"] == "predicate" and answer.get("type") == "predicate":
                    probability = _probability(answer.get("probability"))
                    if probability is None:
                        raise TypeError
                    results[name] = {"type": "predicate", "probability": probability}
                elif expected["type"] == "choice" and answer.get("type") == "choice":
                    choices = [str(item["value"]) for item in expected["choices"]]
                    probabilities = _probability_map(answer.get("probabilities"), choices)
                    selected = str(answer.get("choice", ""))
                    confidence = _probability(answer.get("confidence"))
                    if probabilities is None or selected not in probabilities or confidence is None:
                        raise TypeError
                    results[name] = {
                        "type": "choice",
                        "choice": selected,
                        "probabilities": probabilities,
                        "confidence": confidence,
                    }
                else:
                    raise TypeError
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("OpenAI Decisions returned an invalid typed response") from None
        missing = set(by_name) - set(results)
        if missing:
            names = ", ".join(sorted(missing))
            raise RuntimeError(f"OpenAI Decisions omitted answers for: {names}")
        return results


class ChatGPTPlanResponsesTransport:
    """Responses API transport using a user-consented ChatGPT-plan OAuth token."""

    name = "chatgpt-plan-responses"

    def __init__(
        self,
        access_token: Any,
        *,
        model: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 90.0,
    ) -> None:
        self.access_token = access_token
        self.model = model or os.getenv("OPENAI_RESPONSES_MODEL", "gpt-6.1-sol")
        self.transport = transport
        self.timeout = timeout

    @staticmethod
    def _response_schema(questions: list[dict[str, Any]]) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for question in questions:
            name = question["name"]
            required.append(name)
            if question["type"] == "predicate":
                properties[name] = {"type": "number", "minimum": 0, "maximum": 1}
            else:
                choices = [str(item["value"]) for item in question["choices"]]
                probability_properties = {
                    choice: {"type": "number", "minimum": 0, "maximum": 1} for choice in choices
                }
                properties[name] = {
                    "type": "object",
                    "properties": {
                        "choice": {"type": "string", "enum": choices},
                        "probabilities": {
                            "type": "object",
                            "properties": probability_properties,
                            "required": choices,
                            "additionalProperties": False,
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["choice", "probabilities", "confidence"],
                    "additionalProperties": False,
                }
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    async def decide(
        self, input_text: str, questions: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        token = self.access_token()
        if asyncio.iscoroutine(token):
            token = await token
        question_text = json.dumps(questions, ensure_ascii=False, separators=(",", ":"))
        instructions = (
            "Apply only the supplied owner-authored policies to the evidence. Do not infer missing facts, "
            "causation, or destinations. Return model-estimated probability values in the requested "
            "schema; these are not calibrated API-native class probabilities. Questions are independent "
            "diagnostics unless the outcome instructions say otherwise.\nDecision questions: "
            + question_text
        )
        body = {
            "model": self.model,
            "instructions": instructions,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": input_text}]}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "signalweave_decision",
                    "strict": True,
                    "schema": self._response_schema(questions),
                }
            },
            "store": False,
            "stream": True,
        }
        request_id: str | None = None
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            async with client.stream(
                "POST",
                RESPONSES_URL,
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            ) as response:
                request_id = _request_id(response)
                if response.status_code >= 400:
                    await response.aread()
                    raise _http_failure("ChatGPT-plan Responses", response)
                final_payload: dict[str, Any] | None = None
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].lstrip()
                    if data == "[DONE]":
                        continue
                    if not data:
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        raise _stream_failure(
                            "ChatGPT-plan Responses",
                            event_type="invalid event JSON",
                            request_id=request_id,
                        ) from None
                    if not isinstance(event, Mapping):
                        raise _stream_failure(
                            "ChatGPT-plan Responses",
                            event_type="invalid event object",
                            request_id=request_id,
                        )
                    event_type = event.get("type")
                    if not isinstance(event_type, str):
                        raise _stream_failure(
                            "ChatGPT-plan Responses",
                            event_type="invalid event type",
                            request_id=request_id,
                        )
                    if event_type in {"response.failed", "error"}:
                        code, param = _event_error_code(event)
                        raise _stream_failure(
                            "ChatGPT-plan Responses",
                            event_type=str(event_type),
                            request_id=request_id,
                            code=code,
                            param=param,
                        )
                    if event_type == "response.incomplete":
                        code, param = _event_error_code(event)
                        response_payload = event.get("response")
                        incomplete = (
                            response_payload.get("incomplete_details")
                            if isinstance(response_payload, Mapping)
                            else None
                        )
                        reason = (
                            _safe_diagnostic(incomplete.get("reason"))
                            if isinstance(incomplete, Mapping)
                            else None
                        )
                        raise _stream_failure(
                            "ChatGPT-plan Responses",
                            event_type=f"response.incomplete reason={reason}" if reason else "response.incomplete",
                            request_id=request_id,
                            code=code,
                            param=param,
                        )
                    if event_type == "response.completed":
                        response_payload = event.get("response")
                        if not isinstance(response_payload, Mapping):
                            raise _stream_failure(
                                "ChatGPT-plan Responses",
                                event_type="invalid response.completed payload",
                                request_id=request_id,
                            )
                        final_payload = dict(response_payload)
        if not isinstance(final_payload, Mapping):
            raise _stream_failure(
                "ChatGPT-plan Responses",
                event_type="stream ended without response.completed",
                request_id=request_id,
            )
        if any(
            isinstance(content, Mapping) and content.get("type") == "refusal"
            for item in final_payload.get("output", []) or []
            if isinstance(item, Mapping)
            for content in item.get("content", []) or []
        ):
            raise _stream_failure(
                "ChatGPT-plan Responses",
                event_type="refusal",
                request_id=request_id,
            )
        output_text = final_payload.get("output_text")
        if not isinstance(output_text, str):
            chunks = []
            for item in final_payload.get("output", []) or []:
                if not isinstance(item, Mapping):
                    continue
                for content in item.get("content", []) or []:
                    if isinstance(content, Mapping) and content.get("type") == "output_text":
                        chunks.append(str(content.get("text", "")))
            output_text = "".join(chunks)
        try:
            payload = json.loads(output_text)
        except (TypeError, json.JSONDecodeError):
            raise RuntimeError(
                "ChatGPT-plan Responses returned invalid structured output"
            ) from None
        if not isinstance(payload, Mapping):
            raise RuntimeError("ChatGPT-plan Responses returned invalid structured output")
        results: dict[str, dict[str, Any]] = {}
        by_name = {item["name"]: item for item in questions}
        if set(payload) != set(by_name):
            missing = sorted(set(by_name) - set(payload))
            extra = sorted(set(payload) - set(by_name))
            detail = []
            if missing:
                detail.append("missing " + ", ".join(missing))
            if extra:
                detail.append("unexpected " + ", ".join(extra))
            raise RuntimeError(
                "ChatGPT-plan Responses returned incomplete structured output: "
                + "; ".join(detail)
            )
        for name, expected in by_name.items():
            answer = payload[name]
            if expected["type"] == "predicate":
                probability = _probability(answer)
                if probability is None:
                    raise RuntimeError(
                        f"ChatGPT-plan Responses returned an invalid predicate answer for {name!r}"
                    )
                results[name] = {"type": "predicate", "probability": probability}
                continue
            if not isinstance(answer, Mapping):
                raise RuntimeError(
                    f"ChatGPT-plan Responses returned an invalid choice answer for {name!r}"
                )
            choices = [str(item["value"]) for item in expected["choices"]]
            selected = str(answer.get("choice", ""))
            probabilities = _probability_map(answer.get("probabilities"), choices)
            confidence = _probability(answer.get("confidence"))
            if selected not in choices or probabilities is None or confidence is None:
                raise RuntimeError(
                    f"ChatGPT-plan Responses returned an invalid choice answer for {name!r}"
                )
            results[name] = {
                "type": "choice",
                "choice": selected,
                "probabilities": probabilities,
                "confidence": confidence,
            }
        return results


class OpenAIDecisionJudger:
    """Typed card and source-selection judgments using an OpenAI transport."""

    skip_semantic_compile = True
    supports_judgment_chunking = False
    item_threshold = 0.70
    name = "openai-decisions"

    def __init__(self, transport: DecisionTransport) -> None:
        self.transport = transport
        self.name = transport.name

    async def _ask(self, state: Any, questions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        input_text = json.dumps(state, ensure_ascii=False, separators=(",", ":"), default=str)
        observed = estimate_json_tokens({"input": input_text, "questions": questions})
        budget = int(os.getenv("SIGNALWEAVE_MAX_DECISION_INPUT_TOKENS", str(MAX_INPUT_TOKENS)))
        if budget < 1 or observed > budget:
            raise RuntimeError(
                f"Decision request is too large ({observed} estimated tokens; limit {budget}); "
                "narrow the selected evidence or card scope"
            )
        try:
            answers = await self.transport.decide(input_text, questions)
        except httpx.TransportError:
            raise RuntimeError(
                f"{self.name} could not be reached; check network and provider status"
            ) from None
        if not isinstance(answers, Mapping):
            raise RuntimeError(f"{self.name} returned an invalid answer collection")
        expected_names = {item["name"] for item in questions}
        received_names = set(answers)
        missing = expected_names - received_names
        unexpected = received_names - expected_names
        if missing or unexpected:
            details = []
            if missing:
                details.append("missing " + ", ".join(sorted(missing)))
            if unexpected:
                details.append("unexpected " + ", ".join(sorted(unexpected)))
            raise RuntimeError(f"{self.name} returned an incomplete answer set ({'; '.join(details)})")
        if not all(isinstance(answer, Mapping) for answer in answers.values()):
            raise RuntimeError(f"{self.name} returned a malformed typed answer")
        return dict(answers)

    @staticmethod
    def _choice(name: str, instructions: str, choices: Mapping[str, str]) -> dict[str, Any]:
        return {
            "type": "choice",
            "name": name,
            "instructions": instructions,
            "choices": [
                {"value": key, "description": description} for key, description in choices.items()
            ],
        }

    @staticmethod
    def _predicate(name: str, instructions: str) -> dict[str, Any]:
        return {"type": "predicate", "name": name, "instructions": instructions}

    @staticmethod
    def _input_state(
        state: Mapping[str, Any],
        card: InsightCard,
        plan: InsightPlan,
        observations: list[Observation],
    ) -> dict[str, Any]:
        compact = JevJudger._compact_synthesis_state(
            state, card, plan, observations, {}, semantic_roles=False
        )
        return {
            "evidence_bundle": compact,
            "decision_contract": {
                "apply_owner_guidance": True,
                "diagnostics_are_not_extra_outcome_prerequisites": True,
                "correlation_and_computed_contributions_do_not_prove_causality": True,
                "incomplete_rollups_are_unresolved_not_absent": True,
            },
        }

    @staticmethod
    def _outcomes(card: InsightCard) -> list[Outcome]:
        result = [Outcome.IGNORE, Outcome.INVESTIGATE, Outcome.INSUFFICIENT_DATA]
        for method in card.delivery_methods:
            if method.outcome not in result:
                result.append(method.outcome)
        return result

    @classmethod
    def _outcome_questions(cls, card: InsightCard) -> tuple[dict[str, str], str]:
        criteria: dict[str, str] = {}
        for outcome in cls._outcomes(card):
            methods = [item for item in card.delivery_methods if item.outcome == outcome]
            if outcome == Outcome.IGNORE:
                reason = "Evidence establishes no action is needed under the owner's policy; missing data is not a reason to ignore."
            elif outcome == Outcome.INVESTIGATE:
                reason = "Evidence is meaningful or ambiguous and warrants downstream or human investigation."
            elif outcome == Outcome.INSUFFICIENT_DATA:
                reason = "Missing, conflicting, untrusted, or semantically incomplete evidence prevents applying policy."
            elif methods:
                reason = (
                    "The owner's policy supports this routed outcome. Destinations do not create triggers: "
                    + "; ".join(
                        f"{item.key}: {item.instructions or item.label}" for item in methods
                    )
                )
            else:
                reason = "The owner's policy supports this outcome."
            criteria[outcome.value] = reason
        instructions = (
            "Choose one mutually exclusive outcome by applying only the human-authored card purpose, "
            "decision guidance, numeric conditions, and supplied evidence. Ignore, investigate, and "
            "insufficient_data are always allowed. Notify/escalate are available only when configured "
            "on the card. Do not infer new thresholds, causes, recipients, or permissions."
        )
        return criteria, instructions

    async def judge(
        self,
        state: dict[str, Any],
        card: InsightCard,
        plan: InsightPlan,
        observations: list[Observation],
    ) -> InsightResult:
        prompt_state = self._input_state(state, card, plan, observations)
        questions: list[dict[str, Any]] = []
        watch_items = list(card.watch_for)
        for index, item in enumerate(watch_items):
            questions.append(
                self._choice(
                    f"watch_{index}",
                    f"Classify whether this owner-defined watch condition is established: {item!r}. "
                    "Use absent only when sufficient applicable evidence rules it out; use unknown for missing/conflicting evidence.",
                    {
                        "present": "The condition is established by applicable evidence.",
                        "absent": "Sufficient applicable evidence establishes the condition does not hold.",
                        "unknown": "Evidence is missing, conflicting, or insufficient.",
                    },
                )
            )
        for index, question in enumerate(card.questions):
            questions.append(
                self._predicate(
                    f"question_{index}",
                    f"Estimate the probability that this question has a concrete evidence-backed answer: {question!r}. "
                    "Do not invent missing definitions or causal facts.",
                )
            )
        outcome_criteria, outcome_instructions = self._outcome_questions(card)
        questions.append(self._choice("outcome", outcome_instructions, outcome_criteria))
        answers = await self._ask(prompt_state, questions)

        watch_results: list[WatchResult] = []
        for index, item in enumerate(watch_items):
            answer = answers.get(f"watch_{index}", {})
            choices = answer.get("probabilities", {})
            allowed = {item.value for item in WatchStatus}
            valid = (
                answer.get("type") == "choice"
                and answer.get("choice") in allowed
                and set(choices) == allowed
                and math.isclose(sum(choices.values()), 1.0, abs_tol=1e-6)
            )
            selected = answer["choice"] if valid else WatchStatus.UNKNOWN.value
            watch_results.append(
                WatchResult(
                    key=f"watch_{index}",
                    watch_for=item,
                    status=WatchStatus(selected),
                    probability=choices.get("present", 0.5) if valid else 0.5,
                    probabilities=choices if valid else {},
                )
            )
        question_results: list[QuestionResult] = []
        for index, question in enumerate(card.questions):
            answer = answers.get(f"question_{index}", {})
            probability = answer.get("probability") if answer.get("type") == "predicate" else None
            if probability is None:
                probability = 0.5
            status = (
                QuestionStatus.SUPPORTED
                if probability >= 0.70
                else QuestionStatus.NOT_SUPPORTED
                if probability <= 0.30
                else QuestionStatus.UNKNOWN
            )
            question_results.append(
                QuestionResult(
                    key=f"question_{index}",
                    question=question,
                    status=status,
                    probability=probability,
                )
            )
        outcomes = self._outcomes(card)
        outcome_answer = answers.get("outcome", {})
        probabilities = outcome_answer.get("probabilities", {})
        valid_outcome = (
            outcome_answer.get("type") == "choice"
            and outcome_answer.get("choice") in {item.value for item in outcomes}
            and set(probabilities) == {item.value for item in outcomes}
            and math.isclose(sum(probabilities.values()), 1.0, abs_tol=1e-6)
        )
        selected = outcome_answer.get("choice") if valid_outcome else Outcome.INVESTIGATE.value
        selected_probability = probabilities.get(selected, 0.0) if valid_outcome else 0.0
        routed_outcome = Outcome(selected)
        # Preserve the selected data-gap/investigation handoff, just as the
        # engine does. The support floor gates business conclusions/actions.
        if (routed_outcome in (Outcome.IGNORE, Outcome.NOTIFY, Outcome.ESCALATE)
                and selected_probability < card.action_confidence_threshold):
            routed_outcome = Outcome.INVESTIGATE
        source_keys = plan.selected_source_keys or [source.key for source in card.sources]
        provider_note = (
            "ChatGPT-plan Responses produced model-estimated probabilities; they are not native or calibrated Decisions API probabilities."
            if self.name == "chatgpt-plan-responses"
            else "Probabilities are the provider's typed Decisions API distribution."
        )
        evidence = [Evidence.model_validate(item) for item in state.get("evidence", [])]
        source_evidence_count = sum(item.origin == "source" for item in evidence)
        return InsightResult(
            card_id=card.id,
            outcome=routed_outcome,
            summary=(
                f"Evaluated {source_evidence_count} source evidence items, {len(observations)} "
                f"normalized observations, and {len(state.get('analyses', []))} computed analyses "
                f"across {len(source_keys)} sources (counts may overlap)."
            ),
            rationale=(
                f"{self.name} evaluated the owner's typed watch, question, and outcome policy; "
                f"selected={selected}, support={selected_probability:.2f}; routed={routed_outcome.value}. "
                f"{provider_note}"
            ),
            confidence=selected_probability if valid_outcome else 0.0,
            probabilities=probabilities if valid_outcome else {},
            watch_results=watch_results,
            question_results=question_results,
            evidence_findings=[],
            evidence=evidence,
            observations=observations,
            source_keys=source_keys,
            evaluator=self.name,
        )

    async def rank_resources(
        self, goal: str, resources: list[ResourceDescriptor]
    ) -> dict[str, float]:
        candidates = resources[:MAX_CANDIDATES]
        if not candidates:
            return {}
        question_defs = [
            self._predicate(
                f"candidate_{index}",
                f"Could this authorized resource materially help answer this user's goal: {goal!r}? "
                "Assess its title, description, kind, contract, and metadata; do not infer permission or ownership.",
            )
            for index, _ in enumerate(candidates)
        ]
        payload = {
            "goal": goal,
            "authorized_candidates": [self._resource_payload(item) for item in candidates],
        }
        answers = await self._ask(payload, question_defs)
        return {
            resource_ref(item): float(answers.get(f"candidate_{index}", {}).get("probability", 0.0))
            for index, item in enumerate(candidates)
        }

    async def classify_resource_roles(
        self, goal: str, resources: list[ResourceDescriptor]
    ) -> dict[str, dict[str, Any]]:
        candidates = resources[:MAX_CANDIDATES]
        if not candidates:
            return {}
        choices = {
            "primary": "Canonical source directly measures or anchors the goal.",
            "corroborates": "Independent evidence can cross-check a primary signal.",
            "diagnostic": "Could help explain why a signal moved; not proof of causation.",
            "quality": "Qualifies freshness, completeness, definition, or trustworthiness.",
            "owner": "Identifies accountable owner or delivery context.",
            "unknown": "The role cannot be established from available metadata.",
        }
        question_defs = [
            self._choice(
                f"role_{index}",
                f"What role could this authorized resource play for the user's goal {goal!r}? Use metadata only; do not infer causality or ownership.",
                choices,
            )
            for index, _ in enumerate(candidates)
        ]
        answers = await self._ask(
            {
                "goal": goal,
                "authorized_candidates": [self._resource_payload(item) for item in candidates],
            },
            question_defs,
        )
        return {
            resource_ref(item): {
                "role": answers[f"role_{index}"]["choice"],
                "probability": answers[f"role_{index}"]["probabilities"][
                    answers[f"role_{index}"]["choice"]
                ],
            }
            for index, item in enumerate(candidates)
            if f"role_{index}" in answers
        }

    @staticmethod
    def _resource_payload(resource: ResourceDescriptor) -> dict[str, Any]:
        return compact_json_value(
            {
                "ref": resource_ref(resource),
                "adapter": resource.adapter,
                "resource": resource.resource,
                "kind": resource.kind,
                "title": resource.title,
                "description": resource.description,
                "metadata": resource.metadata,
                "contract": resource.contract.model_dump(mode="json"),
            },
            max_string=700,
            max_items=30,
            max_depth=4,
        )

    async def select_investigation_sources(
        self,
        state: dict[str, Any],
        card: InsightCard,
        plan: InsightPlan,
        candidates: list[ResourceDescriptor],
        max_sources: int,
    ) -> dict[str, Any]:
        candidates = candidates[:MAX_CANDIDATES]
        questions = [
            self._predicate(
                "need_investigation",
                "Does initial evidence leave a material question unresolved that an authorized follow-up source may clarify? "
                "Do not investigate when evidence is already sufficient; correlation alone does not prove a cause.",
            )
        ]
        questions.extend(
            self._predicate(
                f"candidate_{index}",
                "Could this source materially clarify, corroborate, contradict, or qualify the current evidence? "
                "Do not infer causality from relevance.",
            )
            for index, _ in enumerate(candidates)
        )
        answers = await self._ask(
            {
                "card": card.execution_payload(),
                "plan": plan.model_dump(mode="json"),
                "current_state": compact_json_value(
                    state, max_string=600, max_items=40, max_depth=4
                ),
                "authorized_candidates": [self._resource_payload(item) for item in candidates],
            },
            questions,
        )
        ranked = [
            {
                "ref": resource_ref(resource),
                "score": float(answers.get(f"candidate_{index}", {}).get("probability", 0.0)),
                "confidence": float(answers.get(f"candidate_{index}", {}).get("probability", 0.0)),
            }
            for index, resource in enumerate(candidates)
        ]
        ranked.sort(key=lambda item: (-item["score"], item["ref"]))
        return {
            "probability": float(answers.get("need_investigation", {}).get("probability", 0.0)),
            "selections": ranked[:max_sources],
        }

    async def select_metric_plan(
        self,
        goal: str,
        candidates: list[dict[str, Any]],
        requested_dimensions: list[str],
        requested_time_grain: str | None,
    ) -> dict[str, Any]:
        candidates = candidates[:50]
        if not candidates:
            raise ValueError("metric selection requires at least one approved candidate")
        candidate_choices = {
            str(item["candidate_id"]): (
                f"{item.get('label')}; {item.get('description')}; population={item.get('population')}; "
                f"grain={item.get('grain')}; dimensions={','.join(item.get('dimensions', {}))}"
            )
            for item in candidates
        }
        questions = [
            self._choice(
                "metric",
                "Which approved metric definition best answers this question? Match population, grain, aggregation, relation, and dimensions; label overlap alone is not enough.",
                candidate_choices,
            )
        ]
        all_dimensions = sorted(
            {name for item in candidates for name in item.get("dimensions", {})}
        )
        for index, dimension in enumerate(all_dimensions):
            questions.append(
                self._predicate(
                    f"dimension_{index}",
                    f"Does the request explicitly require grouping by dimension {dimension!r}?",
                )
            )
        grains = sorted(
            {grain for item in candidates for grain in item.get("supported_grains", [])}
        )
        if requested_time_grain is None and grains:
            questions.append(
                self._choice(
                    "time_grain",
                    f"Choose the time grain that best answers this request: {goal!r}.",
                    {grain: f"Group by {grain}." for grain in grains},
                )
            )
        answers = await self._ask(
            {
                "goal": goal,
                "requested_dimensions": requested_dimensions,
                "requested_time_grain": requested_time_grain,
                "approved_metric_definitions": candidates,
            },
            questions,
        )
        selected = answers.get("metric", {})
        if selected.get("type") != "choice":
            raise ValueError("OpenAI did not return a valid metric definition selection")
        result: dict[str, Any] = {
            "candidate_id": selected["choice"],
            "probability": selected["probabilities"][selected["choice"]],
            "dimensions": list(requested_dimensions),
        }
        result["dimensions"] = sorted(
            set(
                result["dimensions"]
                + [
                    dimension
                    for index, dimension in enumerate(all_dimensions)
                    if answers.get(f"dimension_{index}", {}).get("probability", 0.0) >= 0.70
                ]
            )
        )
        if requested_time_grain:
            result["time_grain"] = requested_time_grain
        elif "time_grain" in answers:
            result["time_grain"] = answers["time_grain"]["choice"]
        return result

    async def compile_plan(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("plan compilation is owned by the card and source contracts")


__all__ = [
    "ChatGPTPlanResponsesTransport",
    "OpenAIDecisionJudger",
    "OpenAIDecisionsTransport",
]
