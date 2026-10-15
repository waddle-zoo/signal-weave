"""Offline evidence export for the frozen enterprise onboarding regression."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from evaluations.bootstrap_agent_trial import (
    canonical,
    select_scenarios,
    usage_summary,
    write_exclusive,
)
from evaluations.bootstrap_review_packet import packets
from evaluations.bootstrap_scenarios import _Submission, dataset_digest, score_submission
from evaluations.enterprise_onboarding_journeys import journeys


def validate_execution(report: dict, events: list[dict], fixtures: list[dict]) -> dict:
    """Reject truncated/mixed artifacts instead of exporting plausible totals."""
    expected = {(s["scenario_id"], arm, p["period_id"])
                for s in fixtures for arm in ("luna_bi", "luna_signalweave_jev")
                for p in [s["public"]["onboarding"], *s["public"]["periods"]]}
    observed = [(r["scenario_id"], r["arm"], r["period_id"]) for r in report["rows"]]
    if len(observed) != len(expected) or set(observed) != expected:
        raise ValueError("Report must retain every planned episode exactly once")
    identifiers = {"/".join(parts) for parts in expected}
    if any(e.get("episode") not in identifiers for e in events):
        raise ValueError("Trace contains an unknown episode")
    requests, terminals = Counter(), Counter()
    for event in events:
        if event["kind"] in {"api.request", "api.response", "api.error"}:
            if event.get("provider") not in {"jev", "openai"}:
                raise ValueError("Trace contains an unknown API provider")
            key = (event["episode"], event["provider"], event["request_id"])
            (requests if event["kind"] == "api.request" else terminals)[key] += 1
    if requests != terminals or any(count != 1 for count in requests.values()):
        raise ValueError("Trace has unmatched or duplicate API attempts")
    if usage_summary(events) != report["usage"]:
        raise ValueError("Trace usage differs from report")
    for row in report["rows"]:
        episode = "/".join(str(row[k]) for k in ("scenario_id", "arm", "period_id"))
        if usage_summary([e for e in events if e["episode"] == episode]) != row["usage"]:
            raise ValueError("Trace usage differs from episode")
    return {"expected_episodes": len(expected), "expected_onboardings": len(fixtures) * 2,
            "expected_monitoring_per_arm": sum(len(s["public"]["periods"]) for s in fixtures),
            "validated": True}


def onboarding_stories(report: dict, events: list[dict], fixtures: list[dict]) -> list[dict]:
    companies = {s["scenario_id"]: s for s in fixtures}
    stories = []
    for row in report["rows"]:
        if row["phase"] != "onboarding":
            continue
        company = companies[row["scenario_id"]]
        episode = f"{row['scenario_id']}/{row['arm']}/{row['period_id']}"
        local = [e for e in events if e.get("episode") == episode]
        tools = [e for e in local if e["kind"] == "tool.result" and e.get("actor_role") != "owner_reviewer"]
        counts = Counter(e["name"] for e in tools)
        preview = next((i for i, e in enumerate(tools, 1) if e["name"] in {
            "preview_investigation_report", "simulate_insight_card"} and isinstance(e.get("result"), dict)
                        and e["result"].get("status") == "preview"), None)
        alternatives = {f"{d['adapter']}|{d['resource']}" for d in company["public"]["catalog"]
                        if d.get("metadata", {}).get("scope_note")}
        stories.append({
            "company": company["public"]["company"], "brief": company["public"]["brief"],
            "arm": row["arm"], "status": row["status"], "error": row.get("error"),
            "onboarding_seconds": row["seconds"], "guide_calls": counts["get_signalweave_guide"],
            "author_tool_calls": len(tools), "tool_histogram": dict(counts),
            "first_successful_preview_tool_ordinal": preview,
            "first_preview_wall_time": None,
            "first_preview_time_limit": "Trace has per-tool duration, not timestamps covering intervening model time; do not infer time-to-first-value.",
            "owner_interview": [{"topic": e["arguments"].get("topic"), "answer": e.get("result")}
                                for e in tools if e["name"] == "ask_owner"],
            "owner_reviews": [{"approved": e.get("approved"), "reasons": e.get("reasons"),
                               "review_episode": e.get("episode_result")}
                              for e in local if e["kind"] == "review.result"],
            "tool_errors": [{"tool": e["name"], "error": e["result"]}
                            for e in tools if isinstance(e.get("result"), dict) and e["result"].get("error")],
            "alternate_scope_read_count": sum(e["kind"] == "source.read" and e.get("ref") in alternatives for e in local),
            "saved_notes": row.get("notes"),
        })
    return stories


def export(report_path: Path, output: Path) -> dict:
    raw = report_path.read_bytes()
    report = json.loads(raw)
    fixtures = journeys(report["config"]["seed"])
    fixtures = select_scenarios(fixtures, report["config"].get("selected_scenario_ids"),
                               report["config"].get("selected_companies", len(fixtures)))
    trace_path = report_path.with_name("trace.jsonl")
    with trace_path.open() as stream:
        events = [json.loads(line) for line in stream]
    integrity = validate_execution(report, events, fixtures)
    _validate_monitoring_scores(report["rows"], fixtures, events)
    blind, mapping, compact = packets(report, fixtures_override=fixtures)
    stories = onboarding_stories(report, events, fixtures)
    counts = Counter((e.get("kind"), e.get("provider")) for e in events)
    summary = {
        "full_report_sha256": hashlib.sha256(raw).hexdigest(),
        "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        "planned_episodes": integrity["expected_episodes"], "retained_episodes": len(report["rows"]),
        "integrity": integrity,
        "onboarding_stories": len(stories),
        "jev_attempts": counts["api.request", "jev"],
        "jev_failed_attempts": counts["api.error", "jev"],
        "codex_invocations": counts["api.request", "openai"],
        "codex_api_error_events": counts["api.error", "openai"],
        "failed_author_monitor_episodes": sum(r["status"] != "complete" for r in report["rows"]),
        "failed_owner_review_invocations": sum(e["kind"] == "review.result" and
            e.get("episode_result", {}).get("status") != "complete" for e in events),
        "event_kind_counts": dict(Counter(e["kind"] for e in events)),
        "blindness_limit": "Arm metadata removed, but output style can reveal treatment. Give reviewers only blind-review.json, never review-key.json or this directory.",
        "budget_censored": report["budget_censored"],
        "native_correctness": {},
        "acceptance_status": _acceptance_status(report["rows"]),
        "narrative_gate": "unassessed",
        "ledger_limit": "Hashes record supplied artifacts; they do not authenticate historical execution or code.",
        "limit": "Scripted owner interviews with an actual model agent. Not real users, enterprise certification, or independent peer review.",
    }
    for arm in ("luna_bi", "luna_signalweave_jev"):
        rows = [r for r in report["rows"] if r["phase"] == "monitoring" and r["arm"] == arm]
        native = [r["raw_system_decision"] for r in rows if r.get("raw_system_decision")]
        summary["native_correctness"][arm] = {
            "planned_monitoring_periods": integrity["expected_monitoring_per_arm"],
            "completed_agent_reports": sum(r["status"] == "complete" for r in rows),
            "native_decisions_available": len(native),
            "native_decisions_missing": len(rows) - len(native),
            "native_metric_applicable": arm == "luna_signalweave_jev",
            "native_outcome_and_recipient_correct": sum(n["outcome_correct"] and n["recipients_correct"] for n in native),
            "agent_changed_native_outcome": sum(n["agent_changed_outcome"] for n in native),
        }
    output.mkdir(parents=True, exist_ok=False)
    compact["full_report_sha256"] = summary["full_report_sha256"]
    compact["acceptance_status"] = summary["acceptance_status"]
    compact["narrative_gate"] = "unassessed"
    write_exclusive(output / "results.json", compact)
    write_exclusive(output / "blind-review.json", {"cases": blind})
    write_exclusive(output / "review-key.json", mapping)
    write_exclusive(output / "onboarding-stories.json", stories)
    write_exclusive(output / "execution-audit.json", summary)
    return summary


def _monitoring_trace_inputs(row: dict, events: list[dict], identity: str) -> tuple[dict | None, dict | None]:
    """Bind retained inputs to the recorded tool receipts, not mutable score caches."""
    submissions = []
    systems = []
    for event in events:
        if event["kind"] == "tool.result" and event.get("name") == "submit_analysis":
            receipt = event.get("result")
            if not isinstance(receipt, dict):
                raise ValueError(f"Malformed submission trace receipt: {identity}")
            if receipt.get("error") and receipt.get("recorded") is not True:
                continue  # A rejected call is not a submission.
            if (receipt.get("recorded") is not True or receipt.get("delivery_enabled") is not False
                    or receipt.get("error") or event.get("actor_role", "author") != "author"):
                raise ValueError(f"Invalid successful submission trace receipt: {identity}")
            try:
                submissions.append(_Submission.model_validate(event["arguments"]).model_dump(mode="json"))
            except (KeyError, ValueError, TypeError) as error:
                raise ValueError(f"Invalid submission trace arguments: {identity}") from error
        elif event["kind"] == "system.evaluation":
            if row["arm"] != "luna_signalweave_jev" or not isinstance(event.get("response"), dict):
                raise ValueError(f"Invalid native routing trace response: {identity}")
            systems.append(event["response"])
    if len(submissions) > 1 or (row["status"] == "complete" and len(submissions) != 1):
        raise ValueError(f"Completed monitoring requires one successful submission trace receipt: {identity}")
    if len(systems) > 1 or (row["status"] == "complete" and row["arm"] == "luna_signalweave_jev"
                            and len(systems) != 1):
        raise ValueError(f"Completed treatment requires one native routing trace response: {identity}")
    submission = submissions[0] if submissions else None
    system_output = systems[0] if systems else None
    if canonical(row.get("submission")) != canonical(submission):
        raise ValueError(f"Retained submission differs from successful submission trace: {identity}")
    if canonical(row.get("system_output")) != canonical(system_output):
        raise ValueError(f"Retained native routing input differs from system evaluation trace: {identity}")
    return submission, system_output


def _validate_monitoring_scores(rows: list[dict], fixtures: list[dict], events: list[dict]) -> None:
    """Check trace-bound inputs and recompute scores against private labels offline."""
    scenarios = {s["scenario_id"]: s for s in fixtures}
    phases = {(s["scenario_id"], p["period_id"]): phase for s in fixtures
              for phase, periods in (("onboarding", [s["public"]["onboarding"]]),
                                     ("monitoring", s["public"]["periods"])) for p in periods}
    by_episode = defaultdict(list)
    for event in events:
        by_episode[event["episode"]].append(event)
    for row in rows:
        if row["phase"] != phases[row["scenario_id"], row["period_id"]]:
            raise ValueError("Component episode phase differs from the planned period")
        if row["phase"] != "monitoring":
            continue
        scenario = scenarios[row["scenario_id"]]
        identity = f"{row['scenario_id']}/{row['arm']}/{row['period_id']}"
        submission, system_output = _monitoring_trace_inputs(row, by_episode[identity], identity)
        try:
            score = score_submission(
                scenario, row["period_id"], submission or {},
                inspected_refs=row["inspected_refs"], asked_owner_topics=row["asked_owner_topics"],
            )
        except Exception as error:
            raise ValueError(f"Cannot recompute structured score: {identity}") from error
        if row["status"] != "complete":
            score["exact"] = False
        if canonical(row.get("score")) != canonical(score):
            raise ValueError(f"Cached structured score differs from recomputation: {identity}")
        system = (system_output or {}).get("result")
        native = None
        if system:
            expected = scenario["private"]["periods"][row["period_id"]]
            destination_keys = {d["destination"]: d["key"] for d in scenario["public"]["destinations"]}
            destinations = sorted({method["destination"] for method in system.get("delivery_methods", [])})
            routes = sorted({destination_keys.get(destination, destination) for destination in destinations})
            native = {
                "outcome": system.get("outcome"), "recipients": routes, "destinations": destinations,
                "outcome_correct": system.get("outcome") == expected["outcome"],
                "recipients_correct": set(routes) == set(expected["recipients"]),
                "agent_changed_outcome": system.get("outcome") != (submission or {}).get("outcome"),
                "scope": "raw system routing only; not numerical or narrative correctness",
            }
        if canonical(row.get("raw_system_decision")) != canonical(native):
            raise ValueError(f"Cached native routing differs from recomputation: {identity}")


def _acceptance_status(rows: list[dict]) -> str:
    """A structured failure fails acceptance; structured success cannot pass narrative review."""
    treatment = [row for row in rows if row["arm"] == "luna_signalweave_jev"]
    for row in treatment:
        if row["status"] != "complete":
            return "not_passed"
        if row["phase"] == "monitoring":
            native = row.get("raw_system_decision") or {}
            if (row["score"]["exact"] is not True or native.get("outcome_correct") is not True
                    or native.get("recipients_correct") is not True):
                return "not_passed"
    return "unassessed"


def export_cohort(report_paths: list[Path], output: Path) -> dict:
    """Export a staged six-company ledger; never synthesize one run or clock.

    All components must retain both arms and every planned period, including
    failed episodes. Per-process Jev caps may differ but must total 144. Other
    execution settings and the complete recorded source hash maps must match.
    Structured scores and native routing are recomputed; narratives remain unassessed.
    """
    if not 2 <= len(report_paths) <= 6:
        raise ValueError("A staged cohort requires two to six component reports")
    variable_fields = {
        "selected_companies", "selected_scenario_ids", "dataset_digest",
        "public_context_digest", "clock_rebased_to", "max_api_requests", "source_fingerprint",
    }
    required_settings = {
        "seed", "model", "effort", "owner_review", "owner_review_model", "owner_review_effort",
        "owner_review_attempts_per_arm_company", "owner_review_timeout_seconds",
        "agent_transport", "episode_timeout_seconds", "max_tool_calls", "max_turns",
        "max_output_tokens", "api_request_budget_scope",
    }
    components, rows, all_events = [], [], []
    seen_companies: set[str] = set()
    reference_settings = reference_hashes = None
    cohort_fixtures = []
    for report_path in report_paths:
        report_path = report_path.resolve()
        raw = report_path.read_bytes()
        report = json.loads(raw)
        config = report["config"]
        if not required_settings <= config.keys():
            raise ValueError("Component is missing required execution settings")
        hashes = config.get("source_fingerprint", {}).get("sha256")
        if not isinstance(hashes, dict) or not hashes or any(
            not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value) for value in hashes.values()
        ):
            raise ValueError("Component must record a nonempty source SHA256 map")
        settings = {key: value for key, value in config.items() if key not in variable_fields}
        if reference_settings is None:
            reference_settings, reference_hashes = settings, hashes
            cohort_fixtures = journeys(config["seed"])
        elif settings != reference_settings or hashes != reference_hashes:
            raise ValueError("Components have mixed execution settings or source fingerprints")
        if config["agent_transport"] != "codex_cli" or config["api_request_budget_scope"] != "Jev only":
            raise ValueError("Cohort requires saved Codex transport and separately capped Jev attempts")
        selected = config.get("selected_scenario_ids")
        if (not isinstance(selected, list) or not selected or len(set(selected)) != len(selected)
                or config.get("selected_companies") != len(selected)):
            raise ValueError("Component must declare unique selected companies and their exact count")
        if seen_companies.intersection(selected):
            raise ValueError("Components contain duplicate companies")
        fixtures = select_scenarios(cohort_fixtures, selected, len(selected))
        if {s["scenario_id"] for s in fixtures} != set(selected):
            raise ValueError("Component selects companies outside the cohort")
        if config.get("dataset_digest") != dataset_digest(fixtures):
            raise ValueError("Component fixture digest differs from the expected dataset")
        trace_path = report_path.with_name("trace.jsonl")
        trace_raw = trace_path.read_bytes()
        events = [json.loads(line) for line in trace_raw.splitlines()]
        integrity = validate_execution(report, events, fixtures)
        _validate_monitoring_scores(report["rows"], fixtures, events)
        cap = config.get("max_api_requests")
        attempts = report["usage"]["jev"]["attempts"]
        if type(cap) is not int or cap <= 0 or attempts > cap:
            raise ValueError("Component exceeds or omits its Jev attempt cap")
        if not isinstance(config.get("clock_rebased_to"), str) or not config["clock_rebased_to"]:
            raise ValueError("Component must retain its own rebased clock")
        components.append({
            "report_path": str(report_path), "report_sha256": hashlib.sha256(raw).hexdigest(),
            "trace_path": str(trace_path), "trace_sha256": hashlib.sha256(trace_raw).hexdigest(),
            "clock_rebased_to": config["clock_rebased_to"], "config": config,
            "integrity": integrity, "budget_censored": report["budget_censored"],
            "jev_attempt_cap": cap, "jev_attempts": attempts,
            "codex_invocations": report["usage"]["openai"]["attempts"],
        })
        seen_companies.update(selected)
        rows.extend(report["rows"])
        all_events.extend(events)
    if len(cohort_fixtures) != 6 or seen_companies != {s["scenario_id"] for s in cohort_fixtures}:
        raise ValueError("Cohort must cover the full six-company union")
    integrity = validate_execution({"rows": rows, "usage": usage_summary(all_events)},
                                   all_events, cohort_fixtures)
    if integrity["expected_episodes"] != 48 or integrity["expected_monitoring_per_arm"] != 18:
        raise ValueError("Cohort must contain 48 episodes and 18 later periods per arm")
    if sum(c["jev_attempt_cap"] for c in components) != 144:
        raise ValueError("Component Jev caps must total the staged cohort ceiling of 144")
    resolved_models = {e["response"]["model"] for e in all_events
                       if e["kind"] == "api.response" and e.get("provider") == "jev"
                       and isinstance(e.get("response"), dict) and e["response"].get("model")}
    if len(resolved_models) > 1:
        raise ValueError("Components contain mixed resolved Jev models")
    arms = {}
    for arm in ("luna_bi", "luna_signalweave_jev"):
        setup = [r for r in rows if r["arm"] == arm and r["phase"] == "onboarding"]
        later = [r for r in rows if r["arm"] == arm and r["phase"] == "monitoring"]
        native = [r["raw_system_decision"] for r in later if r.get("raw_system_decision")]
        arms[arm] = {
            "planned_onboardings": 6,
            "completed_onboardings": sum(r["status"] == "complete" for r in setup),
            "planned_monitoring_periods": 18,
            "completed_agent_reports": sum(r["status"] == "complete" for r in later),
            "final_structured_exact": sum(r["status"] == "complete" and
                                          (r.get("score") or {}).get("exact") is True for r in later),
            "native_metric_applicable": arm == "luna_signalweave_jev",
            "native_decisions_available": len(native), "native_decisions_missing": 18 - len(native),
            "native_outcome_and_recipient_correct": sum(n.get("outcome_correct") is True and
                                                        n.get("recipients_correct") is True for n in native),
            "agent_changed_native_outcome": sum(n.get("agent_changed_outcome") is True for n in native),
        }
    result = {
        "kind": "staged_six_company_cohort", "components": components,
        "integrity": integrity, "retained_episodes": len(rows), "arms": arms,
        "jev_attempt_cap": 144, "jev_attempts": sum(c["jev_attempts"] for c in components),
        "codex_invocations": sum(c["codex_invocations"] for c in components),
        "budget_censored": any(c["budget_censored"] for c in components),
        "resolved_jev_models": sorted(resolved_models), "narrative_gate": "unassessed",
        "acceptance_status": _acceptance_status(rows),
        "limitations": [
            "Separate processes and rebased clocks; a staged known-family regression, not one randomized run.",
            "Native correctness covers routing only. Final exact scores cover structured fields; narrative review remains separate.",
            "Missing and failed episodes remain in denominators. No combined latency, median, cost savings or generalized success claim.",
            "Hashes record supplied artifacts; they do not authenticate historical execution or code.",
        ],
    }
    output.mkdir(parents=True, exist_ok=False)
    write_exclusive(output / "cohort.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--component", type=Path, action="append", default=[],
                        help="Additional report to validate as a staged six-company cohort; repeat per component.")
    args = parser.parse_args()
    result = (export_cohort([args.report, *args.component], args.output) if args.component
              else export(args.report, args.output))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
