"""Compare Jev with fixed rules and embedding+LLM on real Northstar rows.

This is an evaluation harness, not product logic. It reads the Northstar seed
rows that back the local Superset instance, keeps their observed distributions,
and replays a small sequence of counterfactual monitoring days. Every arm sees
the same normalized observations and the same free-form card.

The replay is deliberately labeled as counterfactual: the rows are real local
company data, while the day-to-day movements and expected decisions are a
reviewable human rubric. It proves decision behavior over messy evidence; it
does not claim that synthetic perturbations are production labels.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from dotenv import dotenv_values

from evaluations.embedding_baseline import EmbeddingReasoningJudger
from signalweave.compiler import base_plan
from signalweave.engine import InsightEngine
from signalweave.models import (
    DeliveryMethod,
    Evidence,
    InsightCard,
    InsightPlan,
    InsightResult,
    Observation,
    Outcome,
    ResourceContract,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.superset_client import SupersetClient
from signalweave.typesafe_adapter import JevJudger, JudgerMetrics, load_api_key

SALES_SOURCE = "superset|dashboard:1"
FUNNEL_SOURCE = "northstar|fct_web_session"
SUPPORT_SOURCE = "northstar|fct_support_ticket"
FINANCE_SOURCE = "northstar|fct_finance_daily"


@dataclass(frozen=True)
class PeriodData:
    current_month: str
    baseline_month: str
    sales_current: dict[str, float]
    sales_baseline: dict[str, float]
    funnel_current: dict[str, float]
    funnel_baseline: dict[str, float]
    support_current: float
    support_baseline: float
    finance_current: float
    finance_baseline: float
    row_counts: dict[str, int]


@dataclass(frozen=True)
class ReplayCase:
    case_id: str
    description: str
    expected: Outcome
    adjustments: dict[str, float]
    failed_sources: tuple[str, ...] = ()


class ThresholdJudger:
    """Evaluation-only fixed-rule comparator, not product behavior."""

    name = "fixed-threshold"

    async def compile_plan(self, state: dict[str, Any], card: InsightCard) -> dict[str, Any]:
        plan = base_plan(card)
        return {"capabilities": plan.capabilities, "baseline": plan.comparison_windows[0]}

    async def judge(
        self,
        state: dict[str, Any],
        card: InsightCard,
        plan: InsightPlan,
        observations: list[Observation],
    ) -> InsightResult:
        revenue = _find(observations, "revenue-total")
        channels = [item for item in observations if item.subject_type == "channel"]
        funnel = _find(observations, "conversion-rate")
        revenue_change = revenue.change_pct if revenue else None
        corroborating_channels = sum(
            1 for item in channels if item.change_pct is not None and item.change_pct <= -10
        )
        if revenue_change is None:
            outcome = Outcome.INSUFFICIENT_DATA
            confidence = 0.99
        elif revenue_change <= -15 and corroborating_channels >= 2 and (
            funnel is not None and (funnel.change_pct or 0) <= -10
        ):
            outcome = Outcome.NOTIFY
            confidence = 0.99
        elif revenue_change <= -10:
            outcome = Outcome.INVESTIGATE
            confidence = 0.99
        else:
            outcome = Outcome.IGNORE
            confidence = 0.99
        return InsightResult(
            card_id=card.id,
            outcome=outcome,
            delivery_methods=[
                method for method in card.delivery_methods if method.outcome == outcome
            ],
            summary=f"Fixed rule evaluated {len(observations)} observations.",
            rationale=(
                f"revenue_change={revenue_change!r}, corroborating_channels="
                f"{corroborating_channels}, funnel_change={funnel.change_pct if funnel else None!r}."
            ),
            confidence=confidence,
            probabilities={outcome.value: confidence},
            observations=observations,
            evidence=[Evidence.model_validate(item) for item in state.get("evidence", [])],
            source_keys=plan.selected_source_keys,
            evaluator=self.name,
        )


def _find(observations: list[Observation], subject_id: str) -> Observation | None:
    return next((item for item in observations if item.subject_id == subject_id), None)


def _pct(current: float, baseline: float) -> float:
    if baseline == 0:
        return 0.0
    return round((current - baseline) / abs(baseline) * 100, 3)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_period_data(seed_dir: Path) -> PeriodData:
    sales_rows = _read_csv(seed_dir / "fct_sales_order_line.csv")
    funnel_rows = _read_csv(seed_dir / "fct_web_session.csv")
    support_rows = _read_csv(seed_dir / "fct_support_ticket.csv")
    finance_rows = _read_csv(seed_dir / "fct_finance_daily.csv")

    sales: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in sales_rows:
        month = row["order_date"][:7]
        channel = row["channel"] or "Unknown"
        sales[month]["__total__"] += float(row["net_sales"] or 0)
        sales[month][channel] += float(row["net_sales"] or 0)

    funnel: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in funnel_rows:
        month = row["event_date"][:7]
        funnel[month]["sessions"] += float(row["sessions"] or 0)
        funnel[month]["orders"] += float(row["orders"] or 0)
        funnel[month]["revenue"] += float(row["revenue"] or 0)
    for _month, values in funnel.items():
        values["conversion_rate"] = values["orders"] / values["sessions"] if values["sessions"] else 0

    support: dict[str, list[float]] = defaultdict(list)
    for row in support_rows:
        support[row["event_date"][:7]].append(float(row["backlog"] or 0))

    finance: dict[str, float] = defaultdict(float)
    for row in finance_rows:
        finance[row["event_date"][:7]] += float(row["revenue"] or 0)

    months = sorted(sales)
    if len(months) < 3:
        raise RuntimeError("Northstar sales seed requires at least three months")
    # The latest month is partial in the local trial; use the latest two complete
    # months so the comparison does not mistake month-to-date for a movement.
    current_month, baseline_month = months[-2], months[-3]
    return PeriodData(
        current_month=current_month,
        baseline_month=baseline_month,
        sales_current=dict(sales[current_month]),
        sales_baseline=dict(sales[baseline_month]),
        funnel_current=dict(funnel[current_month]),
        funnel_baseline=dict(funnel[baseline_month]),
        support_current=sum(support[current_month]) / len(support[current_month]),
        support_baseline=sum(support[baseline_month]) / len(support[baseline_month]),
        finance_current=finance[current_month],
        finance_baseline=finance[baseline_month],
        row_counts={
            "sales": len(sales_rows),
            "funnel": len(funnel_rows),
            "support": len(support_rows),
            "finance": len(finance_rows),
        },
    )


def _observation(
    *,
    source_key: str,
    subject_id: str,
    subject_label: str,
    metric: str,
    unit: str,
    current: float,
    baseline: float,
    dimensions: dict[str, Any] | None = None,
    period: PeriodData,
) -> Observation:
    return Observation(
        source_key=source_key,
        subject_id=subject_id,
        subject_label=subject_label,
        subject_type="channel" if "channel" in subject_id else "metric",
        metric=metric,
        unit=unit,
        current=round(current, 4),
        baseline=round(baseline, 4),
        previous=round(baseline, 4),
        change_pct=_pct(current, baseline),
        dimensions={**(dimensions or {}), "current_period": period.current_month},
        freshness=f"fresh; complete month {period.current_month}",
        source_url=(
            "http://127.0.0.1:18089/superset/dashboard/1/"
            if source_key == SALES_SOURCE
            else None
        ),
        attributes={
            "baseline_period": period.baseline_month,
            "data_origin": "Northstar local seed rows backing the warehouse",
        },
    )


def _build_resources(period: PeriodData, case: ReplayCase) -> list[ResourceSnapshot]:
    def adjusted(baseline: float, key: str) -> float:
        """Build a replay day from the observed baseline, not from actual movement."""
        return baseline * (1 + case.adjustments.get(key, 0) / 100)

    channels = sorted(key for key in period.sales_current if key != "__total__")
    observations = [
        _observation(
            source_key=SALES_SOURCE,
            subject_id="revenue-total",
            subject_label="Net sales revenue",
            metric="net_sales",
            unit="currency",
            current=adjusted(period.sales_baseline["__total__"], "revenue"),
            baseline=period.sales_baseline["__total__"],
            dimensions={"grain": "month", "aggregation": "sum"},
            period=period,
        )
    ]
    observations.extend(
        _observation(
            source_key=SALES_SOURCE,
            subject_id=f"channel-{channel.lower()}",
            subject_label=f"Net sales — {channel}",
            metric="net_sales",
            unit="currency",
            current=adjusted(period.sales_baseline[channel], f"channel:{channel}"),
            baseline=period.sales_baseline.get(channel, 0.0),
            dimensions={"channel": channel, "grain": "month", "aggregation": "sum"},
            period=period,
        )
        for channel in channels
        if period.sales_baseline.get(channel, 0.0) > 0
    )
    observations.extend(
        [
            _observation(
                source_key=FUNNEL_SOURCE,
                subject_id="conversion-rate",
                subject_label="Web conversion rate",
                metric="conversion_rate",
                unit="ratio",
                current=adjusted(period.funnel_baseline["conversion_rate"], "conversion_rate"),
                baseline=period.funnel_baseline["conversion_rate"],
                dimensions={"grain": "month", "aggregation": "orders / sessions"},
                period=period,
            ),
            _observation(
                source_key=FUNNEL_SOURCE,
                subject_id="web-sessions",
                subject_label="Web sessions",
                metric="sessions",
                unit="count",
                current=adjusted(period.funnel_baseline["sessions"], "sessions"),
                baseline=period.funnel_baseline["sessions"],
                dimensions={"grain": "month", "aggregation": "sum"},
                period=period,
            ),
            _observation(
                source_key=SUPPORT_SOURCE,
                subject_id="support-backlog",
                subject_label="Support backlog",
                metric="backlog",
                unit="tickets",
                current=adjusted(period.support_baseline, "support_backlog"),
                baseline=period.support_baseline,
                dimensions={"grain": "month", "aggregation": "average across ticket rows"},
                period=period,
            ),
            _observation(
                source_key=FINANCE_SOURCE,
                subject_id="finance-revenue",
                subject_label="Finance booked revenue",
                metric="revenue",
                unit="currency",
                current=adjusted(period.finance_baseline, "finance_revenue"),
                baseline=period.finance_baseline,
                dimensions={"grain": "month", "aggregation": "sum"},
                period=period,
            ),
        ]
    )

    by_source: dict[str, list[Observation]] = defaultdict(list)
    for item in observations:
        by_source[item.source_key].append(item)
    source_titles = {
        SALES_SOURCE: "Northstar Executive Pulse (Superset dashboard 1)",
        FUNNEL_SOURCE: "Northstar Web Funnel",
        SUPPORT_SOURCE: "Northstar Support Operations",
        FINANCE_SOURCE: "Northstar Finance Daily",
    }
    resources: list[ResourceSnapshot] = []
    for source_key, source_observations in by_source.items():
        failed = source_key in case.failed_sources
        resources.append(
            ResourceSnapshot(
                source_key=source_key,
                adapter=source_key.split("|", 1)[0],
                resource=source_key.split("|", 1)[1],
                title=source_titles[source_key],
                description="Real Northstar rows normalized for a shadow monitoring replay.",
                observations=source_observations,
                evidence=[
                    Evidence(
                        source_key=source_key,
                        subject_id=source_key,
                        subject_label=source_titles[source_key],
                        statement=(
                            f"Rows were read from the local Northstar seed backing {source_key}."
                        ),
                        values={"row_count": period.row_counts},
                    )
                ],
                error="source unavailable during replay" if failed else None,
                source_url=(
                    "http://127.0.0.1:18089/superset/dashboard/1/"
                    if source_key == SALES_SOURCE
                    else None
                ),
                metadata={"data_quality": {"status": "failed" if failed else "healthy"}},
                contract=ResourceContract(
                    tenant_id="northstar-outfitters",
                    domain="commerce",
                    source_status="failed" if failed else "healthy",
                ),
            )
        )
    return resources


def _card() -> InsightCard:
    return InsightCard(
        id="northstar-executive-pulse",
        title="Executive pulse: material revenue risk",
        what_to_watch=(
            "Revenue performance and the related signals across sales channels, web funnel, "
            "support operations, and finance."
        ),
        why_watch=(
            "Do not make leaders inspect dashboards every day. Notify leadership only when "
            "a material revenue decline is corroborated across the business; route ambiguous "
            "or conflicting movement to analytics for investigation; ignore ordinary movement."
        ),
        watch_for=[
            "Net sales revenue moves materially below its comparable baseline.",
            "Two or more sales channels corroborate a material revenue decline.",
            "Web conversion or support backlog provides related context for the movement.",
            "Finance and operational sources agree enough to support an automatic route.",
        ],
        questions=[
            "What changed materially and which channels are most relevant?",
            "Is the movement corroborated across the related sources?",
            "Should leadership be notified or should analytics investigate first?",
        ],
        sources=[
            SourceRef(
                key=SALES_SOURCE,
                adapter="superset",
                resource="dashboard:1",
                label="Northstar Executive Pulse",
            ),
            SourceRef(
                key=FUNNEL_SOURCE,
                adapter="warehouse",
                resource="fct_web_session",
                label="Northstar Web Funnel",
            ),
            SourceRef(
                key=SUPPORT_SOURCE,
                adapter="warehouse",
                resource="fct_support_ticket",
                label="Northstar Support Operations",
            ),
            SourceRef(
                key=FINANCE_SOURCE,
                adapter="warehouse",
                resource="fct_finance_daily",
                label="Northstar Finance Daily",
            ),
        ],
        delivery_methods=[
            DeliveryMethod(
                key="leadership",
                outcome=Outcome.NOTIFY,
                label="Notify leadership",
                destination="northstar://leadership",
                instructions="Notify leadership only when the decline is material and corroborated.",
            ),
            DeliveryMethod(
                key="analytics",
                outcome=Outcome.INVESTIGATE,
                label="Route to analytics",
                destination="northstar://analytics",
                instructions="Ask analytics to investigate ambiguous, isolated, or conflicting movement.",
            ),
        ],
        comparison_windows=["previous_period"],
        action_confidence_threshold=0.70,
    )


def _cases() -> list[ReplayCase]:
    return [
        ReplayCase(
            "day-01-no-change",
            "No meaningful movement across the observed sources.",
            Outcome.IGNORE,
            {"revenue": 0, "conversion_rate": 0, "support_backlog": 0, "finance_revenue": 0},
        ),
        ReplayCase(
            "day-02-modest-movement",
            "A small broad movement that should not page leadership.",
            Outcome.IGNORE,
            {
                "revenue": -6,
                "conversion_rate": -4,
                "support_backlog": 3,
                "finance_revenue": -5,
                "channel:Online": -6,
                "channel:Store": -6,
                "channel:Mobile": -6,
                "channel:Marketplace": -6,
            },
        ),
        ReplayCase(
            "day-03-isolated-channel",
            "Top-line movement is concentrated in one channel with no independent corroboration.",
            Outcome.INVESTIGATE,
            {
                "revenue": -18,
                "channel:Online": -35,
                "channel:Store": 1,
                "channel:Mobile": 1,
                "channel:Marketplace": 1,
                "conversion_rate": 0,
                "finance_revenue": 1,
            },
        ),
        ReplayCase(
            "day-04-corroborated-decline",
            "Revenue, multiple channels, funnel conversion, and finance agree on a decline.",
            Outcome.NOTIFY,
            {
                "revenue": -22,
                "channel:Online": -24,
                "channel:Store": -18,
                "channel:Mobile": -20,
                "channel:Marketplace": -16,
                "conversion_rate": -15,
                "sessions": -10,
                "support_backlog": 28,
                "finance_revenue": -21,
            },
        ),
        ReplayCase(
            "day-05-conflicting-sources",
            "Sales moves down while finance and the funnel do not corroborate it.",
            Outcome.INVESTIGATE,
            {
                "revenue": -20,
                "channel:Online": -20,
                "channel:Store": -20,
                "channel:Mobile": -20,
                "channel:Marketplace": -20,
                "conversion_rate": 2,
                "sessions": 4,
                "support_backlog": 0,
                "finance_revenue": 5,
            },
        ),
        ReplayCase(
            "day-06-source-unavailable",
            "The executive source is unavailable; no semantic arm may auto-interpret it.",
            Outcome.INSUFFICIENT_DATA,
            {"revenue": -22, "conversion_rate": -15, "finance_revenue": -21},
            failed_sources=(SALES_SOURCE,),
        ),
    ]


def _metrics(judger: Any) -> JudgerMetrics:
    metrics = getattr(judger, "metrics", None)
    if metrics is None:
        return JudgerMetrics()
    return JudgerMetrics(
        requests=metrics.requests,
        input_tokens=metrics.input_tokens,
        output_tokens=metrics.output_tokens,
    )


def _delta(before: JudgerMetrics, after: JudgerMetrics) -> dict[str, int]:
    return {
        "requests": after.requests - before.requests,
        "input_tokens": after.input_tokens - before.input_tokens,
        "output_tokens": after.output_tokens - before.output_tokens,
    }


def _safe_error(error: Exception) -> str:
    message = str(error)
    if "api key" in message.lower() or "authorization" in message.lower():
        return f"{type(error).__name__}: provider authentication failed"
    return re.sub(r"(?:sk|key)-[A-Za-z0-9_-]{6,}", "[redacted-key]", message)


def _openai_key(dotenv_path: Path | None) -> str | None:
    if os.getenv("OPENAI_API_KEY"):
        return str(os.environ["OPENAI_API_KEY"])
    if dotenv_path and dotenv_path.exists():
        value = dotenv_values(dotenv_path).get("OPENAI_API_KEY")
        return str(value) if value else None
    return None


async def _validate_superset(base_url: str, username: str, password: str, dashboard_id: str) -> dict[str, Any]:
    client = SupersetClient(base_url, username=username, password=password)
    result: dict[str, Any] = {"base_url": base_url, "dashboard_id": dashboard_id}
    try:
        result["health"] = await client.health()
    except Exception as error:  # noqa: BLE001 - evidence should record source failures
        result["health"] = False
        result["health_error"] = f"{type(error).__name__}: {error}"
    try:
        metadata = await client.get_dashboard_metadata(dashboard_id)
        result["metadata"] = "succeeded"
        result["dashboard_title"] = metadata.get("dashboard_title") if isinstance(metadata, dict) else None
    except Exception as error:  # noqa: BLE001 - evidence should record source failures
        result["metadata"] = "failed"
        result["metadata_error"] = f"{type(error).__name__}: {error}"
    if result.get("metadata") == "succeeded":
        try:
            snapshot = await client.dashboard_snapshot(dashboard_id, include_data=True)
            result["chart_count"] = len(snapshot.charts)
            result["charts_with_observations"] = sum(
                1 for chart in snapshot.charts if chart.observations
            )
            result["chart_errors"] = [
                f"{chart.title}: {chart.error}" for chart in snapshot.charts if chart.error
            ]
        except Exception as error:  # noqa: BLE001 - evidence should record source failures
            result["data"] = "failed"
            result["data_error"] = f"{type(error).__name__}: {error}"
        else:
            result["data"] = "succeeded"
    return result


async def _run_arm(
    name: str,
    judger: Any,
    card: InsightCard,
    period: PeriodData,
    cases: list[ReplayCase],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    engine = InsightEngine(judger=judger)
    first_resources = _build_resources(period, cases[0])
    plan = await engine.compile(card, first_resources)
    compiled_card = card.model_copy(update={"compiled_plan": plan})
    rows: list[dict[str, Any]] = []
    for case in cases:
        before = _metrics(judger)
        started = time.perf_counter()
        try:
            run = await engine.evaluate(compiled_card, _build_resources(period, case))
            result = run.result
            error = None
        except Exception as exc:  # noqa: BLE001 - provider failure is a trial result
            result = None
            error = _safe_error(exc)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        request_delta = _delta(before, _metrics(judger))
        outcome = result.outcome.value if result else Outcome.INSUFFICIENT_DATA.value
        row = {
            "case_id": case.case_id,
            "expected": case.expected.value,
            "outcome": outcome,
            "correct": outcome == case.expected.value,
            "delivery_methods": [method.key for method in result.delivery_methods] if result else [],
            "confidence": result.confidence if result else None,
            "elapsed_ms": elapsed_ms,
            "metrics": request_delta,
            "error": error,
            "rationale": result.rationale if result else None,
            "evidence_subjects": [item.subject_label for item in result.evidence] if result else [],
        }
        rows.append(row)
    correct = sum(1 for row in rows if row["correct"])
    elapsed = [row["elapsed_ms"] for row in rows if row["error"] is None]
    false_notify = sum(
        1 for row in rows if row["outcome"] == Outcome.NOTIFY.value and row["expected"] != Outcome.NOTIFY.value
    )
    missed_notify = sum(
        1 for row in rows if row["expected"] == Outcome.NOTIFY.value and row["outcome"] != Outcome.NOTIFY.value
    )
    totals = {
        "cases": len(rows),
        "correct": correct,
        "accuracy": round(correct / len(rows), 3) if rows else 0.0,
        "false_notify": false_notify,
        "missed_notify": missed_notify,
        "median_ms": round(median(elapsed), 2) if elapsed else None,
        "max_ms": round(max(elapsed), 2) if elapsed else None,
        "requests": sum(row["metrics"]["requests"] for row in rows),
        "input_tokens": sum(row["metrics"]["input_tokens"] for row in rows),
        "output_tokens": sum(row["metrics"]["output_tokens"] for row in rows),
    }
    return rows, totals


async def run_trial(
    *,
    seed_dir: Path,
    output: Path,
    typesafe_key_file: Path,
    openai_dotenv: Path | None,
    superset_url: str,
    superset_username: str,
    superset_password: str,
    dashboard_id: str,
    include_openai: bool,
) -> dict[str, Any]:
    period = _load_period_data(seed_dir)
    card = _card()
    cases = _cases()
    source_validation = await _validate_superset(
        superset_url, superset_username, superset_password, dashboard_id
    )

    arms: dict[str, Any] = {}
    jev_key = load_api_key(str(typesafe_key_file))
    if not jev_key:
        raise RuntimeError("a TypeSafe API key is required for the Jev arm")
    jev_rows, jev_totals = await _run_arm(
        "jev", JevJudger(api_key=jev_key), card, period, cases
    )
    arms["jev"] = {"rows": jev_rows, "totals": jev_totals}

    rule_rows, rule_totals = await _run_arm(
        "fixed-threshold", ThresholdJudger(), card, period, cases
    )
    arms["fixed-threshold"] = {"rows": rule_rows, "totals": rule_totals}

    openai_key = _openai_key(openai_dotenv)
    if include_openai and openai_key:
        baseline = EmbeddingReasoningJudger(
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            api_key=openai_key,
            top_k=8,
            responses_api=True,
        )
        baseline.name = "openai-embedding-reasoning"
        baseline_rows, baseline_totals = await _run_arm(
            "openai-embedding-reasoning", baseline, card, period, cases
        )
        arms["openai-embedding-reasoning"] = {
            "rows": baseline_rows,
            "totals": baseline_totals,
        }
    elif include_openai:
        arms["openai-embedding-reasoning"] = {
            "rows": [],
            "totals": {"error": "OPENAI_API_KEY was not found in the supplied dotenv file or environment"},
        }

    report = {
        "trial": "northstar-real-row-shadow-replay",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "labeling": "counterfactual replay over real Northstar row distributions; expected outcomes are a human rubric",
        "source_validation": source_validation,
        "dataset": {
            "seed_dir": str(seed_dir),
            "current_complete_month": period.current_month,
            "baseline_month": period.baseline_month,
            "row_counts": period.row_counts,
            "observation_count": len(_build_resources(period, cases[0])[0].observations)
            + sum(len(resource.observations) for resource in _build_resources(period, cases[0])[1:]),
        },
        "rubric": [
            {"case_id": case.case_id, "expected": case.expected.value, "description": case.description}
            for case in cases
        ],
        "arms": arms,
        "limitations": [
            "The replay uses real local Northstar rows but counterfactual day-to-day perturbations.",
            "Superset metadata and chart-data validation are recorded separately from the replay arm results.",
            "The fixed-threshold arm is an explicit comparator, not a claimed production design.",
            "OpenAI embedding retrieval is intentionally capped at top_k=8 to represent a conventional RAG baseline.",
            "API latency and token counts include provider calls but exclude the unavailable Superset metadata retry time.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(_markdown(report) + "\n", encoding="utf-8")
    return report


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Northstar real-row shadow replay",
        "",
        "This is a counterfactual replay over real Northstar seed rows. The rows are real; the expected outcomes are a reviewable human rubric.",
        "",
        f"- Complete comparison month: `{report['dataset']['current_complete_month']}`",
        f"- Baseline month: `{report['dataset']['baseline_month']}`",
        f"- Superset health: `{report['source_validation'].get('health')}`",
        f"- Superset metadata: `{report['source_validation'].get('metadata')}`",
        "",
        "| Arm | Accuracy | False notify | Missed notify | Median ms | Requests |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, arm in report["arms"].items():
        totals = arm["totals"]
        if "error" in totals:
            lines.append(f"| `{name}` | error | — | — | — | — |")
            continue
        lines.append(
            f"| `{name}` | {totals['accuracy']:.1%} | {totals['false_notify']} | "
            f"{totals['missed_notify']} | {totals['median_ms']} | {totals['requests']} |"
        )
    lines.extend(["", "## Event decisions", "", "| Case | Expected | " + " | ".join(report["arms"].keys()) + " |", "| --- | --- | " + " | ".join(["---"] * len(report["arms"])) + " |"])
    case_ids = [item["case_id"] for item in report["rubric"]]
    for case_id in case_ids:
        values = []
        for arm in report["arms"].values():
            row = next((item for item in arm.get("rows", []) if item["case_id"] == case_id), None)
            values.append(row["outcome"] if row else "error")
        expected = next(item["expected"] for item in report["rubric"] if item["case_id"] == case_id)
        lines.append(f"| `{case_id}` | `{expected}` | " + " | ".join(f"`{value}`" for value in values) + " |")
    lines.extend(["", "## Limits", "", *[f"- {item}" for item in report["limitations"]]])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-dir", type=Path, required=True)
    parser.add_argument("--typesafe-key-file", type=Path, required=True)
    parser.add_argument("--openai-dotenv", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/northstar-shadow-trial.json"))
    parser.add_argument("--superset-url", default="http://127.0.0.1:18089")
    parser.add_argument("--superset-username", default="admin")
    parser.add_argument("--superset-password", default="admin")
    parser.add_argument("--dashboard-id", default="1")
    parser.add_argument("--skip-openai", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(
        run_trial(
            seed_dir=args.seed_dir,
            output=args.output,
            typesafe_key_file=args.typesafe_key_file,
            openai_dotenv=args.openai_dotenv,
            superset_url=args.superset_url,
            superset_username=args.superset_username,
            superset_password=args.superset_password,
            dashboard_id=args.dashboard_id,
            include_openai=not args.skip_openai,
        )
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
