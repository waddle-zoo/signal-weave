"""Run the frozen owner-labeled card-guided Jev holdout.

The card catalog and the owner labels are separate files.  Labels are loaded
only by the evaluator and are attached to the in-memory score object; they are
never added to the card, catalog descriptors, snapshots, or Jev state.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from signalweave.engine import InsightEngine
from signalweave.models import PrincipalContext
from signalweave.onboarding import InsightAuthoringService
from signalweave.sources import SourceRegistry
from signalweave.typesafe_adapter import JevJudger, load_api_key

try:
    from evaluations.card_guided_retrieval_benchmark import (
        DashboardChartAdapter,
        Usage,
        _aggregate,
        _cost,
        _evaluate_selection,
        _goal,
        _lexical_ids,
        _load_config,
        _score,
        _selected_ids,
        _usage_delta,
        build_cases,
    )
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    from card_guided_retrieval_benchmark import (
        DashboardChartAdapter,
        Usage,
        _aggregate,
        _cost,
        _evaluate_selection,
        _goal,
        _lexical_ids,
        _load_config,
        _score,
        _selected_ids,
        _usage_delta,
        build_cases,
    )

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "evaluations" / "data" / "card-guided-owner-holdout.json"
DEFAULT_LABELS = ROOT / "evaluations" / "data" / "card-guided-owner-holdout-labels.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "card-guided-owner-holdout.json"
ALLOWED_ROLES = {"driver", "corroborates", "diagnostic", "quality", "contradicts"}


def load_holdout_cases(config_path: Path, labels_path: Path) -> list[Any]:
    config = _load_config(config_path)
    labels = json.loads(labels_path.read_text())
    if labels.get("schema_version") != 1:
        raise ValueError("owner holdout labels must have schema_version=1")
    label_cases = labels.get("cases", {})
    cases = build_cases(config, repeats=1)
    if set(label_cases) != {case.scenario_id for case in cases}:
        raise ValueError("owner holdout labels must cover exactly the configured scenarios")

    labeled: list[Any] = []
    for case in cases:
        raw_case = label_cases[case.scenario_id]
        expected_chart_ids = {
            descriptor.metadata.get("chart_id")
            for descriptor in case.descriptors
            if descriptor.kind == "chart"
        }
        if not set(raw_case) or not set(raw_case).issubset(expected_chart_ids):
            raise ValueError(f"owner labels must identify relevant charts in {case.scenario_id}")
        retrieval_roles: dict[str, str] = {}
        evidence_roles: dict[str, str] = {}
        for chart_id, item in raw_case.items():
            retrieval_role = str(item.get("retrieval_role", ""))
            evidence_role = str(item.get("evidence_role", ""))
            if retrieval_role not in ALLOWED_ROLES or evidence_role not in {
                *ALLOWED_ROLES,
                "unrelated",
                "unknown",
            }:
                raise ValueError(f"invalid owner label for {case.scenario_id}/{chart_id}")
            retrieval_roles[chart_id] = retrieval_role
            evidence_roles[chart_id] = evidence_role
        labeled.append(
            replace(
                case,
                gold_roles=retrieval_roles,
                gold_evidence_roles=evidence_roles,
            )
        )
    return labeled


async def run_holdout(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_holdout_cases(args.config, args.labels)
    key = load_api_key(str(args.typesafe_key_file) if args.typesafe_key_file else None)
    if not key:
        raise RuntimeError("a TypeSafe key is required; pass --typesafe-key-file or set TYPESAFE_API_KEY")
    judger = JevJudger(api_key=key, timeout=args.timeout)
    arm_rows: dict[str, list[dict[str, Any]]] = {
        "jev-card-guided": [],
        "lexical-selection": [],
        "gold-selection-jev": [],
    }

    for case in cases:
        adapter = DashboardChartAdapter(case)
        registry = SourceRegistry([adapter], authorized_tenants={"northstar"})
        engine = InsightEngine(judger=judger, registry=registry)
        service = InsightAuthoringService(
            registry=registry,
            engine=engine,
            max_candidates=args.max_candidates,
            recommendation_threshold=args.recommendation_threshold,
            principal=PrincipalContext(
                principal_id="owner-holdout-agent",
                tenant_id="northstar",
                authorization_source="owner-holdout",
            ),
        )
        before = Usage(
            judger.metrics.requests,
            judger.metrics.input_tokens,
            judger.metrics.output_tokens,
        )
        started = time.perf_counter()
        discovery = await service.discover(
            _goal(case.card),
            adapter="superset",
            limit=args.retrieval_limit,
            principal=service.principal,
        )
        discovery_elapsed_ms = (time.perf_counter() - started) * 1000
        selections = {
            "jev-card-guided": _selected_ids(discovery.matches, cap=args.selection_cap),
            "lexical-selection": _lexical_ids(case, cap=args.selection_cap),
            "gold-selection-jev": sorted(case.gold_roles),
        }
        for arm, selected_ids in selections.items():
            decision, decision_usage, decision_elapsed_ms = await _evaluate_selection(
                case, selected_ids, engine
            )
            retrieval_usage = _usage_delta(before, judger.metrics)
            usage = retrieval_usage if arm == "jev-card-guided" else decision_usage
            elapsed_ms = (
                discovery_elapsed_ms + decision_elapsed_ms
                if arm == "jev-card-guided"
                else decision_elapsed_ms
            )
            row = _score(case, arm, selected_ids, decision, usage, elapsed_ms)
            row.update(
                {
                    "discovery_candidate_count": discovery.candidate_count,
                    "discovery_returned_count": len(discovery.matches),
                    "discovery_recommended_count": sum(
                        bool(match.recommended) for match in discovery.matches
                    ),
                    "discovery_truncated": discovery.truncated,
                    "discovery_strategy": discovery.candidate_strategy,
                    "discovery_evaluator": discovery.evaluator,
                    "discovery_elapsed_ms": round(discovery_elapsed_ms, 2),
                    "decision_elapsed_ms": round(decision_elapsed_ms, 2),
                }
            )
            arm_rows[arm].append(row)

    arms = {arm: _aggregate(rows) for arm, rows in arm_rows.items()}
    costs = {
        arm: _cost(
            Usage(summary["api_requests"], summary["input_tokens"], summary["output_tokens"]),
            args.typesafe_input_price_per_mtok,
            args.typesafe_output_price_per_mtok,
        )
        for arm, summary in arms.items()
    }
    report = {
        "benchmark": "card-guided-owner-holdout",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "jev-latest",
        "label_source": "independent-owner-review-v1",
        "config": str(args.config.relative_to(ROOT)),
        "labels": str(args.labels.relative_to(ROOT)),
        "cases": len(cases),
        "charts_per_case": _load_config(args.config)["chart_count"],
        "candidate_pool_limit": args.max_candidates,
        "retrieval_limit": args.retrieval_limit,
        "selection_cap": args.selection_cap,
        "recommendation_threshold": args.recommendation_threshold,
        "arms": arms,
        "estimated_costs_usd": costs,
        "rows": [row for rows in arm_rows.values() for row in rows],
        "limitations": [
            "The catalog and owner labels are synthetic; Jev retrieval and decision calls are live.",
            "Owner labels are held outside the Jev-facing card and catalog payloads, but are not labels from a production team.",
            "The cards are intentionally explicit about evidence roles; this does not prove card authoring quality.",
            "Chart metadata represents what a catalog adapter could expose; no raw pixels or SQL are sent.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--typesafe-key-file", type=Path)
    parser.add_argument("--max-candidates", type=int, default=40)
    parser.add_argument("--retrieval-limit", type=int, default=12)
    parser.add_argument("--selection-cap", type=int, default=8)
    parser.add_argument("--recommendation-threshold", type=float, default=0.60)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--typesafe-input-price-per-mtok", type=float, default=0.042)
    parser.add_argument("--typesafe-output-price-per-mtok", type=float, default=0.0)
    args = parser.parse_args()
    report = asyncio.run(run_holdout(args))
    print(json.dumps(report["arms"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
