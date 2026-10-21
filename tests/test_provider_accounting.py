import pytest

from evaluations.provider_accounting import provider_accounting


def response(request_id=1, usage=None):
    return {"kind": "api.response", "provider": "jev", "request_id": request_id,
            "usage": {"input_tokens": 100, "output_tokens": 5} if usage is None else usage}


def request(request_id=1):
    return {"kind": "api.request", "provider": "jev", "request_id": request_id}


def test_local_cap_does_not_turn_completed_upstream_usage_into_unknown():
    result = provider_accounting([request(), response(), {
        "kind": "api.rejected", "provider": "jev", "reason": "global_api_request_budget_exhausted"}])
    assert result["forwarded_attempts"] == 1
    assert result["local_rejections"] == 1 and result["workflow_resource_censored"]
    assert result["usage_known"] and result["usage"] == {"input_tokens": 100, "output_tokens": 5}
    assert result["billing_cost"] is None


@pytest.mark.parametrize("events", [
    [request(), response(2)],
    [request(), response(), response()],
    [request(), response(usage={})],
    [request(), response(usage={"input_tokens": True, "output_tokens": 5})],
    [request(), {"kind": "api.error", "provider": "jev", "request_id": 1, "error_type": "HTTP_429"}],
    [request()],
    [{**request(), "request_id": {"invalid": "unhashable"}}, response()],
])
def test_incomplete_or_invalid_telemetry_never_claims_known_total(events):
    result = provider_accounting(events)
    assert result["usage_known"] is False and result["usage"] is None


def test_zero_real_calls_and_foreign_provider_events_remain_zero():
    result = provider_accounting([{**request(), "provider": "openai"}])
    assert result["usage_known"]
    assert result["forwarded_attempts"] == 0
    assert result["usage"] == {"input_tokens": 0, "output_tokens": 0}
