from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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


class InsightJudger(Protocol):
    name: str

    async def compile_plan(
        self, state: dict[str, Any], card: InsightCard
    ) -> dict[str, Any]: ...

    async def judge(
        self,
        state: dict[str, Any],
        card: InsightCard,
        plan: InsightPlan,
        observations: list[Observation],
    ) -> InsightResult: ...


@dataclass
class JudgerMetrics:
    """Small, non-sensitive counters used by the local benchmark harness."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def record(self, response: Any) -> None:
        self.requests += 1
        usage = getattr(response, "usage", None)
        self.record_tokens(
            getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None)
        )

    def record_tokens(self, input_tokens: Any = None, output_tokens: Any = None) -> None:
        self.input_tokens += int(input_tokens or 0)
        self.output_tokens += int(output_tokens or 0)


class JevJudger:
    """Use Jev for bounded planning and per-card semantic judgments."""

    name = "jev-latest"
    item_threshold = 0.70

    def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
        from typesafe_sdk import AsyncTypeSafeClient

        timeout_seconds = timeout
        if timeout_seconds is None:
            try:
                timeout_seconds = float(os.getenv("TYPESAFE_TIMEOUT_SECONDS", "30"))
            except ValueError as error:
                raise ValueError("TYPESAFE_TIMEOUT_SECONDS must be a positive number") from error
        if timeout_seconds <= 0:
            raise ValueError("TYPESAFE_TIMEOUT_SECONDS must be a positive number")
        self._client_type = AsyncTypeSafeClient
        self._api_key = api_key
        self._timeout = timeout_seconds
        self.metrics = JudgerMetrics()

    async def rank_resources(
        self, goal: str, resources: list[ResourceDescriptor]
    ) -> dict[str, float]:
        """Rank bounded catalog candidates for a natural-language insight goal."""
        from typesafe_sdk import Noul

        state = {
            "goal": goal,
            "candidate_resources": [
                {
                    "ref": f"{resource.adapter}|{resource.resource}",
                    "adapter": resource.adapter,
                    "resource": resource.resource,
                    "kind": resource.kind,
                    "title": resource.title,
                    "description": resource.description,
                    "source_url": resource.source_url,
                    "metadata": resource.metadata,
                }
                for resource in resources
            ],
        }
        questions = {
            f"resource_{index}": Noul(
                instructions=(
                    f"Is candidate_resources[{index}] materially relevant to the user's "
                    "insight goal? Consider the candidate title, description, kind, and "
                    "metadata. Judge relevance to the goal, not whether the source is "
                    "merely a valid resource."
                ),
                criteria={
                    "true": "The resource contains or represents signals that could help answer the goal.",
                    "false": "The resource is unrelated, too vague, or not useful for the goal.",
                },
            )
            for index in range(len(resources))
        }
        if not questions:
            return {}
        async with self._client_type(api_key=self._api_key, timeout=self._timeout) as client:
            response = await client.system_one(state=state, questions=questions)
        self.metrics.record(response)
        return {
            f"{resource.adapter}|{resource.resource}": response.nouls[f"resource_{index}"].noul
            for index, resource in enumerate(resources)
        }

    async def compile_plan(
        self, state: dict[str, Any], card: InsightCard
    ) -> dict[str, Any]:
        from typesafe_sdk import Choice, Noul

        available_capabilities = state["available_capabilities"]
        questions = {
            f"use_{capability['key']}": Noul(
                instructions=(
                    f"Does this insight card require the `{capability['key']}` "
                    "capability for its selected sources and stated purpose? Read "
                    "card.what_to_watch, card.why_watch, card.watch_for, card.questions, "
                    "and the available source metadata."
                ),
                criteria={
                    "true": capability["description"],
                    "false": "This capability is not needed for the card's stated purpose.",
                },
            )
            for capability in available_capabilities
        }
        windows = card.comparison_windows or ["previous_period"]
        questions["baseline"] = Choice(
            instructions="Which comparison window best fits the card's stated purpose?",
            criteria={window: None for window in windows},
        )

        async with self._client_type(api_key=self._api_key, timeout=self._timeout) as client:
            response = await client.system_one(state=state, questions=questions)
        self.metrics.record(response)
        capabilities = [
            capability["key"]
            for capability in available_capabilities
            if response.nouls[f"use_{capability['key']}"].noul >= 0.6
        ]
        return {"capabilities": capabilities, "baseline": response.choices["baseline"].choice}

    async def judge(
        self,
        state: dict[str, Any],
        card: InsightCard,
        plan: InsightPlan,
        observations: list[Observation],
    ) -> InsightResult:
        from typesafe_sdk import Noul

        # Each owner-authored item gets a typed judgment. That is what makes a
        # result useful for cards with many metrics: the caller gets the exact
        # items that were supported, not just one opaque alert explanation.
        questions: dict[str, Any] = {}
        for index, watch_item in enumerate(card.watch_for):
            questions[f"watch_{index}"] = Noul(
                instructions=(
                    f"Does the current evidence support watch_for[{index}]? Assess the "
                    "card's purpose, all normalized observations, all evidence, and "
                    "related source context. Do not require a numeric change when the "
                    "item describes existence, freshness, a relationship, or another "
                    "non-numeric condition."
                ),
                criteria={
                    "true": watch_item,
                    "false": "The current evidence does not support this watch item or is insufficient to judge it.",
                },
            )
        for index, question in enumerate(card.questions):
            questions[f"question_{index}"] = Noul(
                instructions=(
                    f"Does the available evidence support a concrete answer to questions[{index}]? "
                    "Use only the normalized observations, source evidence, and card context. "
                    "A related metric may support an answer, but do not invent facts that are absent."
                ),
                criteria={
                    "true": question,
                    "false": "The available evidence does not support a concrete answer to this question.",
                },
            )

        action_outcomes = [Outcome.IGNORE, Outcome.INVESTIGATE]
        for method in card.delivery_methods:
            if method.outcome not in action_outcomes and method.outcome not in {
                Outcome.INSUFFICIENT_DATA
            }:
                action_outcomes.append(method.outcome)
        for outcome in action_outcomes:
            methods = [method for method in card.delivery_methods if method.outcome == outcome]
            if outcome == Outcome.IGNORE:
                condition = "The evidence is not actionable for this card's stated purpose."
            elif outcome == Outcome.INVESTIGATE:
                condition = "The evidence warrants human or downstream investigation before an automatic action."
            elif methods:
                condition = "\n".join(
                    [
                        f"Delivery method {method.key}: {method.instructions or method.label}"
                        for method in methods
                    ]
                )
            else:
                condition = "The evidence supports this outcome under the card's stated purpose."
            questions[f"outcome_{outcome.value}"] = Noul(
                instructions=(
                    f"Does the current evidence satisfy the card's condition for the "
                    f"`{outcome.value}` outcome? Read card.what_to_watch, card.why_watch, "
                    "card.watch_for, card.questions, all observations, and all evidence. "
                    "Do not invent sources, destinations, or facts."
                ),
                criteria={
                    "true": condition,
                    "false": "The evidence does not support this outcome condition.",
                },
            )

        async with self._client_type(api_key=self._api_key, timeout=self._timeout) as client:
            response = await client.system_one(state=state, questions=questions)
        self.metrics.record(response)

        def probability(key: str) -> float:
            return max(0.0, min(1.0, float(response.nouls[key].noul)))

        watch_results = [
            self._watch_result(index, item, probability(f"watch_{index}"))
            for index, item in enumerate(card.watch_for)
        ]
        question_results = [
            self._question_result(index, question, probability(f"question_{index}"))
            for index, question in enumerate(card.questions)
        ]
        action_probabilities = {
            outcome.value: probability(f"outcome_{outcome.value}")
            for outcome in action_outcomes
        }
        selected_outcome, selected_probability = max(
            action_probabilities.items(), key=lambda item: item[1]
        )
        outcome = Outcome(selected_outcome)
        confidence = selected_probability
        if confidence < card.action_confidence_threshold:
            outcome = Outcome.INVESTIGATE
        source_keys = plan.selected_source_keys or [source.key for source in card.sources]
        summary = (
            f"Evaluated {len(observations)} observations across {len(source_keys)} sources; "
            f"{len(watch_results)} watch items and {len(question_results)} questions were checked."
        )
        return InsightResult(
            card_id=card.id,
            outcome=outcome,
            summary=summary,
            rationale=(
                f"Jev evaluated the card's typed watch, question, and outcome judgments; "
                f"selected={outcome.value}, support={confidence:.2f}."
            ),
            confidence=confidence,
            probabilities=action_probabilities,
            watch_results=watch_results,
            question_results=question_results,
            evidence=[Evidence.model_validate(item) for item in state["evidence"]],
            observations=observations,
            source_keys=source_keys,
            evaluator=self.name,
        )

    def _watch_result(self, index: int, item: str, probability: float) -> WatchResult:
        if probability >= self.item_threshold:
            status = WatchStatus.PRESENT
        elif probability <= 1 - self.item_threshold:
            status = WatchStatus.ABSENT
        else:
            status = WatchStatus.UNKNOWN
        return WatchResult(
            key=f"watch_{index}", watch_for=item, status=status, probability=probability
        )

    def _question_result(self, index: int, question: str, probability: float) -> QuestionResult:
        if probability >= self.item_threshold:
            status = QuestionStatus.SUPPORTED
        elif probability <= 1 - self.item_threshold:
            status = QuestionStatus.NOT_SUPPORTED
        else:
            status = QuestionStatus.UNKNOWN
        return QuestionResult(
            key=f"question_{index}", question=question, status=status, probability=probability
        )


def load_api_key(path: str | None = None) -> str | None:
    path = path or os.getenv("TYPESAFE_API_KEY_FILE")
    if not path:
        return os.getenv("TYPESAFE_API_KEY")
    key_path = Path(path)
    if not key_path.exists():
        raise FileNotFoundError(f"TypeSafe API key file does not exist: {key_path}")
    return key_path.read_text().strip()
