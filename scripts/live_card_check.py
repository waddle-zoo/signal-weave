"""Evaluate a user-supplied insight card against its live source adapters.

This command has no expected outcome and does not import evaluation fixtures. It
proves that a user-authored card, installed source adapters, Jev adapter, safety
gates, and evidence contract work together on live inputs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from pathlib import Path
from typing import Any

from signalweave.models import InsightCard
from signalweave.runtime import build_runtime


async def run(card_path: str | Path, *, verbose: bool = False) -> dict[str, Any]:
    def progress(message: str) -> None:
        if verbose:
            print(message, file=sys.stderr, flush=True)

    progress("loading insight card")
    card = InsightCard.model_validate(json.loads(Path(card_path).read_text()))
    runtime = build_runtime()
    missing_adapters = sorted(
        {source.adapter for source in card.sources} - set(runtime.sources.adapter_names())
    )
    if missing_adapters:
        raise RuntimeError(
            "card references source adapters that are not installed: "
            + ", ".join(missing_adapters)
        )

    progress(
        f"fetching {len(card.sources)} source(s): "
        + ", ".join(f"{source.key}={source.adapter}" for source in card.sources)
    )
    run_result = await runtime.engine.evaluate(card)
    result = run_result.result
    if result.evaluator != "jev-latest":
        raise RuntimeError(f"unexpected evaluator: {result.evaluator}")
    if not result.evidence:
        raise RuntimeError("evaluation returned no evidence")

    return {
        "sources": [
            {
                "key": source.key,
                "adapter": source.adapter,
                "resource": source.resource,
                "title": snapshot.title,
                "observation_count": len(snapshot.observations),
                "error": snapshot.error,
            }
            for source in card.sources
            for snapshot in run_result.resources
            if snapshot.source_key == source.key
        ],
        "card": card.model_dump(mode="json"),
        "plan": run_result.plan.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
        "proof": {
            "live_sources": True,
            "installed_adapters": runtime.sources.adapter_names(),
            "jev_evaluator": True,
            "evidence_count": len(result.evidence),
            "expected_outcome_supplied": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--card",
        required=True,
        help="JSON insight card containing source references and author guidance",
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
            asyncio.wait_for(run(args.card, verbose=args.verbose), timeout=args.timeout)
        )
    except TimeoutError as error:
        raise SystemExit(f"live card acceptance check timed out after {args.timeout:g}s") from error
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
