from __future__ import annotations

import copy
import json
from datetime import date, timedelta

import httpx
import pytest

from evaluations import northstar_policy_contrasts as probe
from signalweave.models import InsightCard, ResourceSnapshot

PROTOCOL = probe.ROOT / "evaluations/protocols/northstar-policy-contrasts.json"


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """Portable source fixtures; no retained workspace or connected BI required."""
    monkeypatch.setattr(probe.httpx.AsyncClient, "post", lambda *a, **kw: pytest.fail("Unexpected network"))
    card = InsightCard(id="local-card", title="Sales check", what_to_watch="All digital sales",
                       why_watch="Apply the owner rule", decision_guidance="Investigate a decline of at least 10%.",
                       watch_for=["Dates represented", "Digital movement", "Company bridge", "Seasonal equivalence"],
                       sources=[{"key": "sales", "adapter": "publication", "resource": "report:sales", "label": "Sales"}],
                       comparison_windows=["rolling seven dates"], action_confidence_threshold=.7)
    snapshot = ResourceSnapshot(source_key="inspection-key", adapter="publication", resource="report:sales",
                                title="Analysis", captured_at="2026-10-18T09:00:00Z",
                                evidence=[{"source_key": "inspection-key", "statement": "Original actual fixture fact.",
                                           "subject_id": "all-digital-net-sales", "values": {"change_pct": "14.57", "unit": "source units; currency not declared"}, "provenance": ["original-query"]}])
    rows = [{"period": p, "order_date": (start+timedelta(days=i)).isoformat(), "channel": c,
             "net_sales": 100+i, "orders": 1, "digital_flag": int(c != "Store")}
            for p, start in [("current_2026", date(2026, 9, 6)), ("prior_2025", date(2025, 9, 7))]
            for i in range(7) for c in ["Online", "Mobile", "Marketplace", "Store"]]
    report = tmp_path/"report.json"
    report.write_text(json.dumps({"card_after": card.model_dump(mode="json"),
                                 "native_calls": [{"name": "inspect_resource", "result": snapshot.model_dump(mode="json") }]}))
    trace = tmp_path/"trace.jsonl"
    trace.write_text(json.dumps({"kind": "tool.result", "name": "company_superset_sqllab_execute",
                                "result": {"result": json.dumps({"data": rows})}})+"\n")
    spec = probe.read(PROTOCOL)
    spec["sources"] = {day: {"report": str(report), "trace": str(trace)} for day in ["05", "12"]}
    protocol = tmp_path/"protocol.json"
    protocol.write_text(json.dumps(spec))
    return protocol, snapshot.model_dump(mode="json"), rows


@pytest.mark.asyncio
async def test_preparation_captures_exact_sdk_requests_without_answers_or_source_mutation(corpus, tmp_path):
    protocol, snapshot, rows = corpus
    before = copy.deepcopy((snapshot, rows))
    output = tmp_path/"prepared"
    assert await probe.prepare(protocol, output) == {"prepared": 16, "provider_calls": 0, "certification": False}
    manifest = probe.read(output/"prepared.json")
    assert (snapshot, rows) == before
    assert manifest["originals"]["12"]["inspection"] == snapshot
    assert manifest["originals"]["12"]["queries"][0]["data"] == rows
    grouped = {}
    for record in manifest["records"]:
        wire = json.loads(record["wire"])
        assert probe.digest(record["wire"].encode()) == record["wire_sha256"]
        assert wire["model"] == probe.MODEL
        assert set(wire["questions"]) == {"outcome", "watch_0", "watch_1", "watch_2", "watch_3"}
        assert "allowed_raw_outcomes" not in record["wire"]
        assert "ordered_proposed_outcome" not in record["wire"]
        assert record["case"]["id"] not in json.dumps(wire["state"]["evidence"])
        assert wire["state"]["card"]["action_confidence_threshold"] == .7
        assert wire["state"]["card"]["delivery_methods"] == []
        grouped.setdefault(record["case"]["id"], {})[record["policy"]] = record
    for pair in grouped.values():
        original, ordered = pair["original"], pair["ordered"]
        assert original["snapshot"] == ordered["snapshot"]
        a, b = copy.deepcopy(original["card"]), copy.deepcopy(ordered["card"])
        a.pop("decision_guidance")
        b.pop("decision_guidance")
        assert a == b
        assert original["card"]["watch_for"] == ordered["card"]["watch_for"]
    with pytest.raises(ValueError, match="New output"):
        await probe.prepare(protocol, output)


