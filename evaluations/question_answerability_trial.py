"""Opt-in paired answerability research; never a production approval gate.

Twenty synthetic development cases, one request per case with both templates
over the same state. No sources are fetched, no delivery occurs, and no threshold
is tuned. A positive label means an answer exists, including an explicit no or
zero; it does not mean the owner's proposition is true. This is not a holdout or
evidence of production readiness. Run only with separate live-call authorization:
python -m evaluations.question_answerability_trial --jev-key-file KEY --output NEW_DIR
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import subprocess
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter

from typesafe_sdk import Noul

from signalweave.typesafe_adapter import JevJudger, load_api_key

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 20
SUPPORTED = .70
NOT_SUPPORTED = .30
ARMS = ("old", "candidate")
GATE = (
    "Candidate must classify all 20 cases correctly at the frozen thresholds with zero false support; "
    "unknown, invalid, errored, or incomplete cases fail. Old-arm results are descriptive only. "
    "Passing permits consideration of a production integration experiment, not production promotion."
)


def questions(question: str, index: int = 0):
    """Old text is copied verbatim from JevJudger.judge, not silently improved."""
    return {
        "old": Noul(
            instructions=(
                f"Does the available evidence support a concrete answer to questions[{index}]? "
                "Use only the normalized observations, source evidence, and card context. "
                "Computed analyses contain verified arithmetic, not proof of causation "
                "or statistical significance; respect their limitations. "
                "A related metric may support an answer, but do not invent facts that are absent."
            ),
            criteria={
                "true": question,
                "false": "The available evidence does not support a concrete answer to this question.",
            },
        ),
        "candidate": Noul(
            instructions=(
                f"Can the available evidence supply a concrete answer to the owner's question: {question!r}? "
                f"This is the question in `insight_card.questions[{index}]`. "
                "Judge whether an answer exists, including an explicit no, zero, or absence. "
                "Use only normalized observations, source evidence, card context, and computed analyses. "
                "Respect the requested population, period, definitions, and scope. "
                "Every requested part of a compound question needs an answer. "
                "Code owns arithmetic: use supplied computed results and respect their status and limitations. "
                "Arithmetic and temporal proximity do not establish causation or statistical significance. "
                "A healthy source or a list of observed entities does not establish complete coverage. "
                "Do not invent absent facts or resolve conflicting evidence without a supplied basis."
            ),
            criteria={
                "true": (
                    "Applicable evidence supplies a concrete answer to the entire owner question. "
                    "The answer may be yes, no, zero, an established absence, or a supplied numeric value."
                ),
                "false": (
                    "Missing, conflicting, inapplicable, or insufficient evidence prevents a concrete "
                    "answer to at least one requested part of the owner question."
                ),
            },
        ),
    }


def _case(domain, variant, question, statements, answer, *, analyses=()):
    # Only this state is dispatched. All IDs, categories and reference answers
    # remain in the local report. Healthy transport deliberately proves no scope.
    return {
        "id": f"{domain}-{variant}", "domain": domain, "variant": variant,
        "reference_answer": answer, "expected_accept": answer is not None,
        "expected_status": "supported" if answer is not None else "not_supported",
        "state": {
            "insight_card": {
                "what_to_watch": "The operational facts within the owner's stated scope.",
                "why_watch": "Determine whether the supplied evidence answers the owner's question.",
                "questions": [question],
            },
            "observations": [],
            "sources": [{"status": "healthy"}],
            "evidence": [{"statement": statement} for statement in statements],
            "analyses": list(analyses),
        },
    }


def cases():
    """Four domains x four conditions, then four distinct scope/answer edges."""
    definitions = [
        (
            "support_denominator",
            "Were there any SLA-eligible customer tickets in the North support queue on September 30?",
            "SLA eligibility means customer tickets opened in the North support queue on September 30, excluding spam and internal tickets.",
            "The complete eligibility audit for that queue and day records 120 eligible customer tickets.",
            "The complete eligibility audit for that queue and day explicitly records zero eligible customer tickets; no tickets qualify.",
            "The dashboard reports 150 total tickets, but has no eligibility classification or eligible denominator.",
            "Two equally authoritative complete eligibility audits for that queue and day report 120 and zero eligible tickets. Neither supersedes the other.",
        ),
        (
            "release_rollback",
            "Was the September 30 production checkout release rolled back by 18:00 UTC that day?",
            "Only the production checkout release and rollback events through September 30 at 18:00 UTC are in scope.",
            "The complete release ledger records that this release was rolled back at 17:00 UTC.",
            "The complete release ledger explicitly records no rollback for this release through 18:00 UTC; it remains deployed.",
            "The deployment log records the release at 16:00 UTC; rollback records and subsequent release state are unavailable.",
            "Two equally authoritative release ledgers at 18:00 UTC disagree: one records rollback at 17:00 UTC, the other explicitly records no rollback and the release still deployed. Neither supersedes the other.",
        ),
        (
            "finance_approval",
            "Had the finance owner approved the September 30 settled refund batch by 18:00 UTC?",
            "Approval must be recorded by the finance owner for the September 30 settled refund batch by 18:00 UTC.",
            "The complete approval register explicitly records this batch as approved by its finance owner at 17:00 UTC.",
            "The complete approval register explicitly records this batch as not approved by its finance owner as of 18:00 UTC.",
            "The batch settlement is recorded, but its finance-owner approval record is unavailable.",
            "Two equally authoritative approval records for this batch at 18:00 UTC disagree: one says finance-owner approved, the other says finance-owner not approved. Neither supersedes the other.",
        ),
        (
            "cluster_coverage",
            "Does the 18:00 UTC September 30 telemetry snapshot cover every production database cluster?",
            "Coverage requires telemetry for every cluster in the authoritative production inventory at the same timestamp.",
            "The authoritative complete production inventory at 18:00 UTC is east, west, and central. The telemetry snapshot explicitly contains all three at that timestamp.",
            "The authoritative complete production inventory at 18:00 UTC is east, west, and central. The telemetry snapshot explicitly lacks central at that timestamp and contains only east and west.",
            "The telemetry source is healthy and lists east and west at 18:00 UTC. No authoritative complete production inventory or coverage attestation is supplied.",
            "The complete production inventory contains east, west, and central. Two equally authoritative reports of the same telemetry snapshot disagree: one includes all three; the other explicitly excludes central. Neither supersedes the other.",
        ),
    ]
    for domain, question, scope, yes, no, missing, conflict in definitions:
        for variant, evidence, answer in (
            ("answer_yes", yes, "yes"), ("answer_no", no, "no"),
            ("missing", missing, None), ("conflicting", conflict, None),
        ):
            yield _case(domain, variant, question, [scope, evidence], answer)

    yield _case(
        "release_rollback", "partial_compound_question",
        "Was the September 30 production checkout release rolled back by 18:00 UTC, and who authorized the rollback?",
        ["The complete production release ledger records a rollback at 17:00 UTC that day. The authorizer field is absent, and no authorization record is supplied."],
        None,
    )
    yield _case(
        "support_denominator", "wrong_population",
        "Were there any SLA-eligible customer tickets in the North support queue on September 30?",
        ["The complete September 30 eligibility audit covers internal employee IT tickets in the South queue only and reports 120 eligible tickets. No North customer-ticket audit is supplied."],
        None,
    )
    # Known arithmetic is computed here, never delegated to either Noul.
    met, eligible = 90, 120
    rate = 100 * met / eligible
    yield _case(
        "support_denominator", "open_numeric_answer",
        "What percentage of SLA-eligible North customer tickets met SLA on September 30?",
        [f"The complete North customer-ticket audit for September 30 records {eligible} SLA-eligible tickets, of which {met} met SLA. Spam and internal tickets are excluded."],
        rate,
        analyses=[{
            "status": "complete", "metric": "eligible_ticket_sla_percent",
            "inputs": {"met_sla": met, "eligible_tickets": eligible},
            "formula": "100 * met_sla / eligible_tickets", "value": rate,
            "limitations": ["Only North customer tickets on September 30; descriptive arithmetic, not a causal or statistical-significance finding."],
        }],
    )
    yield _case(
        "release_rollback", "causal_why_from_time",
        "Why did production checkout latency rise on September 30?",
        ["A release occurred at 16:00 UTC. Latency rose at 16:05 UTC. No mechanism, controlled comparison, or causal investigation is supplied."],
        None,
        analyses=[{
            "status": "complete", "metric": "latency_change_percent",
            "inputs": {"baseline_ms": 100, "current_ms": 120},
            "value": 100 * (120 - 100) / 100,
            "limitations": ["Descriptive arithmetic only. Temporal proximity cannot establish why latency rose."],
        }],
    )


def safe_raw(value):
    """JSON-safe diagnostics, without coercing arbitrary objects to secret text."""
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else {"nonfinite": str(value)}
    if isinstance(value, Mapping):
        return {str(k): safe_raw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_raw(v) for v in value]
    return {"unexpected_type": type(value).__name__}


def decode(answer):
    value = getattr(answer, "noul", None)
    valid = type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value)
    status = "unknown"
    if valid:
        if value >= SUPPORTED:
            status = "supported"
        elif value <= NOT_SUPPORTED:
            status = "not_supported"
    return {
        "probability": value if valid else None, "status": status,
        "valid": valid, "accept": valid and status == "supported",
        "validation": "valid" if valid else "missing_or_invalid_noul",
        "raw": {"noul": safe_raw(value), "answer_type": type(answer).__name__},
    }


def compare(answers, case):
    """Unknown/malformed results are never counted as correct negative answers."""
    return {
        arm: {
            "exact": answers[arm]["valid"] and answers[arm]["status"] == case["expected_status"],
            "would_accept": answers[arm]["accept"],
            "acceptance_matches": answers[arm]["valid"] and answers[arm]["accept"] == case["expected_accept"],
        }
        for arm in ARMS
    }


class Probe(JevJudger):
    def __init__(self, key):
        super().__init__(api_key=key, max_retries=0)
        self.attempts = 0

    async def check(self, state):
        if self.attempts >= LIMIT:
            raise RuntimeError("Research request budget exhausted")
        paired = questions(state["insight_card"]["questions"][0])
        self.attempts += 1  # Before await; transport failures consume the budget too.
        response = await self._system_one_with_retry(
            state=state, questions=paired, stage="question-answerability-probe",
        )
        self.metrics.record(response)
        nouls = getattr(response, "nouls", None)
        usage = getattr(response, "usage", None)
        return {
            "model": safe_raw(getattr(response, "model", None)),
            "usage": {
                name: safe_raw(getattr(usage, name, None))
                for name in ("input_tokens", "output_tokens")
            },
            "answers": {arm: decode(nouls.get(arm) if isinstance(nouls, Mapping) else None) for arm in ARMS},
        }


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def summarize(rows, planned):
    result = {}
    for arm in ARMS:
        answered = [
            (row, row.get("response", {}).get("answers", {}).get(arm, {}))
            for row in rows if row["status"] == "complete"
        ]
        result[arm] = {
            "denominator": planned,
            "exact": sum(row.get("comparison", {}).get(arm, {}).get("exact", False) for row in rows),
            "accepted": sum(row.get("comparison", {}).get(arm, {}).get("would_accept", False) for row in rows),
            "false_support": sum(
                not row["expected_accept"] and answer.get("valid", False) and answer.get("accept", False)
                for row, answer in answered
            ),
            # A known negative answer (including explicit zero/absence) is
            # represented by reference_answer="no" in the four domain controls.
            "false_refusal": sum(
                row["reference_answer"] == "no" and answer.get("valid", False)
                and answer.get("status") == "not_supported" for row, answer in answered
            ),
            "probability_unknown": sum(
                answer.get("valid", False) and answer.get("status") == "unknown"
                for _, answer in answered
            ),
            "invalid_answers": sum(not answer.get("valid", False) for _, answer in answered),
            "errors": sum(row["status"] == "error" for row in rows),
            "passed": len(rows) == planned and all(row.get("comparison", {}).get(arm, {}).get("exact", False) for row in rows),
        }
    result["candidate_only_correct"] = sum(
        row.get("comparison", {}).get("candidate", {}).get("exact", False)
        and not row.get("comparison", {}).get("old", {}).get("exact", False) for row in rows
    )
    result["old_only_correct"] = sum(
        row.get("comparison", {}).get("old", {}).get("exact", False)
        and not row.get("comparison", {}).get("candidate", {}).get("exact", False) for row in rows
    )
    return result


async def trial(output, key_file):
    fixture = list(cases())
    if not 0 < len(fixture) <= LIMIT:
        raise ValueError("Fixture exceeds research request budget")
    key = load_api_key(key_file)
    if not key:
        raise ValueError("A configured live Jev key is required")
    output.mkdir(parents=True, exist_ok=False)
    probe = Probe(key)
    report = {
        "scope": "Synthetic development research only; no production promotion or readiness claim.",
        "label_semantics": "Acceptance denotes answerability, not answer truth; explicit no/zero/absence are positive controls.",
        "gate": GATE,
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "production_adapter_sha256": hashlib.sha256((ROOT / "src/signalweave/typesafe_adapter.py").read_bytes()).hexdigest(),
        "dataset_sha256": digest(fixture),
        "questions_sha256": digest([JevJudger._question_budget_payload(questions(c["state"]["insight_card"]["questions"][0])) for c in fixture]),
        "thresholds": {"supported_gte": SUPPORTED, "not_supported_lte": NOT_SUPPORTED},
        "requested_model": probe.name, "live_jev": True, "external_delivery": False,
        "planned_cases": len(fixture), "max_attempts": LIMIT, "max_retries": 0,
        "attempts_reserved": 0, "attempts": 0, "status": "running", "passed": False,
        "cases": [],
    }
    report_path = output / "report.json"

    def persist():
        # Atomic replacement preserves the last reservation if serialization or
        # the process is interrupted while writing the next checkpoint.
        pending_path = output / "report.json.tmp"
        pending_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        pending_path.replace(report_path)

    persist()
    for case in fixture:
        row = {
            **case, "status": "pending",
            "questions": JevJudger._question_budget_payload(questions(case["state"]["insight_card"]["questions"][0])),
        }
        report["cases"].append(row)
        # Reserved means possibly in flight, not proof of billing or success.
        report["attempts_reserved"] = len(report["cases"])
        persist()
        start = perf_counter()
        try:
            row["response"] = await probe.check(case["state"])
            row["comparison"] = compare(row["response"]["answers"], case)
            row["status"] = "complete"
        except Exception as error:
            row.update(status="error", error_type=type(error).__name__)
        # BaseException deliberately leaves a durable pending reservation.
        row["seconds"] = perf_counter() - start
        report.update(
            attempts=probe.attempts, input_tokens=probe.metrics.input_tokens,
            output_tokens=probe.metrics.output_tokens, successful_requests=probe.metrics.requests,
        )
        report["summary"] = summarize(report["cases"], len(fixture))
        if len(report["cases"]) == len(fixture):
            report["status"] = "complete"
            report["passed"] = (
                report["summary"]["candidate"]["passed"]
                and report["summary"]["candidate"]["false_support"] == 0
            )
        persist()
    print(json.dumps({k: report[k] for k in ("status", "attempts", "summary")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jev-key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        asyncio.run(trial(arguments.output, arguments.jev_key_file))
    except Exception as error:
        # Setup failures must not print credential paths, values or server text.
        raise SystemExit(type(error).__name__) from None
