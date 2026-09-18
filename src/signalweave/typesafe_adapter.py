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
from .query_planner import MetricCandidate


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

    async def select_metric_plan(
        self,
        goal: str,
        candidates: list[MetricCandidate],
        requested_dimensions: list[str],
        requested_time_grain: str | None,
    ) -> dict[str, Any]: ...


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
                    "contract": resource.contract.model_dump(mode="json"),
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

    async def select_metric_plan(
        self,
        goal: str,
        candidates: list[MetricCandidate],
        requested_dimensions: list[str],
        requested_time_grain: str | None,
    ) -> dict[str, Any]:
        """Select an approved metric definition; never ask Jev to write SQL."""
        from typesafe_sdk import Choice, Noul

        if not candidates:
            raise ValueError("metric selection requires at least one candidate")
        candidate_criteria = {
            str(candidate["candidate_id"]): {
                "label": str(candidate["label"]),
                "description": str(candidate["description"]),
                "domain": str(candidate["domain"]),
                "population": str(candidate["population"]),
                "grain": str(candidate["grain"]),
                "relation": str(candidate["relation"]),
                "dimensions": list(candidate["dimensions"]),
            }
            for candidate in candidates[:50]
        }
        dimensions = sorted(
            {
                name
                for candidate in candidates
                for name in candidate.get("dimensions", {})
            }
        )
        grains = sorted(
            {
                grain
                for candidate in candidates
                for grain in candidate.get("supported_grains", [])
            }
        )
        questions: dict[str, Any] = {
            "metric": Choice(
                instructions=(
                    "Which approved metric definition best answers the user's metric question? "
                    "Choose only a candidate whose population, grain, relation, and dimensions "
                    "match the question. Never choose a definition merely because its label shares "
                    "a word with the question."
                ),
                criteria=candidate_criteria,
            )
        }
        for index, dimension in enumerate(dimensions):
            questions[f"dimension_{index}"] = Noul(
                instructions=(
                    f"Does the user's metric question require grouping by the approved dimension "
                    f"`{dimension}`? Treat an explicit 'by {dimension}' or an equivalent business "
                    "phrase as positive evidence."
                ),
                criteria={
                    "true": f"The answer must be broken out by {dimension}.",
                    "false": f"The answer does not need a {dimension} breakdown.",
                },
            )
        if requested_time_grain is None and grains:
            questions["time_grain"] = Choice(
                instructions="Which approved time grain best matches the user's metric question?",
                criteria={grain: f"Group the metric by {grain}." for grain in grains},
            )

        state = {
            "goal": goal,
            "requested_dimensions": requested_dimensions,
            "requested_time_grain": requested_time_grain,
            "metric_candidates": [dict(candidate) for candidate in candidates[:50]],
        }
        async with self._client_type(api_key=self._api_key, timeout=self._timeout) as client:
            response = await client.system_one(state=state, questions=questions)
        self.metrics.record(response)
        metric_answer = response.choices["metric"]
        selected_dimensions = list(requested_dimensions)
        if not selected_dimensions:
            selected_dimensions = [
                dimension
                for index, dimension in enumerate(dimensions)
                if response.nouls[f"dimension_{index}"].noul >= 0.60
            ]
        selected_grain = requested_time_grain
        if selected_grain is None and "time_grain" in response.choices:
            selected_grain = response.choices["time_grain"].choice
        return {
            "candidate_id": metric_answer.choice,
            "probability": metric_answer.probabilities.get(metric_answer.choice, 0.0),
            "dimensions": selected_dimensions,
            "time_grain": selected_grain,
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
        from typesafe_sdk import Choice, Noul

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
        outcome_criteria: dict[str, str] = {}
        for outcome in action_outcomes:
            methods = [method for method in card.delivery_methods if method.outcome == outcome]
            if outcome == Outcome.IGNORE:
                condition = (
                    "The evidence is non-actionable for this card's stated purpose. Read the "
                    "owner-authored card guidance closely: if it says a movement is expected, "
                    "normal, seasonal, explainable, within range, or should not create a "
                    "notification, that guidance is positive evidence for ignore when the "
                    "related observations support it. A large numeric movement alone is not "
                    "enough to notify when the card's context explains it."
                )
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
            outcome_criteria[outcome.value] = condition

        # Outcomes are mutually exclusive. Use one Choice rather than separate
        # Nouls: independent yes/no probabilities are not a normalized decision
        # distribution and can make a benign case look like investigation simply
        # because several conditions are moderately plausible.
        questions["outcome"] = Choice(
            instructions=(
                "Which single outcome best fits the current evidence and the owner's "
                "card purpose? Choose only from the allowed outcomes. Treat an outcome "
                "as unavailable if its delivery route is not configured. Do not invent "
                "facts, sources, or destinations."
            ),
            criteria=outcome_criteria,
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
        selected_outcome = str(response.choices["outcome"].choice)
        raw_probabilities = getattr(response.choices["outcome"], "probabilities", {})
        action_probabilities = {
            outcome.value: max(0.0, min(1.0, float(raw_probabilities.get(outcome.value, 0.0))))
            for outcome in action_outcomes
        }
        if selected_outcome not in action_probabilities:
            selected_outcome = Outcome.INVESTIGATE.value
        selected_probability = action_probabilities.get(selected_outcome, 0.0)
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
