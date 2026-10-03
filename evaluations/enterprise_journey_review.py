"""Offline evidence export for the frozen enterprise onboarding regression."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from evaluations.bootstrap_agent_trial import select_scenarios, usage_summary, write_exclusive
from evaluations.bootstrap_review_packet import packets
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
    blind, mapping, compact = packets(report, fixtures_override=fixtures)
    trace_path = report_path.with_name("trace.jsonl")
    with trace_path.open() as stream:
        events = [json.loads(line) for line in stream]
    integrity = validate_execution(report, events, fixtures)
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
    write_exclusive(output / "results.json", compact)
    write_exclusive(output / "blind-review.json", {"cases": blind})
    write_exclusive(output / "review-key.json", mapping)
    write_exclusive(output / "onboarding-stories.json", stories)
    write_exclusive(output / "execution-audit.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.report, args.output), indent=2))


if __name__ == "__main__":
    main()
