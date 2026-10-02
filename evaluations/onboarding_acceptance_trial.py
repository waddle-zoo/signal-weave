"""Opt-in end-to-end empirical onboarding acceptance regression.

Reuses 12 expert-supplied reviewed synthetic cases (three companies, four states).
This is not novice-bootstrap proof, a holdout, or evidence of a Luna advantage.
Offline fixture judgments test plumbing only, never semantic correctness.

After reviewer checks, the main operator may explicitly run:
  python -m evaluations.onboarding_acceptance_trial --live --key-file PATH --output NEW_DIR
No Codex invocation, external delivery, retries, or production writes occur here.
The exclusive output contains frozen inputs/source hashes, a durable request/result
journal and a checkpoint report. ``recompute`` replays recorded engine results
through CardWorkflowEvaluator offline; it never asks Jev again.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import os
import subprocess
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

from evaluations.watch_evidence_trial import cases as reviewed_cases
from signalweave.compiler import base_plan
from signalweave.engine import InsightEngine
from signalweave.evaluation import (
    CardEvaluationCase,
    CardEvaluationReport,
    CardEvaluationThresholds,
    CardWorkflowEvaluator,
    EvaluationDataset,
    card_acceptance_digest,
)
from signalweave.models import InsightResult, Outcome, ResourceSnapshot
from signalweave.typesafe_adapter import JevJudger, load_api_key

ROOT = Path(__file__).resolve().parents[1]
MAX_REQUESTS = 12
ACCEPTANCE_OUTCOMES = [Outcome.NOTIFY, Outcome.IGNORE, Outcome.INSUFFICIENT_DATA]
EXPECTED_OUTCOMES = {
    "present": Outcome.NOTIFY, "absent": Outcome.IGNORE, "unknown": Outcome.INSUFFICIENT_DATA,
}
THRESHOLDS = CardEvaluationThresholds(min_cases=4)
SCOPE = "end-to-end empirical acceptance regression of expert-supplied reviewed synthetic cards"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def cases() -> dict[str, list[CardEvaluationCase]]:
    """One unchanged card per company; labels remain solely on evaluation cases."""
    companies = {}
    cards = {}
    for name, original, snapshot, expected_watch in reviewed_cases():
        company = name.rsplit("-", 1)[0]
        if company not in cards:
            card = original.model_copy(deep=True, update={"id": f"{company}-operating-check"})
            card.compiled_plan = base_plan(card)
            cards[company] = card
        outcome = EXPECTED_OUTCOMES[expected_watch]
        # Independent labels: do not derive endpoints from the card under test.
        destinations = ({"owner": "agent://operating-owner"} if outcome == Outcome.NOTIFY else
                        {"data": "agent://data-owner"} if outcome == Outcome.INSUFFICIENT_DATA else {})
        case = CardEvaluationCase(
            id=name, card=cards[company], resources=[snapshot], expected_outcome=outcome,
            expected_delivery_method_keys=list(destinations),
            expected_delivery_destinations=destinations,
            required_evidence_source_keys=["record"], expected_retrieval_refs=["fixture|record"],
            dataset=EvaluationDataset(
                dataset_id=f"reviewed-operating-records-{company}", split="validation",
                digest=digest(snapshot.model_dump(mode="json")),
                label_source="expert-supplied reviewed watch_evidence_trial cases; development regression",
            ),
        )
        companies.setdefault(company, []).append(case)
    if len(companies) != 3 or any(len(group) != 4 for group in companies.values()):
        raise ValueError("Expected exactly three companies with four reviewed cases each")
    return companies


def require_acceptance_contract():
    if ("acceptance_outcomes" not in inspect.signature(CardWorkflowEvaluator.evaluate).parameters
            or "expected_delivery_destinations" not in CardEvaluationCase.model_fields
            or not {"acceptance_passed", "card_execution_digests"}.issubset(
                CardEvaluationReport.model_fields)):
        raise RuntimeError("The empirical acceptance evaluator contract must land before this trial")


def source_freeze():
    """Hash working bytes, including dirty/untracked Python sources, not just HEAD."""
    paths = sorted(set(ROOT.glob("src/**/*.py")) | set(ROOT.glob("tests/**/*.py"))
                   | set(ROOT.glob("evaluations/**/*.py")) | set(ROOT.glob("docs/**/*.md")) | {
        Path(__file__), ROOT / "evaluations/watch_evidence_trial.py",
        ROOT / "tests/test_onboarding_acceptance_trial.py", ROOT / "pyproject.toml", ROOT / "uv.lock",
        ROOT / "README.md", ROOT / "AGENTS.md",
    })
    return {
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "git_status": subprocess.check_output(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=ROOT, text=True),
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in paths},
        "dependencies": {name: version(name) for name in ("typesafe-sdk", "pydantic")},
    }


class Journal:
    def __init__(self, output):
        self.file = (output / "events.jsonl").open("x", encoding="utf-8")

    def emit(self, event, **payload):
        self.file.write(json.dumps({"event": event, **payload}, allow_nan=False) + "\n")
        self.file.flush()
        os.fsync(self.file.fileno())

    def close(self):
        self.file.close()


class TrialExecutionError(RuntimeError):
    """Only a bounded failure category may reach evaluator exception formatting."""


class RecordedJudger(JevJudger):
    def __init__(self, api_key, journal):
        super().__init__(api_key=api_key, max_retries=0, timeout=30,
                         max_payload_bytes=4_000_000)
        self.journal = journal
        self.attempts = 0
        self.case_id = None
        self.case_attempts = 0
        self.stopped = False

    async def _system_one_with_retry(self, *, state, questions, stage):
        if self.stopped or self.attempts >= MAX_REQUESTS or self.case_attempts >= 1 or stage != "judgment":
            raise TrialExecutionError("request_budget_or_stage")
        self.attempts += 1
        self.case_attempts += 1
        request_id = self.attempts
        self.journal.emit("request", request_id=request_id, case_id=self.case_id,
                          stage=stage, model=self.name, state=state,
                          questions=self._question_budget_payload(questions))
        try:
            response = await super()._system_one_with_retry(
                state=state, questions=questions, stage=stage)
            # Copy only documented answer fields, never SDK internals/headers.
            answers = {}
            for family, fields in (("choices", ("choice", "confidence", "probabilities")),
                                   ("nouls", ("noul",)),
                                   ("scores", ("score", "confidence", "probabilities"))):
                answers[family] = {
                    key: {field: getattr(answer, field) for field in fields if hasattr(answer, field)}
                    for key, answer in getattr(response, family, {}).items()
                }
            usage = getattr(response, "usage", None)
            self.journal.emit("response", request_id=request_id, case_id=self.case_id,
                              resolved_model=getattr(response, "model", None), answers=answers,
                              usage={key: getattr(usage, key, None)
                                     for key in ("input_tokens", "output_tokens")})
            return response
        except BaseException as error:
            self.journal.emit("request_error", request_id=request_id, case_id=self.case_id,
                              error_type=type(error).__name__)
            if not isinstance(error, Exception):
                self.stopped = True
                raise
            raise TrialExecutionError("provider_or_response_failure") from None


class RecordedEngine(InsightEngine):
    def __init__(self, judger, group, journal):
        super().__init__(judger)
        self.pending = iter(group)
        self.journal = journal

    async def evaluate(self, card, resources, context_override=None):
        case = next(self.pending)
        self.judger.case_id = case.id
        self.judger.case_attempts = 0
        try:
            run = await super().evaluate(card, resources, context_override=context_override)
        except Exception as error:
            # Evaluator includes exception text in its report: replace it here.
            self.journal.emit("execution_error", case_id=case.id, error_type=type(error).__name__)
            raise TrialExecutionError("recorded_execution_failure") from None
        self.journal.emit("result", case_id=case.id, result=run.result.model_dump(mode="json"),
                          resources=[resource.model_dump(mode="json") for resource in run.resources])
        return run


def checkpoint(output, report):
    # Atomic replacement inside the exclusively created output directory.
    temporary = output / "report.pending"
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(output / "report.json")


def semantic_report(report):
    """Compare certification including digests, excluding elapsed time and usage."""
    payload = report.model_dump(mode="json") if hasattr(report, "model_dump") else json.loads(json.dumps(report))
    for key in ("median_latency_ms", "jev_requests", "jev_input_tokens", "jev_output_tokens"):
        payload.pop(key, None)
    for row in payload["cases"]:
        row.pop("latency_ms", None)
    return payload


async def recompute(output):
    """Recompute gates from frozen cases and persisted engine results, offline.

    This validates report consistency, not provenance against malicious rewriting
    of every artifact, and cannot turn a fixture response into semantic proof.
    """
    manifest = json.loads((output / "manifest.json").read_text())
    saved = json.loads((output / "report.json").read_text())
    events = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
    results = {event["case_id"]: event for event in events if event["event"] == "result"}
    requests = [event for event in events if event["event"] == "request"]
    responses = [event for event in events if event["event"] == "response"]
    checks = {
        "complete": saved["status"] == "complete",
        "manifest_unchanged": digest(manifest) == saved["manifest_digest"],
        "bounded_requests": len(requests) == len(responses) == MAX_REQUESTS,
        "request_ids": [row["request_id"] for row in requests] == list(range(1, MAX_REQUESTS + 1)),
        "no_errors": not any(event["event"].endswith("error") for event in events),
        "sources_unchanged": saved.get("sources_unchanged") is True,
        "companies": set(saved["companies"]) == set(manifest["companies"]) and len(manifest["companies"]) == 3,
    }
    recomputed = {}
    for company, raw_cases in manifest["companies"].items():
        group = [CardEvaluationCase.model_validate(row) for row in raw_cases]

        class ReplayEngine:
            def __init__(self, replay_cases):
                self.pending = iter(replay_cases)

            async def evaluate(self, card, resources, context_override=None):
                row = results.get(next(self.pending).id)
                if row is None:
                    raise TrialExecutionError("recorded_execution_failure")
                return SimpleNamespace(
                    result=InsightResult.model_validate(row["result"]),
                    resources=[ResourceSnapshot.model_validate(item) for item in row["resources"]],
                )

        report = await CardWorkflowEvaluator(ReplayEngine(group), max_concurrency=1).evaluate(
            group, thresholds=CardEvaluationThresholds.model_validate(manifest["thresholds"]),
            acceptance_outcomes=[Outcome(value) for value in manifest["acceptance_outcomes"]],
        )
        recomputed[company] = report.model_dump(mode="json")
        checks[f"{company}:report"] = semantic_report(report) == semantic_report(saved["companies"].get(company, {"cases": []}))
        checks[f"{company}:acceptance"] = report.acceptance_passed and report.status == "approved"
        checks[f"{company}:card_digest"] = report.card_execution_digests == {
            case.card.id: card_acceptance_digest(case.card) for case in group
        }
        for case in group:
            incoming = [row for row in requests if row["case_id"] == case.id]
            outgoing = [row for row in responses if row["case_id"] == case.id]
            expected_watch = {Outcome.NOTIFY: "present", Outcome.IGNORE: "absent",
                              Outcome.INSUFFICIENT_DATA: "unknown"}[case.expected_outcome]
            result = results.get(case.id, {}).get("result", {})
            watch = result.get("watch_results", [])
            raw_watch = outgoing[0]["answers"]["choices"].get("watch_0", {}) if outgoing else {}
            checks[f"{case.id}:trace"] = (
                len(incoming) == len(outgoing) == 1
                and incoming[0]["request_id"] == outgoing[0]["request_id"]
                and incoming[0]["stage"] == "judgment"
                and set(raw_watch.get("probabilities", {})) == {"present", "absent", "unknown"}
            )
            checks[f"{case.id}:watch"] = (
                len(watch) == 1 and watch[0]["status"] == expected_watch
                and watch[0]["probabilities"] == raw_watch.get("probabilities")
                and (expected_watch != "unknown" or
                     "watch:1" in result["evidence_plan"]["missing_slot_keys"])
            )
    return {"passed": all(checks.values()), "checks": checks, "companies": recomputed}


async def trial(output: Path, key_file, *, live=False):
    if not live:
        raise ValueError("Explicit --live opt-in required after reviewer checks")
    require_acceptance_contract()
    output.mkdir(parents=True, exist_ok=False)
    report = {"scope": SCOPE, "live_jev": True, "external_delivery": False,
              "novice_bootstrap_proof": False, "luna_advantage_established": False,
              "planned_cases": MAX_REQUESTS, "max_requests": MAX_REQUESTS, "retries": 0,
              "status": "running", "passed": False, "attempts": 0, "companies": {}}
    checkpoint(output, report)
    journal = Journal(output)
    judger = None
    try:
        companies = cases()
        frozen = source_freeze()
        manifest = {"scope": SCOPE, **frozen,
                    "companies": {name: [case.model_dump(mode="json") for case in group]
                                  for name, group in companies.items()},
                    "thresholds": THRESHOLDS.model_dump(mode="json"),
                    "acceptance_outcomes": [value.value for value in ACCEPTANCE_OUTCOMES],
                    "card_execution_digests": {group[0].card.id: card_acceptance_digest(group[0].card)
                                               for group in companies.values()}}
        with (output / "manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        report["manifest_digest"] = digest(manifest)
        checkpoint(output, report)
        key = load_api_key(key_file)
        if not key:
            raise ValueError("A configured Jev key is required")
        judger = RecordedJudger(key, journal)
        for company, group in companies.items():
            evaluation = await CardWorkflowEvaluator(
                RecordedEngine(judger, group, journal), max_concurrency=1,
            ).evaluate(group, thresholds=THRESHOLDS, acceptance_outcomes=ACCEPTANCE_OUTCOMES)
            report["companies"][company] = evaluation.model_dump(mode="json")
            report["attempts"] = judger.attempts
            checkpoint(output, report)
        report["sources_unchanged"] = frozen["source_sha256"] == source_freeze()["source_sha256"]
        report["status"] = "complete"
        checkpoint(output, report)
        review = await recompute(output)
        report["checks"] = review["checks"]
        report["passed"] = review["passed"]
    except BaseException as error:
        report["status"] = "interrupted" if not isinstance(error, Exception) else "failed"
        report["error_type"] = type(error).__name__
        report["passed"] = False
        if not isinstance(error, Exception):
            raise
    finally:
        report["attempts"] = judger.attempts if judger else 0
        checkpoint(output, report)
        journal.close()
    return report["passed"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly opt in after review")
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("--live is required; run reviewer checks before opting in")
    raise SystemExit(0 if asyncio.run(trial(args.output, args.key_file, live=True)) else 1)


if __name__ == "__main__":
    main()
