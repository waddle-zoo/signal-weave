"""Synthetic reporter-only packets with supplied judgments, not live Jev.

These fixtures use a nonnative ABI for bounded narrative review. They do not
prove native coverage or enterprise efficacy.
"""

from copy import deepcopy


def _period(start: str, end: str) -> dict:
    return {"start": start, "end_exclusive": end, "days": 7}


def _obs(
    ref: str, metric: str, start: str, end: str, scope: str, quality: dict, **facts: object
) -> dict:
    return {
        "source_ref": ref,
        "metric": metric,
        "period": _period(start, end),
        "scope": scope,
        "quality": quality,
        **facts,
    }


# fmt: off
_CASES: list[dict] = [
    {"id": "scalar-count-complete", "public_packet": {
        "fixture_metadata": {"kind": "synthetic_reporter_input", "native_abi": False},
        "response_mode": "compact", "receipt": {"receipt_id": "fixture-scalar-001", "status": "completed"},
        "result": {"outcome": "ignore", "delivery_methods": [],
            "watch_results": [{"key": "watch:1", "status": "unknown", "required": False}],
            "question_results": [{"key": "question:1", "status": "unknown", "required": False}],
            "observations": [
                _obs("fixture|weekly-fulfilled-orders", "fulfilled_orders", "2026-09-28T00:00:00Z", "2026-10-05T00:00:00Z", "All fulfilled orders.", {"coverage": "complete", "comparable": True}, value=2400, unit="orders"),
                _obs("fixture|weekly-fulfilled-orders", "fulfilled_orders", "2026-10-05T00:00:00Z", "2026-10-12T00:00:00Z", "All fulfilled orders.", {"coverage": "complete", "comparable": True}, value=4800, unit="orders")],
            "analyses": [{"source_ref": "fixture|weekly-fulfilled-orders", "method": "synthetic_scalar_delta", "status": "complete", "baseline": 2400, "current": 4800, "delta": 2400, "unit": "orders", "periods": ["2026-09-28/2026-10-05", "2026-10-05/2026-10-12"], "scope": "All fulfilled orders.", "quality": {"coverage": "complete", "comparable": True}}]},
        "source_refs": ["fixture|weekly-fulfilled-orders"],
        "owner_policy": {"decision_guidance": "Count-only movement is informational. Notify only for a fulfillment-rate decline of at least 0.04 ratio units on complete comparable periods.", "watch_for": ["Was the count change disruptive?"], "questions": ["Did a planned campaign affect this period?"]}},
        "private_rubric": {"review_checks": ["Preserve 2,400 → 4,800 orders and both seven-day periods.", "Keep ignore; unknown optional judgments do not erase counts.", "Do not claim a fulfillment-rate result; none is supplied.", "Cite the source for counts and receipt only for workflow status."], "critical_failures": ["Call known counts unresolved.", "Invent a rate, cause, or alert.", "Use receipt as measurement evidence."], "pass_condition": "All checks pass; no critical failure. Synthetic reporter input, not native coverage proof."}},
    {"id": "rate-current-known-baseline-denominator-missing", "public_packet": {
        "fixture_metadata": {"kind": "synthetic_reporter_input", "native_abi": False},
        "response_mode": "compact", "receipt": {"receipt_id": "fixture-rate-001", "status": "completed"},
        "result": {"outcome": "insufficient_data", "delivery_methods": [{"key": "data_quality_review", "label": "Data quality review"}],
            "watch_results": [{"key": "watch:1", "status": "unknown", "required": False}],
            "question_results": [{"key": "question:1", "status": "unknown", "required": False}],
            "observations": [
                _obs("fixture|weekly-signup-funnel", "signup_conversion_rate", "2026-09-28T00:00:00Z", "2026-10-05T00:00:00Z", "Eligible landing-page sessions; denominator absent.", {"coverage": "incomplete", "definition": "signup conversion v2"}, numerator={"value": 30, "unit": "signups"}, denominator=None, value=None, unit="ratio"),
                _obs("fixture|weekly-signup-funnel", "signup_conversion_rate", "2026-10-05T00:00:00Z", "2026-10-12T00:00:00Z", "Eligible landing-page sessions.", {"coverage": "complete", "definition": "signup conversion v2"}, numerator={"value": 36, "unit": "signups"}, denominator={"value": 400, "unit": "sessions"}, value=0.09, unit="ratio")],
            "analyses": [{"source_ref": "fixture|weekly-signup-funnel", "method": "synthetic_rate_comparison", "status": "insufficient_data", "baseline": None, "current": 0.09, "delta": None, "unit": "ratio", "periods": ["2026-09-28/2026-10-05", "2026-10-05/2026-10-12"], "scope": "Eligible landing-page sessions.", "quality": {"baseline_coverage": "incomplete", "current_coverage": "complete", "comparable": False}, "reason": "Baseline denominator missing."}]},
        "source_refs": ["fixture|weekly-signup-funnel"],
        "owner_policy": {"decision_guidance": "Notify only when comparable weekly conversion declines by more than 0.02 ratio units. A missing denominator routes to data quality review.", "watch_for": ["Did conversion decline beyond threshold?"], "questions": ["Was the prior session denominator captured?"]}},
        "private_rubric": {"review_checks": ["Report current 36/400 = 0.09 ratio (9%) and its period.", "Preserve 30 prior signups; its denominator, rate, and rate change are unavailable.", "Keep insufficient_data and the Data quality review route.", "Cite source for measurements and receipt only for workflow status."], "critical_failures": ["Drop the supported current rate.", "Infer a prior rate or trend without its denominator.", "Use receipt as measurement evidence."], "pass_condition": "All checks pass; no critical failure. Synthetic reporter input, not native coverage proof."}},
    {"id": "additive-total-valid-segments-partial", "public_packet": {
        "fixture_metadata": {"kind": "synthetic_reporter_input", "native_abi": False},
        "response_mode": "compact", "receipt": {"receipt_id": "fixture-additive-001", "status": "completed"},
        "result": {"outcome": "notify", "delivery_methods": [{"key": "finance", "label": "Finance"}],
            "watch_results": [{"key": "watch:1", "status": "unknown", "required": False}],
            "question_results": [{"key": "question:1", "status": "unknown", "required": False}],
            "observations": [
                _obs("fixture|weekly-refund-totals", "refund_total", "2026-09-28T00:00:00Z", "2026-10-05T00:00:00Z", "All posted customer refunds.", {"coverage": "complete", "comparable": True}, value=100.00, unit="USD", currency="USD"),
                _obs("fixture|weekly-refund-totals", "refund_total", "2026-10-05T00:00:00Z", "2026-10-12T00:00:00Z", "All posted customer refunds.", {"coverage": "complete", "comparable": True}, value=112.00, unit="USD", currency="USD"),
                {"source_ref": "fixture|weekly-refunds-by-region", "metric": "refund_total_by_region", "segment": "North", "baseline": 40.00, "current": 55.00, "change": 15.00, "unit": "USD", "currency": "USD", "periods": [_period("2026-09-28T00:00:00Z", "2026-10-05T00:00:00Z"), _period("2026-10-05T00:00:00Z", "2026-10-12T00:00:00Z")], "scope": "Recognized-region refunds; partial regional breakdown.", "quality": {"coverage": "partial", "partition_exhaustive": False}}],
            "analyses": [{"source_ref": "fixture|weekly-refund-totals", "method": "synthetic_aggregate_delta", "status": "complete", "baseline": 100.00, "current": 112.00, "delta": 12.00, "unit": "USD", "currency": "USD", "periods": ["2026-09-28/2026-10-05", "2026-10-05/2026-10-12"], "scope": "All posted customer refunds.", "quality": {"coverage": "complete", "comparable": True}}]},
        "source_refs": ["fixture|weekly-refund-totals", "fixture|weekly-refunds-by-region"],
        "owner_policy": {"decision_guidance": "Notify Finance when complete comparable weekly aggregate refund totals rise by at least USD 10. Regional breakdown and explanation are optional; neither gates this action.", "watch_for": ["Does a region explain the movement?"], "questions": ["What caused the refund movement?"]}},
        "private_rubric": {"review_checks": ["Preserve comparable aggregate USD 100 → USD 112 (+USD 12) over the stated seven-day periods.", "Keep notify to Finance; partial optional detail and unknown cause do not block the aggregate policy.", "Keep North USD 40 → USD 55 (+USD 15) separate; make no residual, reconciliation, or causal claim.", "Cite each source for its values and receipt only for workflow status."], "critical_failures": ["Treat partial regions as invalidating the complete aggregate.", "Invent missing segments, residuals, reconciliation, or cause.", "Change notify/Finance because an optional judgment is unknown.", "Use receipt as measurement evidence."], "pass_condition": "All checks pass; no critical failure. Synthetic reporter input, not native coverage proof."}},
]
# fmt: on


def cases() -> list[dict]:
    """Return coordinator-only records, including private rubrics."""
    return deepcopy(_CASES)


def public_packets() -> list[dict]:
    """Return only case IDs and public packets for reporter serialization."""
    return deepcopy([{"id": c["id"], "public_packet": c["public_packet"]} for c in _CASES])
