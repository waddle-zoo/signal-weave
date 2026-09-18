from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluations.cases import load_evaluation_cases
from signalweave.engine import InsightEngine
from signalweave.models import InsightResult, Outcome
from signalweave.typesafe_adapter import JevJudger, load_api_key


@dataclass(frozen=True)
class ProofResult:
    scenario: str
    card: str
    outcome: str
    confidence: float | None
    delivery_methods: list[str]
    expected_outcome: str | None
    expected_delivery_methods: list[str]
    passed: bool | None
    elapsed_ms: float
    rationale: str
    watch_results: list[dict[str, Any]]
    question_results: list[dict[str, Any]]
    evidence: list[dict[str, Any]]

    @classmethod
    def from_result(
        cls,
        scenario: str,
        card: str,
        result: InsightResult,
        expected: Outcome | None,
        expected_delivery_methods: list[str],
        elapsed_ms: float,
    ) -> ProofResult:
        delivery_methods = [method.key for method in result.delivery_methods]
        return cls(
            scenario=scenario,
            card=card,
            outcome=result.outcome.value,
            confidence=result.confidence,
            delivery_methods=delivery_methods,
            expected_outcome=expected.value if expected else None,
            expected_delivery_methods=expected_delivery_methods,
            passed=(
                result.outcome == expected
                and delivery_methods == expected_delivery_methods
            )
            if expected
            else None,
            elapsed_ms=round(elapsed_ms, 2),
            rationale=result.rationale,
            watch_results=[item.model_dump(mode="json") for item in result.watch_results],
            question_results=[item.model_dump(mode="json") for item in result.question_results],
            evidence=[item.model_dump(mode="json") for item in result.evidence],
        )

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


async def run_labeled_proof() -> list[ProofResult]:
    """Run labeled evaluation cases through the same engine used by the service."""
    api_key = load_api_key()
    if not api_key:
        raise RuntimeError("Jev proof requires TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE")
    judger = JevJudger(api_key=api_key)
    engine = InsightEngine(judger=judger)
    cases = load_evaluation_cases()
    results: list[ProofResult] = []
    for case in sorted(cases, key=lambda item: item.id):
        started = time.perf_counter()
        run = await engine.evaluate(case.card, case.resources)
        elapsed_ms = (time.perf_counter() - started) * 1000
        results.append(
            ProofResult.from_result(
                scenario=case.id,
                card=case.card.title,
                result=run.result,
                expected=Outcome(case.expected_outcome),
                expected_delivery_methods=case.expected_delivery_methods,
                elapsed_ms=elapsed_ms,
            )
        )
    return results


def run_labeled_proof_sync() -> list[ProofResult]:
    return asyncio.run(run_labeled_proof())


def render_table(results: list[ProofResult]) -> str:
    lines = [
        "scenario             outcome          delivery methods       confidence  expected  pass  ms",
        "-------------------  ---------------  ---------------------  ----------  --------  ----  -----",
    ]
    for result in results:
        confidence = f"{result.confidence:.2f}" if result.confidence is not None else "-"
        expected = result.expected_outcome or "-"
        passed = "yes" if result.passed else "-" if result.passed is None else "NO"
        methods = ",".join(result.delivery_methods) or "-"
        lines.append(
            f"{result.scenario:<19}  {result.outcome:<15}  "
            f"{methods:<21}  {confidence:>10}  {expected:<8}  "
            f"{passed:<4}  {result.elapsed_ms:>5.1f}"
        )
    return "\n".join(lines)


def render_markdown(results: list[ProofResult], mode: str) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# SignalWeave Jev proof run",
        "",
        f"- Mode: `{mode}`",
        f"- Generated: `{generated}`",
        "- Result: **live typed classifications recorded**",
        "",
        "This report runs the same engine used by the MCP and push webhook over four representative company situations.",
        "This is a live Jev run over external demo inputs. The labels are useful for review, but four synthetic cases are not a general accuracy claim; use the benchmark harness on labeled production history.",
        "",
        "| Scenario | Outcome | Delivery methods | Confidence | Expected | Time |",
        "| --- | --- | --- | ---: | --- | ---: |",
    ]
    for result in results:
        expected = result.expected_outcome or "—"
        confidence = f"{result.confidence:.2f}" if result.confidence is not None else "—"
        methods = ", ".join(result.delivery_methods) or "—"
        lines.append(
            f"| `{result.scenario}` | `{result.outcome}` | `{methods}` | "
            f"{confidence} | `{expected}` | {result.elapsed_ms:.1f} ms |"
        )
    lines.extend(["", "## Typed findings", ""])
    for result in results:
        lines.append(f"### {result.scenario}")
        lines.append("")
        lines.append(result.rationale)
        lines.append("")
        if result.watch_results:
            lines.append("Watch items:")
            lines.extend(
                f"- `{item['key']}` `{item['status']}` ({item['probability']:.2f}): {item['watch_for']}"
                for item in result.watch_results
            )
            lines.append("")
        if result.question_results:
            lines.append("Questions:")
            lines.extend(
                f"- `{item['key']}` `{item['status']}` ({item['probability']:.2f}): {item['question']}"
                for item in result.question_results
            )
            lines.append("")
        for item in result.evidence:
            values = item.get("values", {})
            lines.append(
                f"- **{item['subject_label']}**: {item['statement']} "
                f"(`current={values.get('current')}`, `baseline={values.get('baseline')}`, "
                f"`change_pct={values.get('change_pct')}`)"
            )
        lines.append("")
    return "\n".join(lines)


def write_report(results: list[ProofResult], mode: str, output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(results, mode) + "\n")
    return path
