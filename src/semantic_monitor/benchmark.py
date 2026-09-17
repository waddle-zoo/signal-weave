"""Reproducible decision-quality benchmark for SignalWeave evaluators."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from statistics import median
from typing import Any

from .baseline import EmbeddingReasoningJudger
from .demo import load_demo_cases
from .engine import MonitorEngine
from .models import Outcome
from .typesafe_adapter import JevJudger, JudgerMetrics, load_api_key

SUPPORTED_SYSTEMS = {"jev", "embedding-reasoning"}


@dataclass(frozen=True)
class BenchmarkResult:
    system: str
    scenario: str
    outcome: str
    recipient: str | None
    expected_outcome: str
    expected_recipient: str | None
    outcome_correct: bool
    decision_correct: bool
    elapsed_ms: float
    requests: int
    input_tokens: int
    output_tokens: int
    error: str | None = None

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def _metrics(judger: Any) -> JudgerMetrics:
    current = getattr(judger, "metrics", None)
    if current is None:
        return JudgerMetrics()
    return JudgerMetrics(
        requests=current.requests,
        input_tokens=current.input_tokens,
        output_tokens=current.output_tokens,
    )


def _metric_delta(before: JudgerMetrics, after: JudgerMetrics) -> tuple[int, int, int]:
    return (
        after.requests - before.requests,
        after.input_tokens - before.input_tokens,
        after.output_tokens - before.output_tokens,
    )


def _build_judger(system: str) -> Any:
    if system == "jev":
        key = load_api_key()
        if not key:
            raise RuntimeError("Jev benchmark requires TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE")
        return JevJudger(api_key=key)
    if system == "embedding-reasoning":
        base_url = os.getenv("BASELINE_BASE_URL")
        if not base_url:
            raise RuntimeError(
                "embedding-reasoning benchmark requires BASELINE_BASE_URL "
                "(an OpenAI-compatible API root)"
            )
        return EmbeddingReasoningJudger(
            base_url=base_url,
            model=os.getenv("BASELINE_MODEL", "luna"),
            embedding_model=os.getenv("BASELINE_EMBEDDING_MODEL", "text-embedding-3-small"),
            api_key=os.getenv("BASELINE_API_KEY"),
            top_k=int(os.getenv("BASELINE_TOP_K", "8")),
        )
    raise ValueError(f"Unsupported benchmark system: {system}")


async def run_fixture_benchmark(
    systems: list[str] | tuple[str, ...] = ("jev",), repeats: int = 1
) -> list[BenchmarkResult]:
    """Run every system on the same four labeled dashboard situations."""
    if repeats < 1 or repeats > 100:
        raise ValueError("repeats must be between 1 and 100")
    unknown = set(systems) - SUPPORTED_SYSTEMS
    if unknown:
        raise ValueError(f"Unsupported benchmark systems: {sorted(unknown)}")

    cases = load_demo_cases()
    results: list[BenchmarkResult] = []
    for system in systems:
        judger = _build_judger(system)
        engine = MonitorEngine(judger=judger)
        for repeat in range(repeats):
            del repeat
            for case in cases:
                scenario = case.id
                dashboard = case.dashboard
                card = case.monitor_card
                expected_outcome = Outcome(case.expected_outcome)
                expected_recipient = case.expected_recipient
                before = _metrics(judger)
                started = time.perf_counter()
                try:
                    evaluation = await engine.evaluate(dashboard, card)
                    decision = evaluation.decision
                    outcome = decision.outcome.value
                    recipient = decision.recipient_key
                    error = None
                except Exception as exc:  # noqa: BLE001 - benchmark must record provider failures
                    outcome = Outcome.INSUFFICIENT_DATA.value
                    recipient = None
                    error = f"{type(exc).__name__}: {exc}"
                elapsed_ms = (time.perf_counter() - started) * 1000
                requests, input_tokens, output_tokens = _metric_delta(before, _metrics(judger))
                results.append(
                    BenchmarkResult(
                        system=system,
                        scenario=scenario,
                        outcome=outcome,
                        recipient=recipient,
                        expected_outcome=expected_outcome.value,
                        expected_recipient=expected_recipient,
                        outcome_correct=outcome == expected_outcome.value,
                        decision_correct=(
                            outcome == expected_outcome.value and recipient == expected_recipient
                        ),
                        elapsed_ms=round(elapsed_ms, 2),
                        requests=requests,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        error=error,
                    )
                )
    return results


def run_fixture_benchmark_sync(
    systems: list[str] | tuple[str, ...] = ("jev",), repeats: int = 1
) -> list[BenchmarkResult]:
    return asyncio.run(run_fixture_benchmark(systems, repeats))


def _summary(results: list[BenchmarkResult], system: str) -> dict[str, Any]:
    rows = [result for result in results if result.system == system]
    latencies = sorted(result.elapsed_ms for result in rows)
    p95 = latencies[max(0, ceil(len(latencies) * 0.95) - 1)] if latencies else 0.0
    return {
        "system": system,
        "cases": len(rows),
        "outcome_accuracy": round(
            sum(result.outcome_correct for result in rows) / len(rows), 3
        )
        if rows
        else 0.0,
        "decision_accuracy": round(
            sum(result.decision_correct for result in rows) / len(rows), 3
        )
        if rows
        else 0.0,
        "median_ms": round(median(latencies), 2) if latencies else 0.0,
        "p95_ms": round(p95, 2),
        "requests": sum(result.requests for result in rows),
        "input_tokens": sum(result.input_tokens for result in rows),
        "output_tokens": sum(result.output_tokens for result in rows),
        "errors": sum(result.error is not None for result in rows),
    }


def render_benchmark_table(results: list[BenchmarkResult]) -> str:
    systems = list(dict.fromkeys(result.system for result in results))
    lines = [
        "system                 cases  outcome  decision  median_ms  p95_ms  requests  errors",
        "---------------------  -----  -------  --------  ---------  ------  --------  ------",
    ]
    for system in systems:
        summary = _summary(results, system)
        lines.append(
            f"{system:<21}  {summary['cases']:>5}  {summary['outcome_accuracy']:.1%}  "
            f"{summary['decision_accuracy']:.1%}  {summary['median_ms']:>9.2f}  "
            f"{summary['p95_ms']:>6.2f}  {summary['requests']:>8}  {summary['errors']:>6}"
        )
    lines.extend(
        [
            "",
            "system                 scenario             outcome          recipient              expected  exact",
            "---------------------  -------------------  ---------------  ---------------------  --------  -----",
        ]
    )
    for result in results:
        lines.append(
            f"{result.system:<21}  {result.scenario:<19}  {result.outcome:<15}  "
            f"{(result.recipient or '-'): <21}  {result.expected_outcome:<8}  "
            f"{'yes' if result.decision_correct else 'NO'}"
        )
    return "\n".join(lines)


def render_benchmark_markdown(results: list[BenchmarkResult]) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    systems = list(dict.fromkeys(result.system for result in results))
    lines = [
        "# SignalWeave evaluator benchmark",
        "",
        f"- Generated: `{generated}`",
        f"- Labeled cases: `{len(load_demo_cases())}` per repeat and system",
        "- Gold labels: the intended behavior stored with each case in `examples/demo-cases.json`",
        "",
        "This is a local decision-quality benchmark, not a claim of universal model accuracy. "
        "Every system receives the same monitor card, normalized observations, evidence, allowed outcomes, "
        "and recipient allowlist. The engine applies the same safety gates after each judgment.",
        "",
        "## Summary",
        "",
        "| System | Cases | Outcome accuracy | Exact decision accuracy | Median | p95 | Requests | Errors |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for system in systems:
        summary = _summary(results, system)
        lines.append(
            f"| `{system}` | {summary['cases']} | {summary['outcome_accuracy']:.1%} | "
            f"{summary['decision_accuracy']:.1%} | {summary['median_ms']:.2f} ms | "
            f"{summary['p95_ms']:.2f} ms | {summary['requests']} | {summary['errors']} |"
        )
    lines.extend(
        [
            "",
            "## Case results",
            "",
            "| System | Scenario | Outcome | Recipient | Expected | Exact | Time | Error |",
            "| --- | --- | --- | --- | --- | :---: | ---: | --- |",
        ]
    )
    for result in results:
        lines.append(
            f"| `{result.system}` | `{result.scenario}` | `{result.outcome}` | "
            f"`{result.recipient or '—'}` | `{result.expected_outcome}` / "
            f"`{result.expected_recipient or '—'}` | "
            f"{'yes' if result.decision_correct else 'NO'} | {result.elapsed_ms:.2f} ms | "
            f"{result.error or '—'} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `jev` is the product path: Jev supplies typed semantic judgments and the same code owns calculations, evidence, routing, and safety gates.",
            "- `embedding-reasoning` is an optional OpenAI-compatible baseline: it embeds the same dashboard observations, retrieves the top cards, and asks a general model for JSON. Set `BASELINE_BASE_URL`, `BASELINE_MODEL`, and `BASELINE_EMBEDDING_MODEL` to run it against a real provider.",
            "- Do not claim Jev is better from four fixtures alone. Use this harness on a labeled export of real dashboard events and compare accuracy, false alerts, investigation rate, latency, and provider usage.",
        ]
    )
    return "\n".join(lines)


def write_benchmark_report(results: list[BenchmarkResult], output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_benchmark_markdown(results) + "\n")
    return path
