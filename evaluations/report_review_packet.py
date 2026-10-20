"""Build arm-label-masked human-review packets from recorded runner evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone


def _aware_clock(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO datetime with a timezone")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _prompt_payload(event: dict) -> dict:
    prompt = event.get("prompt")
    if not isinstance(prompt, str) or not prompt.splitlines():
        raise ValueError("matching api.request must contain a canonical JSON prompt line")
    payload = json.loads(prompt.splitlines()[-1])
    if not isinstance(payload, dict):
        raise ValueError("matching api.request final prompt line must be an object")
    return payload


def build_report_review_packet(report: dict, audit_events: list[dict], owner_context: dict, review_protocol: dict) -> tuple[dict, dict]:
    """Return an opaque ordered packet and a separate case-to-run coordinate map."""
    protocol = report.get("protocol")
    if not isinstance(protocol, str) or not protocol:
        raise ValueError("report protocol is required")
    sink_name = report.get("report_sink", "submit_analysis")
    if not isinstance(sink_name, str) or sink_name not in {"submit_analysis", "record_report"}:
        raise ValueError("unsupported report sink")

    entries = report.get("episodes", [])
    completed = [episode for episode in entries if episode.get("agent", {}).get("status") == "complete"]
    cases, coordinates, seen_episodes = [], {}, set()
    for episode in completed:
        arm, period_id = episode.get("arm"), episode.get("period_id")
        if not isinstance(arm, str) or not isinstance(period_id, str):
            raise ValueError("completed episode requires arm and period_id coordinates")
        episode_id = f"{arm}:{period_id}"
        if episode_id in seen_episodes:
            raise ValueError("duplicate completed episode coordinates")
        seen_episodes.add(episode_id)
        episode_events = [event for event in audit_events if event.get("episode") == episode_id]
        requests = [event for event in episode_events if event.get("kind") == "api.request" and event.get("provider") == "openai"]
        if len(requests) != 1:
            raise ValueError(f"completed episode {episode_id} requires exactly one matching prompt")
        prompt = _prompt_payload(requests[0])
        reporter_period = prompt.get("period")
        if not isinstance(reporter_period, dict) or reporter_period.get("period_id") != period_id:
            raise ValueError(f"completed episode {episode_id} has a mismatched reporter period")
        cutoff = _aware_clock(reporter_period.get("as_of"), "reporter_period.as_of")
        read_clock = _aware_clock(reporter_period.get("captured_at"), "reporter_period.captured_at")

        submission = episode.get("submission")
        if not isinstance(submission, dict):
            raise ValueError(f"completed episode {episode_id} has no recorded report")
        final_reply = episode.get("agent", {}).get("final_message")
        if not isinstance(final_reply, str):
            raise ValueError(f"completed episode {episode_id} has no final reply")
        submit_events = [event for event in episode_events
                         if event.get("kind") == "tool.result" and event.get("name") == sink_name
                         and isinstance(event.get("result"), dict) and event["result"].get("recorded") is True]
        if len(submit_events) != 1:
            raise ValueError(f"completed episode {episode_id} requires exactly one successful submission")
        submit_event = submit_events[0]
        if submit_event["result"].get("delivery_enabled") is not False:
            raise ValueError(f"completed episode {episode_id} has an invalid submission result")
        arguments = submit_event.get("arguments")
        fields = ("outcome", "recipients", "summary")
        if sink_name == "submit_analysis":
            fields = (*fields, "evidence_refs")
        if (not isinstance(arguments, dict) or any(field not in submission or field not in arguments for field in fields)
                or any(arguments[field] != submission[field] for field in fields)
                or (sink_name == "record_report" and (set(arguments) != set(fields) or set(submission) != set(fields)))
                or not isinstance(submission["recipients"], list)
                or (sink_name == "submit_analysis" and not isinstance(submission["evidence_refs"], list))
                or not isinstance(submission["summary"], str)):
            raise ValueError(f"completed episode {episode_id} submission differs from its recorded report")

        native_events = [event for event in episode_events
                         if event.get("kind") == "tool.result" and event.get("name") == "evaluate_insight_card"
                         and isinstance(event.get("result"), dict) and isinstance(event["result"].get("receipt"), dict)]
        card_id = prompt.get("card_id")
        receipts = []
        if card_id is None:
            if native_events:
                raise ValueError(f"baseline episode {episode_id} has an unexpected native receipt")
        else:
            context = prompt.get("accepted_context")
            policy = context.get("accepted_policy") if isinstance(context, dict) else None
            version = policy.get("version") if isinstance(policy, dict) else None
            key = f"{protocol}:{period_id}"
            if (not isinstance(card_id, str) or not card_id or not isinstance(policy, dict)
                    or policy.get("id") != card_id or type(version) is not int
                    or prompt.get("idempotency_key") != key or len(native_events) != 1):
                raise ValueError(f"completed episode {episode_id} has an invalid evaluation request")
            native_event = native_events[0]
            native_args = native_event.get("arguments", {})
            native_result = native_event["result"]
            receipt = native_result["receipt"]
            result = native_result.get("result", {})
            if not isinstance(native_args, dict) or not isinstance(result, dict):
                raise ValueError(f"completed episode {episode_id} has an invalid evaluation result")
            methods = result.get("delivery_methods")
            result_routes = ([route.get("key") for route in methods]
                             if isinstance(methods, list) and all(isinstance(route, dict) for route in methods)
                             else None)
            if (not isinstance(receipt.get("receipt_id"), str) or not receipt["receipt_id"].strip()
                    or native_args.get("card_id") != card_id or native_args.get("idempotency_key") != key
                    or receipt.get("card_id") != card_id or receipt.get("card_version") != version
                    or receipt.get("idempotency_key") != key or receipt.get("status") != "delivery_disabled"
                    or receipt.get("delivery_enabled") is not False or receipt.get("outcome") != result.get("outcome")
                    or receipt.get("delivery_method_keys") != result_routes or result.get("card_id") != card_id or result_routes is None):
                raise ValueError(f"completed episode {episode_id} has a mismatched or delivering receipt")
            receipt_fields = ("receipt_id", "card_id", "card_version", "idempotency_key", "outcome", "delivery_mode", "status", "delivery_enabled", "delivery_method_keys")
            receipts.append({"call_arguments": copy.deepcopy(native_args),
                             "receipt": {field: copy.deepcopy(receipt.get(field)) for field in receipt_fields},
                             "native_outcome": copy.deepcopy(result.get("outcome")), "native_routes": copy.deepcopy(result_routes)})

        source_truth = []
        for event in episode_events:
            if event.get("kind") != "source.read":
                continue
            snapshot = event.get("snapshot")
            if not isinstance(snapshot, dict):
                raise ValueError(f"completed episode {episode_id} has an invalid source snapshot")
            capture_clock_field = next((field for field in ("source_captured_at", "captured_at")
                                        if snapshot.get(field) is not None), None)
            source_clock = snapshot.get(capture_clock_field) if capture_clock_field else None
            age = None if source_clock is None else (read_clock - _aware_clock(source_clock, "source snapshot capture time")).total_seconds() / 3600
            source_truth.append({"source_ref": event.get("ref"), "snapshot": copy.deepcopy(snapshot), "source_snapshot_capture_age_hours": age, "capture_clock_field_used": capture_clock_field})

        opaque = hashlib.sha256(f"{protocol}:{episode_id}".encode()).hexdigest()[:16]
        case_id = f"case-{opaque}"
        if case_id in coordinates:
            raise ValueError("opaque case identifier collision")
        coordinates[case_id] = {"episode": episode_id, "arm": arm, "period_id": period_id}
        cases.append({
            "id": case_id,
            "reporter_period": copy.deepcopy(reporter_period),
            "actual_measurement_cutoff": cutoff.isoformat(), "actual_read_clock": read_clock.isoformat(),
            "source_truth": source_truth,
            "recorded_report": copy.deepcopy(submission), "agent_final_reply": final_reply,
            "proposed_outcome": submission["outcome"], "policy_triggered_routes": copy.deepcopy(submission["recipients"]),
            "declared_source_refs": copy.deepcopy(submission.get("evidence_refs", [])),
            "successful_submit_analysis": {
                "arguments": copy.deepcopy(submit_event["arguments"]), "result": copy.deepcopy(submit_event["result"]),
            },
            "verified_workflow_receipts": receipts,
        })
        if sink_name == "record_report":
            cases[-1].pop("declared_source_refs")
            cases[-1]["source_citation_format"] = "inline_in_summary"
            cases[-1]["successful_record_report"] = cases[-1].pop("successful_submit_analysis")
    cases.sort(key=lambda case: case["id"])
    ordered_coordinates = {case["id"]: coordinates[case["id"]] for case in cases}
    planned = report.get("planned_episode_count")
    observed = len(entries)
    if planned is not None and (type(planned) is not int or planned < observed):
        raise ValueError("planned_episode_count must be an integer covering observed episodes")
    status = report.get("cohort_status") or report.get("status") or (
        "completed" if report.get("completed") is True else "incomplete_or_stopped")
    packet = {
        "protocol": protocol,
        "cohort_status": status,
        "timing_interpretation": (
            "reporter_period.as_of is assigned measurement cutoff; captured_at is separate read clock; "
            "capture age is not proof of metric freshness"
        ),
        "case_counts": {"completed": len(completed), "observed": observed, "incomplete": observed - len(completed),
                        "planned": planned, "unrun": None if planned is None else planned - observed},
        "owner_context": copy.deepcopy(owner_context),
        "review_protocol": copy.deepcopy(review_protocol),
        "cases": cases,
    }
    return packet, ordered_coordinates