def test_row_controls_derive_boundaries_distinct_dates_and_conflicts(corpus):
    protocol, snapshot, rows = corpus
    before = copy.deepcopy((snapshot, rows))
    for spec in probe.read(protocol)["cases"]:
        if spec["actual"]:
            continue
        fixture, changed = probe.synthetic(snapshot, rows, spec)
        facts = {e["subject_id"]: e["values"] for e in fixture["evidence"]}
        assert all(e["values"]["current_window"] == "2026-09-06 through 2026-09-12" and
                   e["values"]["prior_window"] == "2025-09-07 through 2025-09-13" and
                   e["values"]["unit"] == "source units; currency not declared" for e in fixture["evidence"])
        digital, coverage = facts["all-digital-net-sales"], facts["observed-date-presence"]["scopes"]
        assert fixture["metadata"]["hypothetical"] is True
        assert "publication_sha256" not in json.dumps(fixture)
        assert "original-query" not in json.dumps(fixture["evidence"])
        assert all(e["provenance"] == ["hypothetical:date-channel-row-transformation"] for e in fixture["evidence"])
        if spec["id"] == "complete_minus_9_99":
            assert digital["change_pct"] == "-9.9900"
        elif spec["id"] == "complete_exact_minus_10":
            assert digital["change_pct"] == "-10.0"
        elif spec["id"] == "aggregate_decline_company_offset":
            assert digital["change_pct"] == "-15.00"
            assert float(facts["company-net-sales-bridge"]["delta"]) > 0
        elif spec.get("missing_current"):
            assert coverage["all_digital"][0]["dates_present"] == 6
            assert coverage["all_digital"][0]["missing_dates"] == ["2026-09-06"]
            assert digital["change_pct"] is None
        elif spec.get("duplicate_prior"):
            assert coverage["Mobile"][1]["channel_row_counts"]["Mobile"] == 7
            assert coverage["Mobile"][1]["dates_present"] == 6
            assert digital["comparison_available"] is False
            assert len(changed) == len(rows)
        elif spec.get("scope_conflict"):
            conflict = facts["scope-reconciliation"]
            assert conflict["listed_channel_sum"] != conflict["published_digital_total"]
            assert fixture["contract"]["source_status"] == "ambiguous"
        if "business_control" in spec:
            assert set(spec["allowed_raw_outcomes"]) == {"investigate", "insufficient_data"}
            assert spec["ordered_proposed_outcome"] == "insufficient_data"
    assert (snapshot, rows) == before
    with pytest.raises(ValueError, match="Fixture ambiguity"):
        probe.synthetic(snapshot, rows[:-1], {"current_digital_daily": "8500"})


def response_for(wire, *, choice="ignore", support=.9, inputs=10, outputs=2, model=probe.MODEL):
    questions = json.loads(wire)["questions"]
    answers = {}
    for name, q in questions.items():
        selected = choice if name == "outcome" else "unknown"
        probability = support if name == "outcome" else .9
        answers[name] = {"type": "choice", "choice": selected,
                         "probabilities": {k: probability if k == selected else (1-probability)/(len(q["criteria"])-1)
                                           for k in q["criteria"]}, "confidence": .5}
    return {"model": model, "answers": answers, "usage": {"input_tokens": inputs, "output_tokens": outputs}}


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["complete", "http_error", "input", "output", "model", "unknown_usage"])
async def test_runner_production_projection_caps_usage_and_never_retries(corpus, tmp_path, monkeypatch, stop):
    output = tmp_path/"prepared"
    await probe.prepare(corpus[0], output)
    sent = []

    async def post(self, url, *, content, headers):
        assert headers["Content-Type"] == "application/json"
        assert len(list(output.glob("attempt-*.json"))) == len(sent)+1
        sent.append(content)
        payload = response_for(content, support=.6,
                               inputs=120_000 if stop == "input" else 10,
                               outputs=4_000 if stop == "output" else 2,
                               model="different" if stop == "model" else probe.MODEL)
        if stop == "unknown_usage":
            payload.pop("usage")
        return httpx.Response(503 if stop == "http_error" else 200,
                              request=httpx.Request("POST", url), json=payload)

    monkeypatch.setattr(probe.httpx.AsyncClient, "post", post)
    key = tmp_path/"key"
    key.write_text("offline-test-only")
    result = await probe.run(output, key)
    assert result["attempts"] == len(sent) == (16 if stop == "complete" else 1)
    saved = probe.read(output/"results.json")
    first = saved["results"][0]
    if stop in {"complete", "input", "output"}:
        assert first["raw_choice"]["choice"] == "ignore"
        assert first["routed"]["outcome"] != "ignore"  # Actual .7 code gate, not a fake projection.
        assert first["routed"]["workflow"] is not None
        assert first["routed"]["probabilities"] == first["raw_choice"]["probabilities"]
    else:
        assert "error" in first
    if stop in {"input", "output", "model"}:
        assert saved["input_tokens"] == (120_000 if stop == "input" else 10)
    assert "offline-test-only" not in (output/"results.json").read_text()
    with pytest.raises(FileExistsError):
        await probe.run(output, key)
    assert len(sent) == result["attempts"]


@pytest.mark.asyncio
async def test_changed_input_or_wire_is_rejected_before_dispatch(corpus, tmp_path):
    output = tmp_path/"prepared"
    await probe.prepare(corpus[0], output)
    path = output/"prepared.json"
    saved = probe.read(path)
    saved["records"][0]["wire"] += " "
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="wire changed"):
        await probe.run(output, tmp_path/"no-key")
    assert not (output/"run.claimed").exists()
    saved["records"][0]["wire"] = saved["records"][0]["wire"].rstrip()
    path.write_text(json.dumps(saved))
    corpus[0].write_text("{}")
    with pytest.raises(ValueError, match="input changed"):
        await probe.run(output, tmp_path/"no-key")
