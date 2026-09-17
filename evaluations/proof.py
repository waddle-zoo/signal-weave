from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluations.cases import load_evaluation_cases
from semantic_monitor.engine import MonitorEngine
from semantic_monitor.models import Decision, Outcome
from semantic_monitor.typesafe_adapter import JevJudger, load_api_key


@dataclass(frozen=True)
class ProofResult:
    scenario: str
    workflow: str
    outcome: str
    confidence: float | None
    recipient: str | None
    expected: str | None
    passed: bool | None
    elapsed_ms: float
    rationale: str
    evidence: list[dict[str, Any]]

    @classmethod
    def from_decision(
        cls,
        scenario: str,
        workflow: str,
        decision: Decision,
        expected: Outcome | None,
        elapsed_ms: float,
    ) -> ProofResult:
        return cls(
            scenario=scenario,
            workflow=workflow,
            outcome=decision.outcome.value,
            confidence=decision.confidence,
            recipient=decision.recipient_key,
            expected=expected.value if expected else None,
            passed=(decision.outcome == expected) if expected else None,
            elapsed_ms=round(elapsed_ms, 2),
            rationale=decision.rationale,
            evidence=[item.model_dump(mode="json") for item in decision.evidence],
        )

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


async def run_labeled_proof() -> list[ProofResult]:
    """Run evaluation cases through the same engine used by the service."""
    api_key = load_api_key()
    if not api_key:
        raise RuntimeError("Jev proof requires TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE")
    judger = JevJudger(api_key=api_key)
    engine = MonitorEngine(judger=judger)
    cases = load_evaluation_cases()
    expected_by_scenario = {case.id: Outcome(case.expected_outcome) for case in cases}
    results: list[ProofResult] = []
    for case in sorted(cases, key=lambda item: item.id):
        scenario = case.id
        workflow = case.workflow
        started = time.perf_counter()
        evaluation = await engine.evaluate(workflow, case.resources)
        elapsed_ms = (time.perf_counter() - started) * 1000
        expected = expected_by_scenario.get(scenario)
        results.append(
            ProofResult.from_decision(
                scenario=scenario,
                workflow=workflow.title,
                decision=evaluation.decision,
                expected=expected,
                elapsed_ms=elapsed_ms,
            )
        )
    return results


def run_labeled_proof_sync() -> list[ProofResult]:
    return asyncio.run(run_labeled_proof())


def render_table(results: list[ProofResult]) -> str:
    lines = [
        "scenario             outcome          recipient              confidence  expected  pass  ms",
        "-------------------  ---------------  ---------------------  ----------  --------  ----  -----",
    ]
    for result in results:
        confidence = f"{result.confidence:.2f}" if result.confidence is not None else "-"
        expected = result.expected or "-"
        passed = "yes" if result.passed else "-" if result.passed is None else "NO"
        lines.append(
            f"{result.scenario:<19}  {result.outcome:<15}  "
            f"{(result.recipient or '-'):<21}  {confidence:>10}  {expected:<8}  "
            f"{passed:<4}  {result.elapsed_ms:>5.1f}"
        )
    return "\n".join(lines)


def render_markdown(results: list[ProofResult], mode: str) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    checks = "live typed classifications recorded"
    lines = [
        "# Semantic monitor proof run",
        "",
        f"- Mode: `{mode}`",
        f"- Generated: `{generated}`",
        f"- Result: **{checks}**",
        "",
        "This report runs the same engine used by the MCP and push webhook over four representative company situations.",
        "This is a live Jev run over external demo inputs. The labels are useful for review, but four synthetic cases are not a general accuracy claim; use the benchmark harness on labeled production history.",
        "",
        "| Scenario | Outcome | Recipient | Confidence | Expected | Time |",
        "| --- | --- | --- | ---: | --- | ---: |",
    ]
    for result in results:
        expected = result.expected or "—"
        confidence = f"{result.confidence:.2f}" if result.confidence is not None else "—"
        lines.append(
            f"| `{result.scenario}` | `{result.outcome}` | `{result.recipient or '—'}` | "
            f"{confidence} | `{expected}` | {result.elapsed_ms:.1f} ms |"
        )
    lines.extend(["", "## Evidence", ""])
    for result in results:
        lines.append(f"### {result.scenario}")
        lines.append("")
        lines.append(result.rationale)
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
