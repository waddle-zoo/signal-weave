from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Decision, Outcome
from .runtime import build_runtime

EXPECTED_HEURISTIC_OUTCOMES = {
    "data_freshness": Outcome.ESCALATE,
    "mobile_conversion": Outcome.NOTIFY,
    "revenue_decline": Outcome.NOTIFY,
    "seasonal_normal": Outcome.IGNORE,
}


@dataclass(frozen=True)
class ProofResult:
    scenario: str
    dashboard: str
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
        dashboard: str,
        decision: Decision,
        expected: Outcome | None,
        elapsed_ms: float,
    ) -> ProofResult:
        return cls(
            scenario=scenario,
            dashboard=dashboard,
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


async def run_fixture_proof(mode: str = "heuristic") -> list[ProofResult]:
    """Run the deterministic company scenarios through the production engine."""
    runtime = build_runtime(mode=mode, source="fixtures")
    results: list[ProofResult] = []
    for scenario in sorted(runtime.store.dashboards):
        dashboard = runtime.store.get_dashboard_by_scenario(scenario)
        card = next(card for card in runtime.store.list_cards() if card.dashboard_id == dashboard.id)
        started = time.perf_counter()
        evaluation = await runtime.engine.evaluate(dashboard, card)
        elapsed_ms = (time.perf_counter() - started) * 1000
        expected = EXPECTED_HEURISTIC_OUTCOMES.get(scenario) if mode == "heuristic" else None
        results.append(
            ProofResult.from_decision(
                scenario=scenario,
                dashboard=dashboard.title,
                decision=evaluation.decision,
                expected=expected,
                elapsed_ms=elapsed_ms,
            )
        )
    return results


def run_fixture_proof_sync(mode: str = "heuristic") -> list[ProofResult]:
    return asyncio.run(run_fixture_proof(mode))


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
    passed = sum(result.passed is True for result in results)
    checks = f"{passed}/{len(results)} expected outcomes" if mode == "heuristic" else "semantic classifications recorded"
    lines = [
        "# Semantic monitor proof run",
        "",
        f"- Mode: `{mode}`",
        f"- Generated: `{generated}`",
        f"- Result: **{checks}**",
        "",
        "This report runs the same engine used by the MCP and push webhook over four representative company situations.",
        "The heuristic run is fully offline and has exact expected outcomes. Jev runs record the live typed judgment; confidence gates remain in the engine.",
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
                f"- **{item['chart_title']}**: {item['statement']} "
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
