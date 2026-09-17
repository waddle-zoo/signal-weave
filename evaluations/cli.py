"""Command-line entry points for evaluation-only tools."""

from __future__ import annotations

import argparse
import json

from evaluations.benchmark import (
    render_benchmark_markdown,
    render_benchmark_table,
    run_labeled_benchmark_sync,
    write_benchmark_report,
)
from evaluations.proof import render_markdown, render_table, run_labeled_proof_sync, write_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SignalWeave evaluation tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prove = subparsers.add_parser("prove", help="Run live Jev over labeled evaluation cases")
    prove.add_argument("--format", choices=["table", "json", "markdown"], default="table")
    prove.add_argument("--output", help="Write a Markdown proof report to this path")

    benchmark = subparsers.add_parser(
        "benchmark", help="Compare Jev with an optional embedding-plus-reasoning baseline"
    )
    benchmark.add_argument(
        "--systems",
        default="jev",
        help="Comma-separated systems: jev, openai, embedding-reasoning",
    )
    benchmark.add_argument("--repeats", type=int, default=1)
    benchmark.add_argument("--format", choices=["table", "json", "markdown"], default="table")
    benchmark.add_argument("--output", help="Write a Markdown benchmark report to this path")

    args = parser.parse_args()
    if args.command == "prove":
        results = run_labeled_proof_sync()
        if args.output:
            write_report(results, "jev", args.output)
        if args.format == "json":
            print(json.dumps([result.as_json() for result in results], indent=2))
        elif args.format == "markdown":
            print(render_markdown(results, "jev"))
        else:
            print(render_table(results))
        return

    systems = [system.strip() for system in args.systems.split(",") if system.strip()]
    results = run_labeled_benchmark_sync(systems, args.repeats)
    if args.output:
        write_benchmark_report(results, args.output)
    if args.format == "json":
        print(json.dumps([result.as_json() for result in results], indent=2))
    elif args.format == "markdown":
        print(render_benchmark_markdown(results))
    else:
        print(render_benchmark_table(results))


if __name__ == "__main__":
    main()
