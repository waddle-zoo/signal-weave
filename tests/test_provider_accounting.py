import json

import pytest

from evaluations.provider_accounting import main, provider_accounting


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


def test_cli_reads_actual_trace_without_modifying_it(tmp_path, monkeypatch, capsys):
    trace = tmp_path / "trace.jsonl"
    original = "\n".join(json.dumps(event) for event in [request(), response()]) + "\n"
    trace.write_text(original)
    monkeypatch.setattr("sys.argv", ["provider_accounting", str(trace)])
    main()
    assert json.loads(capsys.readouterr().out)["usage_known"] is True
    assert trace.read_text() == original


@pytest.mark.parametrize("raw", ["not-json", "[]\n", '"string"\n'])
def test_cli_rejects_malformed_trace_instead_of_claiming_zero(tmp_path, monkeypatch, capsys, raw):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(raw)
    monkeypatch.setattr("sys.argv", ["provider_accounting", str(trace)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert capsys.readouterr().out == ""
