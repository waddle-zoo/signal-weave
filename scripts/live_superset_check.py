"""Evaluate a user-supplied monitor card against a live Superset dashboard.

Unlike the labeled evaluation tools, this command has no expected outcome and
does not import evaluation fixtures. It proves that the deployed source adapter,
owner card, Jev adapter, safety gates, and evidence contract work together on an
external dashboard.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import signal
import sys
from pathlib import Path
from typing import Any

from semantic_monitor.models import MonitorCard
from semantic_monitor.runtime import build_runtime


async def run(card_path: str | Path, *, verbose: bool = False) -> dict[str, Any]:
    def progress(message: str) -> None:
        if verbose:
            print(message, file=sys.stderr, flush=True)

    progress("loading owner monitor card")
    card = MonitorCard.model_validate(json.loads(Path(card_path).read_text()))
    progress(f"fetching Superset dashboard {card.dashboard_id}")
    runtime = build_runtime()
    dashboard = runtime.store.get_dashboard(
        card.dashboard_id,
        chart_ids=card.chart_ids or None,
        include_data=True,
    )
    if inspect.isawaitable(dashboard):
        dashboard = await dashboard
    if not dashboard.charts:
        raise RuntimeError("Superset returned no charts for the monitor card")

    progress(f"evaluating {len(dashboard.charts)} charts with Jev")
    evaluation = await runtime.engine.evaluate(dashboard, card)
    decision = evaluation.decision
    if decision.evaluator != "jev-latest":
        raise RuntimeError(f"unexpected evaluator: {decision.evaluator}")
    if not decision.evidence:
        raise RuntimeError("evaluation returned no evidence")

    return {
        "source": "superset",
        "dashboard": {
            "id": dashboard.id,
            "title": dashboard.title,
            "chart_count": len(dashboard.charts),
        },
        "monitor": {
            "id": card.id,
            "title": card.title,
            "owner_defined": True,
            "chart_ids": card.chart_ids,
        },
        "plan": evaluation.plan.model_dump(mode="json"),
        "decision": decision.model_dump(mode="json"),
        "proof": {
            "live_source": True,
            "jev_evaluator": True,
            "evidence_count": len(decision.evidence),
            "expected_outcome_supplied": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--monitor-card",
        required=True,
        help="JSON monitor card containing the live dashboard ID and owner policy",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="Maximum seconds for the complete acceptance check (default: 90)",
    )
    parser.add_argument("--verbose", action="store_true", help="Print progress to stderr")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    def alarm_handler(signum: int, frame: Any) -> None:
        del signum, frame
        raise TimeoutError

    alarm_enabled = hasattr(signal, "SIGALRM")
    if alarm_enabled:
        signal.signal(signal.SIGALRM, alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, args.timeout)
    try:
        payload = asyncio.run(
            asyncio.wait_for(run(args.monitor_card, verbose=args.verbose), timeout=args.timeout)
        )
    except TimeoutError as error:
        raise SystemExit(f"live Superset acceptance check timed out after {args.timeout:g}s") from error
    finally:
        if alarm_enabled:
            signal.setitimer(signal.ITIMER_REAL, 0)
    rendered = json.dumps(payload, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered)


if __name__ == "__main__":
    main()
