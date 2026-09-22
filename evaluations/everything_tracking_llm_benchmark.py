"""Comparative everything-tracking benchmark: LLM, Jev, and LLM+SignalWeave.

This is evaluation-only.  Every arm receives the same card and normalized
source bundle.  The direct LLM arm must reason over that bundle itself; the
mediated arm receives the same bundle plus a typed Jev preflight result.  Gold
labels remain in the evaluator and are never serialized into provider input.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import httpx

from evaluations.everything_tracking_trial import (
    DEFAULT_CONFIG,
    TrackingCase,
    build_cases,
    load_config,
)
from signalweave.engine import InsightEngine
from signalweave.models import Outcome
from signalweave.typesafe_adapter import JevJudger, load_api_key

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "everything-tracking-llm-benchmark.json"
ORACLE_FIELD_NAMES = {
    "expected_outcome",
    "expected_evidence_source_keys",
    "expected_delivery",
    "gold_label",
    "oracle",
}
OUTCOMES = {item.value for item in Outcome}


@dataclass(frozen=True)
class DecisionRow:
    case_id: str
    arm: str
    input_digest: str
    variant: str
    expected_outcome: str
    actual_outcome: str | None
    expected_delivery: list[str]
    actual_delivery: list[str]
    expected_evidence_source_keys: list[str]
    actual_evidence_source_keys: list[str]
    evidence_recall: float
    exact: bool
    unsafe_automatic_action: bool
    provenance_valid: bool
    confidence: float | None
    elapsed_ms: float
    api_requests: int
    input_tokens: int
    output_tokens: int
    oracle_leaks: int
    error: str | None = None


class OpenAIResponsesJudge:
    def __init__(self, *, api_key: str, model: str, timeout: float = 90.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @staticmethod
    def _dotenv_key(path: str | Path) -> str:
        for line in Path(path).read_text().splitlines():
            if line.startswith("OPENAI_API_KEY="):
                value = line.split("=", 1)[1].strip()
                if value and not value.startswith("<") and "your-actual-key" not in value:
                    return value
        raise RuntimeError(f"OPENAI_API_KEY was not found in {path}")

    @staticmethod
    def _schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "outcome": {"type": "string", "enum": sorted(OUTCOMES)},
                "delivery": {"type": "string"},
                "evidence_source_keys": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": [
                "outcome",
                "delivery",
                "evidence_source_keys",
                "reason",
                "confidence",
            ],
            "additionalProperties": False,
        }

    @staticmethod
    def _payload(case: TrackingCase) -> dict[str, Any]:
        return {
            "card": case.card.model_dump(mode="json"),
            "sources": [resource.model_dump(mode="json") for resource in case.resources],
            "task": (
                "Decide whether the current operating state requires no action, a notification, "
                "investigation, escalation, or insufficient-data handling. Use the card's purpose "
                "and all source observations. Cite only source_key values present in sources."
            ),
        }

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are evaluating a scheduled enterprise operating concern. The card was authored "
            "by a human and the sources are the complete evidence bundle for this run. Use the "
            "card's stated purpose, questions, source evidence, freshness, and relationships. "
            "Do not treat a large movement as automatically actionable. Distinguish expected, "
            "contradictory, severe, and untrustworthy states. Never invent facts, recipients, "
            "source keys, or causation. Return only the required JSON schema. The delivery value "
            "must be a configured delivery key or the literal string 'none'."
        )

    @staticmethod
    def _bundle_payload(bundle: dict[str, Any]) -> dict[str, Any]:
        return {
            "signalweave_preflight": bundle,
            "instruction": (
                "Treat this as typed advisory context produced before the agent woke up. Verify "
                "it against the source bundle. It is not an authorization or an unquestionable "
                "answer; use the source evidence and card policy to make the final decision."
            ),
        }

    async def decide(
        self, case: TrackingCase, *, bundle: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = self._payload(case)
        if bundle is not None:
            payload["preflight"] = self._bundle_payload(bundle)
        prompt = self._system_prompt() + "\n\nInput:\n" + json.dumps(payload, sort_keys=True)
        oracle_leaks = sum(field in prompt for field in ORACLE_FIELD_NAMES)
        body = {
            "model": self.model,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            "store": False,
            "max_output_tokens": 900,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "everything_tracking_decision",
                    "strict": True,
                    "schema": self._schema(),
                }
            },
        }
        headers = {
            "authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses", headers=headers, json=body
            )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        if response.is_error:
            raise RuntimeError(f"OpenAI Responses API {response.status_code}: {response.text[:500]}")
        raw = response.json()
        content = raw.get("output_text")
        if not isinstance(content, str):
            content = ""
            for item in raw.get("output", []):
                for part in item.get("content", []):
                    if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                        content = part["text"]
                        break
        if not content:
            raise ValueError("OpenAI Responses API returned no output text")
        try:
            decision = json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError("OpenAI response was not valid JSON") from error
        usage = raw.get("usage", {}) or {}
        return {
            "decision": decision,
            "elapsed_ms": elapsed_ms,
            "api_requests": 1,
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "oracle_leaks": oracle_leaks,
            "prompt_digest": hashlib.sha256(prompt.encode()).hexdigest()[:24],
        }


def _usage_delta(before: Any, after: Any) -> dict[str, int]:
    return {
        "requests": int(after.requests - before.requests),
        "input_tokens": int(after.input_tokens - before.input_tokens),
        "output_tokens": int(after.output_tokens - before.output_tokens),
    }


def _estimated_cost(
    usage: dict[str, int], *, input_price_per_mtok: float, output_price_per_mtok: float
) -> float:
    return round(
        (usage.get("input_tokens", 0) / 1_000_000) * input_price_per_mtok
        + (usage.get("output_tokens", 0) / 1_000_000) * output_price_per_mtok,
        8,
    )


def _expected_delivery(case: TrackingCase) -> list[str]:
    if case.expected_outcome not in {Outcome.NOTIFY.value, Outcome.ESCALATE.value}:
        return []
    return [
        method.key
        for method in case.card.delivery_methods
        if method.outcome.value == case.expected_outcome
    ]


def _normalize_delivery(value: Any) -> list[str]:
    if value is None or str(value).strip().lower() in {"", "none", "null", "—", "-"}:
        return []
    if isinstance(value, list):
        return sorted(str(item) for item in value)
    return [str(value)]


def _input_digest(case: TrackingCase) -> str:
    sources = []
    for resource in case.resources:
        payload = resource.model_dump(mode="json")
        # captured_at is provider-run metadata, not input content.  Excluding
        # it lets the independent reviewer rebuild the same digest later.
        payload.pop("captured_at", None)
        sources.append(payload)
    payload = {
        "card": case.card.model_dump(mode="json"),
        "sources": sources,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


def _score(
    case: TrackingCase,
    *,
    arm: str,
    decision: dict[str, Any] | None,
    elapsed_ms: float,
    api_requests: int,
    input_tokens: int,
    output_tokens: int,
    oracle_leaks: int,
    error: str | None = None,
) -> DecisionRow:
    decision = decision if isinstance(decision, dict) else {}
    actual = str(decision.get("outcome")) if decision.get("outcome") is not None else None
    if actual not in OUTCOMES:
        actual = None
    actual_delivery = _normalize_delivery(decision.get("delivery"))
    actual_evidence = sorted({str(item) for item in decision.get("evidence_source_keys", [])})
    valid_sources = {resource.source_key for resource in case.resources}
    provenance_valid = bool(actual_evidence) and set(actual_evidence) <= valid_sources
    required = set(case.expected_evidence_source_keys)
    evidence_recall = len(required & set(actual_evidence)) / len(required) if required else 1.0
    exact = bool(
        error is None
        and actual == case.expected_outcome
        and actual_delivery == _expected_delivery(case)
        and required <= set(actual_evidence)
        and provenance_valid
        and oracle_leaks == 0
    )
    unsafe = bool(
        actual in {Outcome.NOTIFY.value, Outcome.ESCALATE.value}
        and not exact
    )
    confidence = decision.get("confidence")
    try:
        confidence = max(0.0, min(float(confidence), 1.0)) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    return DecisionRow(
        case_id=case.case_id,
        arm=arm,
        input_digest=_input_digest(case),
        variant=case.variant,
        expected_outcome=case.expected_outcome,
        actual_outcome=actual,
        expected_delivery=_expected_delivery(case),
        actual_delivery=actual_delivery,
        expected_evidence_source_keys=sorted(required),
        actual_evidence_source_keys=actual_evidence,
        evidence_recall=round(evidence_recall, 4),
        exact=exact,
        unsafe_automatic_action=unsafe,
        provenance_valid=provenance_valid,
        confidence=confidence,
        elapsed_ms=round(elapsed_ms, 2),
        api_requests=api_requests,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        oracle_leaks=oracle_leaks,
        error=error,
    )


async def _jev_decision(engine: InsightEngine, case: TrackingCase) -> tuple[dict[str, Any], dict[str, int], float, str | None]:
    before = engine.judger.metrics
    before_usage = type(before)(
        requests=before.requests,
        input_tokens=before.input_tokens,
        output_tokens=before.output_tokens,
    )
    started = time.perf_counter()
    try:
        run = await engine.evaluate(case.card, case.resources)
        result = run.result
        bundle = {
            "outcome": result.outcome.value,
            "probabilities": result.probabilities,
            "confidence": result.confidence,
            "watch_results": [item.model_dump(mode="json") for item in result.watch_results],
            "question_results": [item.model_dump(mode="json") for item in result.question_results],
            "evidence_findings": [item.model_dump(mode="json") for item in result.evidence_findings],
            "evidence_source_keys": sorted({item.source_key for item in result.evidence}),
            "delivery": [method.key for method in result.delivery_methods],
            "rationale": result.rationale,
        }
        usage = _usage_delta(before_usage, engine.judger.metrics)
        return bundle, usage, (time.perf_counter() - started) * 1000, None
    except Exception as error:  # noqa: BLE001 - preserve provider failures in denominator
        usage = _usage_delta(before_usage, engine.judger.metrics)
        return {
            "status": "unavailable",
            "error": f"{type(error).__name__}: {error}",
        }, usage, (time.perf_counter() - started) * 1000, f"{type(error).__name__}: {error}"


def _jev_row(
    case: TrackingCase,
    bundle: dict[str, Any],
    usage: dict[str, int],
    elapsed_ms: float,
    error: str | None,
) -> DecisionRow:
    return _score(
        case,
        arm="jev",
        decision={
            "outcome": bundle.get("outcome"),
            "delivery": bundle.get("delivery", []),
            "evidence_source_keys": bundle.get("evidence_source_keys", []),
            "confidence": bundle.get("confidence"),
        },
        elapsed_ms=elapsed_ms,
        api_requests=usage["requests"],
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        oracle_leaks=0,
        error=error,
    )


def _summary(rows: list[DecisionRow]) -> dict[str, Any]:
    latencies = sorted(item.elapsed_ms for item in rows)
    by_variant: dict[str, list[DecisionRow]] = defaultdict(list)
    for item in rows:
        by_variant[item.variant].append(item)
    return {
        "cases": len(rows),
        "exact": sum(item.exact for item in rows),
        "exact_rate": round(sum(item.exact for item in rows) / len(rows), 4) if rows else 0.0,
        "unsafe_automatic_actions": sum(item.unsafe_automatic_action for item in rows),
        "unsafe_rate": round(sum(item.unsafe_automatic_action for item in rows) / len(rows), 4) if rows else 0.0,
        "evidence_recall": round(sum(item.evidence_recall for item in rows) / len(rows), 4) if rows else 0.0,
        "provenance_valid": sum(item.provenance_valid for item in rows),
        "errors": sum(item.error is not None for item in rows),
        "oracle_leaks": sum(item.oracle_leaks for item in rows),
        "median_ms": round(median(latencies), 2) if latencies else None,
        "p95_ms": round(latencies[max(0, int(len(latencies) * 0.95) - 1)], 2) if latencies else None,
        "api_requests": sum(item.api_requests for item in rows),
        "input_tokens": sum(item.input_tokens for item in rows),
        "output_tokens": sum(item.output_tokens for item in rows),
        "by_variant": {
            variant: {
                "cases": len(items),
                "exact": sum(item.exact for item in items),
                "exact_rate": round(sum(item.exact for item in items) / len(items), 4),
                "unsafe_automatic_actions": sum(item.unsafe_automatic_action for item in items),
                "evidence_recall": round(sum(item.evidence_recall for item in items) / len(items), 4),
            }
            for variant, items in sorted(by_variant.items())
        },
    }


async def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args.config)
    cases = build_cases(config, repeats=args.repeats)
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        raise ValueError("benchmark has no cases")
    if args.dry_run:
        return {
            "trial": "everything-tracking-llm-benchmark",
            "cases": len(cases),
            "adapters": sorted({resource.adapter for case in cases for resource in case.resources}),
        }
    openai_key = OpenAIResponsesJudge._dotenv_key(args.dotenv) if args.dotenv else os.getenv("OPENAI_API_KEY")
    if not openai_key or "your-actual-key" in openai_key:
        raise RuntimeError("provide a real OpenAI key with --dotenv or OPENAI_API_KEY")
    typesafe_key = load_api_key(args.typesafe_key_file)
    if not typesafe_key:
        raise RuntimeError("provide a TypeSafe key with --typesafe-key-file or TYPESAFE_API_KEY")
    llm = OpenAIResponsesJudge(api_key=openai_key, model=args.model)
    jev_judger = JevJudger(api_key=typesafe_key)
    engine = InsightEngine(judger=jev_judger)
    semaphore = asyncio.Semaphore(args.concurrency)
    rows: list[DecisionRow] = []

    async def one(case: TrackingCase) -> list[DecisionRow]:
        async with semaphore:
            raw_task = asyncio.create_task(llm.decide(case))
            jev_task = asyncio.create_task(_jev_decision(engine, case))
            raw_started = time.perf_counter()
            try:
                raw_payload = await raw_task
                raw_row = _score(
                    case,
                    arm="llm-raw",
                    decision=raw_payload["decision"],
                    elapsed_ms=raw_payload["elapsed_ms"],
                    api_requests=raw_payload["api_requests"],
                    input_tokens=raw_payload["input_tokens"],
                    output_tokens=raw_payload["output_tokens"],
                    oracle_leaks=raw_payload["oracle_leaks"],
                )
            except Exception as error:  # noqa: BLE001
                raw_row = _score(
                    case,
                    arm="llm-raw",
                    decision=None,
                    elapsed_ms=(time.perf_counter() - raw_started) * 1000,
                    api_requests=1,
                    input_tokens=0,
                    output_tokens=0,
                    oracle_leaks=0,
                    error=f"{type(error).__name__}: {error}",
                )
            bundle, jev_usage, jev_elapsed, jev_error = await jev_task
            jev_row = _jev_row(case, bundle, jev_usage, jev_elapsed, jev_error)
            mediated_started = time.perf_counter()
            try:
                mediated_payload = await llm.decide(case, bundle=bundle)
                mediated_row = _score(
                    case,
                    arm="llm-signalweave",
                    decision=mediated_payload["decision"],
                    elapsed_ms=jev_elapsed + mediated_payload["elapsed_ms"],
                    api_requests=mediated_payload["api_requests"],
                    input_tokens=mediated_payload["input_tokens"],
                    output_tokens=mediated_payload["output_tokens"],
                    oracle_leaks=mediated_payload["oracle_leaks"],
                )
            except Exception as error:  # noqa: BLE001
                mediated_row = _score(
                    case,
                    arm="llm-signalweave",
                    decision=None,
                    elapsed_ms=jev_elapsed + (time.perf_counter() - mediated_started) * 1000,
                    api_requests=1,
                    input_tokens=0,
                    output_tokens=0,
                    oracle_leaks=0,
                    error=f"{type(error).__name__}: {error}",
                )
            return [raw_row, jev_row, mediated_row]

    nested = await asyncio.gather(*(one(case) for case in cases))
    for result in nested:
        rows.extend(result)
    by_arm = {arm: [row for row in rows if row.arm == arm] for arm in ("llm-raw", "jev", "llm-signalweave")}
    paired = []
    for case in cases:
        pair = {row.arm: row for row in rows if row.case_id == case.case_id}
        if len(pair) != 3:
            continue
        paired.append(
            {
                "case_id": case.case_id,
                "llm_raw_exact": pair["llm-raw"].exact,
                "jev_exact": pair["jev"].exact,
                "llm_signalweave_exact": pair["llm-signalweave"].exact,
                "raw_to_mediated_delta": int(pair["llm-signalweave"].exact) - int(pair["llm-raw"].exact),
                "raw_unsafe": pair["llm-raw"].unsafe_automatic_action,
                "mediated_unsafe": pair["llm-signalweave"].unsafe_automatic_action,
            }
        )
    report = {
        "trial": "everything-tracking-llm-benchmark",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "repeats": args.repeats,
        "cases": len(cases),
        "design": {
            "companies": len({case.company_id for case in cases}),
            "workflows": len({case.workflow_id for case in cases}),
            "variants": sorted({case.variant for case in cases}),
            "adapters": sorted({resource.adapter for case in cases for resource in case.resources}),
            "sources_per_case": sorted({len(case.resources) for case in cases}),
            "same_card_and_sources_all_arms": True,
            "expected_labels_sent_to_providers": False,
            "direct_llm_and_mediated_llm_same_model": True,
            "mediated_difference": "typed Jev preflight bundle",
        },
        "arms": {arm: _summary(items) for arm, items in by_arm.items()},
        "provider_metrics": {
            "typesafe_jev": {
                "requests": jev_judger.metrics.requests,
                "input_tokens": jev_judger.metrics.input_tokens,
                "output_tokens": jev_judger.metrics.output_tokens,
            },
            "openai_raw": {
                "requests": sum(item.api_requests for item in by_arm["llm-raw"]),
                "input_tokens": sum(item.input_tokens for item in by_arm["llm-raw"]),
                "output_tokens": sum(item.output_tokens for item in by_arm["llm-raw"]),
            },
            "openai_mediated": {
                "requests": sum(item.api_requests for item in by_arm["llm-signalweave"]),
                "input_tokens": sum(item.input_tokens for item in by_arm["llm-signalweave"]),
                "output_tokens": sum(item.output_tokens for item in by_arm["llm-signalweave"]),
            },
        },
        "pricing": {
            "currency": "USD",
            "typesafe_input_price_per_mtok": args.typesafe_input_price_per_mtok,
            "typesafe_output_price_per_mtok": args.typesafe_output_price_per_mtok,
            "openai_input_price_per_mtok": args.openai_input_price_per_mtok,
            "openai_output_price_per_mtok": args.openai_output_price_per_mtok,
            "basis": "Configurable list-price estimate using provider-reported usage; not an invoice.",
        },
        "estimated_costs": {},
        "paired": {
            "complete_case_triplets": len(paired),
            "llm_signalweave_improved": sum(item["raw_to_mediated_delta"] > 0 for item in paired),
            "llm_signalweave_worsened": sum(item["raw_to_mediated_delta"] < 0 for item in paired),
            "llm_signalweave_same": sum(item["raw_to_mediated_delta"] == 0 for item in paired),
            "unsafe_actions_removed": sum(item["raw_unsafe"] and not item["mediated_unsafe"] for item in paired),
        },
        "rows": [asdict(row) for row in rows],
        "paired_rows": paired,
        "limitations": [
            "The enterprise catalog and expected outcomes are synthetic, though provider judgments are live.",
            "All arms receive a supplied source bundle; this benchmark does not establish catalog recall.",
            "The direct LLM baseline is a named model but not every possible agent architecture.",
            "Dollar costs are estimates using the configured list prices and provider-reported usage; contracts, caching, and volume discounts can change the invoice.",
            "The mediated arm adds a Jev call, so value must come from safer/useful decisions or avoided work, not raw latency alone.",
        ],
    }
    typesafe_usage = report["provider_metrics"]["typesafe_jev"]
    raw_usage = report["provider_metrics"]["openai_raw"]
    mediated_usage = report["provider_metrics"]["openai_mediated"]
    raw_cost = _estimated_cost(
        raw_usage,
        input_price_per_mtok=args.openai_input_price_per_mtok,
        output_price_per_mtok=args.openai_output_price_per_mtok,
    )
    jev_cost = _estimated_cost(
        typesafe_usage,
        input_price_per_mtok=args.typesafe_input_price_per_mtok,
        output_price_per_mtok=args.typesafe_output_price_per_mtok,
    )
    mediated_llm_cost = _estimated_cost(
        mediated_usage,
        input_price_per_mtok=args.openai_input_price_per_mtok,
        output_price_per_mtok=args.openai_output_price_per_mtok,
    )
    mediated_total_cost = round(jev_cost + mediated_llm_cost, 8)
    raw_per_case = round(raw_cost / len(cases), 8) if cases else 0.0
    mediated_per_case = round(mediated_total_cost / len(cases), 8) if cases else 0.0
    report["estimated_costs"] = {
        "llm_raw_usd": raw_cost,
        "jev_preflight_usd": jev_cost,
        "llm_signalweave_luna_usd": mediated_llm_cost,
        "llm_signalweave_total_usd": mediated_total_cost,
        "raw_cost_per_case_usd": raw_per_case,
        "mediated_cost_per_case_usd": mediated_per_case,
        "mediated_minus_raw_usd": round(mediated_total_cost - raw_cost, 8),
        "mediated_vs_raw_percent": round((mediated_total_cost / raw_cost - 1) * 100, 2)
        if raw_cost
        else None,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(render_markdown(report) + "\n", encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Everything-tracking LLM benchmark",
        "",
        f"Model: `{report.get('model', 'dry-run')}`. Cases: **{report['cases']}**.",
        "",
        "| Measure | LLM raw | Jev | LLM + SignalWeave |",
        "| --- | ---: | ---: | ---: |",
    ]
    for label, key, suffix in [
        ("Exact outcomes", "exact_rate", ""),
        ("Unsafe automatic actions", "unsafe_automatic_actions", ""),
        ("Evidence recall", "evidence_recall", ""),
        ("Errors", "errors", ""),
        ("Median latency", "median_ms", " ms"),
        ("P95 latency", "p95_ms", " ms"),
        ("Input tokens", "input_tokens", ""),
        ("Output tokens", "output_tokens", ""),
    ]:
        values = []
        for arm in ("llm-raw", "jev", "llm-signalweave"):
            value = report["arms"][arm].get(key)
            if key == "exact_rate" or key == "evidence_recall":
                value = f"{float(value):.1%}" if value is not None else "—"
            else:
                value = f"{value}{suffix}" if value is not None else "—"
            values.append(value)
        lines.append(f"| {label} | {values[0]} | {values[1]} | {values[2]} |")
    lines.extend(
        [
            "",
            "## Usage and estimated cost",
            "",
            "Costs use the pricing values recorded in the JSON report and provider-reported token usage; they are estimates, not invoices.",
            "",
            "| Cost measure | Raw Luna | Jev preflight | Luna + SignalWeave |",
            "| --- | ---: | ---: | ---: |",
            f"| Estimated total | ${report['estimated_costs']['llm_raw_usd']:.4f} | ${report['estimated_costs']['jev_preflight_usd']:.4f} | ${report['estimated_costs']['llm_signalweave_total_usd']:.4f} |",
            f"| Estimated per case | ${report['estimated_costs']['raw_cost_per_case_usd']:.6f} | ${report['estimated_costs']['jev_preflight_usd'] / report['cases']:.6f} | ${report['estimated_costs']['mediated_cost_per_case_usd']:.6f} |",
            "",
            "The mediated total is the Jev preflight plus the Luna call that receives the typed preflight.",
            "",
            "## Paired LLM effect",
            "",
            f"- Mediated LLM improved exact outcomes on `{report['paired']['llm_signalweave_improved']}` cases.",
            f"- Mediated LLM worsened exact outcomes on `{report['paired']['llm_signalweave_worsened']}` cases.",
            f"- Mediated LLM removed unsafe actions on `{report['paired']['unsafe_actions_removed']}` cases.",
            "",
            "## Limits",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dotenv", type=Path)
    parser.add_argument("--typesafe-key-file", type=Path)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument(
        "--typesafe-input-price-per-mtok",
        type=float,
        default=0.042,
        help="Estimated TypeSafe input price in USD per million tokens (default: $42/B).",
    )
    parser.add_argument(
        "--typesafe-output-price-per-mtok",
        type=float,
        default=0.0,
        help="Estimated TypeSafe output price in USD per million tokens (default: free).",
    )
    parser.add_argument(
        "--openai-input-price-per-mtok",
        type=float,
        default=0.20,
        help="Estimated OpenAI input price in USD per million tokens.",
    )
    parser.add_argument(
        "--openai-output-price-per-mtok",
        type=float,
        default=1.20,
        help="Estimated OpenAI output price in USD per million tokens.",
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        raise SystemExit("--repeats must be positive")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be positive")
    if not 1 <= args.concurrency <= 16:
        raise SystemExit("--concurrency must be between 1 and 16")
    result = asyncio.run(run_benchmark(args))
    if args.dry_run:
        print(json.dumps(result, indent=2))
    else:
        print(render_markdown(result))


if __name__ == "__main__":
    main()
