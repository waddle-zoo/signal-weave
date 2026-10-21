"""Read actual provider telemetry without confusing local research caps with API use."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def provider_accounting(events: list[dict], provider: str = "jev") -> dict:
    """Reconcile forwarded requests; never infer unreported tokens or billing.

    A proxy rejection happens before forwarding and is retained separately. It
    contaminates workflow interpretation, not the known usage of prior responses.
    """
    rows = [event for event in events if event.get("provider") == provider]
    requests = [row for row in rows if row.get("kind") == "api.request"]
    responses = [row for row in rows if row.get("kind") == "api.response"]
    errors = [row for row in rows if row.get("kind") == "api.error"]
    rejections = [row for row in rows if row.get("kind") == "api.rejected"]
    keys = ("input_tokens", "output_tokens")

    def valid_usage(row):
        usage = row.get("usage")
        return isinstance(usage, dict) and all(
            type(usage.get(key)) is int and usage[key] >= 0 for key in keys
        )

    identifiers = [row.get("request_id") for row in requests + responses + errors]
    valid_ids = all(type(value) in (str, int) and value != "" for value in identifiers)
    matched = False
    if valid_ids:
        sent = Counter(row["request_id"] for row in requests)
        received = Counter(row["request_id"] for row in responses + errors)
        matched = sent == received and all(count == 1 for count in sent.values())
    known = matched and not errors and all(valid_usage(row) for row in responses)
    observed = {key: sum(row["usage"][key] for row in responses if valid_usage(row)) for key in keys}
    return {
        "forwarded_attempts": len(requests),
        "successful_responses": len(responses),
        "upstream_errors": len(errors),
        "local_rejections": len(rejections),
        "request_response_ids_reconciled": matched,
        "usage_known": known,
        "usage": observed if known else None,
        "observed_response_usage": observed,
        "workflow_resource_censored": bool(rejections),
        "billing_cost": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="Retained JSONL audit; never modified")
    parser.add_argument("--provider", default="jev")
    args = parser.parse_args()
    try:
        with args.trace.open(encoding="utf-8") as stream:
            events = [json.loads(line) for line in stream if line.strip()]
        if any(not isinstance(event, dict) for event in events):
            raise ValueError("Audit events must be JSON objects")
    except (OSError, ValueError) as exc:
        parser.error(f"Cannot account for trace: {exc}")
    print(json.dumps(provider_accounting(events, args.provider), indent=2))


if __name__ == "__main__":
    main()
