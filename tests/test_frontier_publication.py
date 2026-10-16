"""Offline controls for the separately bounded analyst-publication trial."""

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from evaluations import frontier_publication as trial


def analyst(tmp_path):
    sources = SimpleNamespace(
        client=SimpleNamespace(base_url="http://127.0.0.1:18089", capture_bounds=[{
            "chart_id": "42", "executed_context_sha256": "b" * 64,
            "request_started_at": "2026-10-16T00:00:00+00:00",
            "response_received_at": "2026-10-16T00:00:01+00:00", "force_requested": True,
        }]),
        _query_definition=lambda metadata: metadata,
        _chart_cache={"42": {"returned_rows_sha256": "a" * 64, "metadata": {"id": "42", "params": {}},
                             "envelopes": [{"is_cached": None, "cached_dttm": None}]}},
    )
    actor = trial.Analyst(sources, tmp_path / "publication.json", trial.Audit())
    actor.reads = [{"tool": "profile_saved_chart", "arguments": {"id": "42"}, "result": {"chart_id": "42"}}]
    return actor


def findings():
    return {"title": "Novel source semantics", "findings": [{
        "statement": "A possible operational explanation, not a measured cause.",
        "values": {"claim_kind": "hypothesis", "niche_field": {"value": -0.023, "unit": "fraction"}},
        "source_chart_ids": ["42"],
    }]}


def test_publisher_preserves_agent_values_capture_bound_and_unknown_input_age(tmp_path):
    actor = analyst(tmp_path)
    payload = findings()
    actor.publish(payload)
    actual = json.loads(actor.path.read_text())
    assert actual["evidence"][0]["values"] == payload["findings"][0]["values"]
    assert actual["source_captured_at"] is None
    assert actual["metadata"]["capture_status"] == "unknown"
    assert actual["metadata"]["provider_cache"]["42"] == [{"is_cached": None, "cached_dttm": None}]
    assert actual["metadata"]["input_rows"]["42"] == "a" * 64
    assert actual["evidence"][0]["source_url"].endswith("slice_id=42")
    provenance = actual["evidence"][1]["values"]
    assert provenance["warehouse_freshness"] == "unknown"
    assert provenance["query_capture_bounds"][0]["executed_context_sha256"] == "b" * 64
    assert actor.submission == actual and actor.path.stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="Publish once"):
        actor.publish(payload)


def test_only_confirmed_uncached_inputs_establish_a_lower_capture_bound(tmp_path):
    actor = analyst(tmp_path)
    actor.sources._chart_cache["42"]["envelopes"][0]["is_cached"] = False
    actor.publish(findings())
    assert actor.submission["source_captured_at"] == "2026-10-16T00:00:00+00:00"
    assert actor.submission["metadata"]["capture_status"] == "known_uncached_lower_bound"


@pytest.mark.parametrize("cache", [True, None, "false", 0])
def test_cached_unknown_and_malformed_flags_cannot_become_fresh(tmp_path, cache):
    actor = analyst(tmp_path)
    actor.sources._chart_cache["42"]["envelopes"][0]["is_cached"] = cache
    actor.publish(findings())
    assert actor.submission["source_captured_at"] is None


def test_publisher_rejects_unread_chart_and_unbounded_payload(tmp_path):
    actor = analyst(tmp_path)
    payload = findings()
    payload["findings"][0]["source_chart_ids"] = ["999"]
    with pytest.raises(ValueError, match="actually read"):
        actor.publish(payload)
    payload = findings()
    payload["findings"][0]["values"]["large"] = "x" * 41000
    with pytest.raises(ValueError, match="40k"):
        actor.publish(payload)
    assert not actor.path.exists() and actor.submission is None


def test_admission_is_exclusive_even_if_manifest_reopened(tmp_path, monkeypatch):
    manifest, admission = tmp_path / "protocol.json", tmp_path / "claimed"
    protocol = {"protocol": trial.PROTOCOL, "execution_status": "planned"}
    trial.write_private(manifest, protocol)
    monkeypatch.setattr(trial, "MANIFEST", manifest)
    monkeypatch.setattr(trial, "ADMISSION", admission)
    trial.admit(protocol)
    assert json.loads(manifest.read_text())["execution_status"] == "closed"
    trial.write_private(manifest, protocol)
    with pytest.raises(FileExistsError):
        trial.admit(protocol)


def test_protocol_does_not_claim_a_benchmark_or_a_freshness_sla():
    protocol = json.loads(trial.MANIFEST.read_text())
    assert protocol["limits"]["frontier_invocations"] == 2
    assert protocol["limits"]["jev_attempts"] == 1
    assert protocol["limits"]["automatic_retries"] == 0
    assert "no paired baseline" in protocol["scope"]
    assert "no card freshness SLA" in protocol["freshness"]


async def test_fresh_query_records_actual_executed_context_without_mutating_chart(monkeypatch):
    calls = []

    async def request(self, method, path, **kwargs):
        calls.append((method, path, deepcopy(kwargs)))
        return SimpleNamespace(json=lambda: {"result": [{"data": [{"n": 1}], "is_cached": None}]})

    monkeypatch.setattr(trial.SupersetClient, "_request", request)
    chart = {"id": "42", "datasource_id": 17, "datasource_type": "table",
             "params": {"viz_type": "table", "all_columns": ["n"], "row_limit": 100}}
    before = deepcopy(chart)
    client = trial.FreshSavedClient("http://127.0.0.1:18089")
    await client.chart_data(chart)
    assert chart == before and len(calls) == 1
    assert calls[0][2]["json"]["force"] is True
    bound = client.capture_bounds[0]
    assert bound["definition_mode"] == "production_saved_params_reconstruction"
    assert bound["chart_id"] == "42"
    assert bound["executed_context_sha256"] == hashlib.sha256(json.dumps(calls[0][2]["json"], sort_keys=True).encode()).hexdigest()
    assert client.pending_query is None


@pytest.mark.parametrize("usage", [None, {}, {"input_tokens": -1, "output_tokens": 1},
                                   {"input_tokens": True, "output_tokens": 1}])
async def test_unknown_policy_usage_prevents_actual_writer_operation(usage):
    audit = trial.Audit(events=[{"kind": "api.response", "provider": "jev", "usage": usage}])
    launched = []

    async def writer():
        launched.append(True)

    with pytest.raises(ValueError, match="do not launch"):
        await trial.writer_with_known_policy(audit, trial.RequestBudget(1, used=1), writer)
    assert not launched


async def test_known_policy_usage_allows_one_writer_operation():
    audit = trial.Audit(events=[{"kind": "api.response", "provider": "jev",
                                "usage": {"input_tokens": 20, "output_tokens": 2}}])
    launched = []

    async def writer():
        launched.append(True)

    await trial.writer_with_known_policy(audit, trial.RequestBudget(1, used=1), writer)
    assert launched == [True]


def test_unmatched_actor_drops_stale_known_status_and_preserves_observed_subtotal():
    events = [{"kind": "api.request", "provider": "openai", "request_id": -1},
              {"kind": "api.response", "provider": "openai", "request_id": -1,
               "usage": {"input_tokens": 50, "output_tokens": 5, "input_tokens_details": {"cached_tokens": 10}}},
              {"kind": "api.request", "provider": "openai", "request_id": -2}]
    result = trial.usage_snapshot(events, 2)
    assert result["known"] is False and result["usage"] is None
    assert result["observed"]["input_tokens"] == 50
