"""Reporter-only fixture integrity, not native adapter or decision efficacy."""

import json

from evaluations.fact_handoff_cases import cases, public_packets


def test_public_accessor_excludes_rubrics_and_returns_independent_data():
    public = public_packets()
    private = cases()
    assert len(public) == len(private) == 3
    assert len({case["id"] for case in public}) == 3
    assert all(set(case) == {"id", "public_packet"} for case in public)
    assert all("private_rubric" not in json.dumps(case) for case in public)
    assert all(case["private_rubric"]["critical_failures"] for case in private)
    public[0]["public_packet"]["result"]["outcome"] = "invented"
    assert public_packets()[0]["public_packet"]["result"]["outcome"] == "ignore"


def test_packets_declare_synthetic_non_native_scope_and_source_linked_measurements():
    for case in public_packets():
        packet = case["public_packet"]
        assert packet["fixture_metadata"] == {"kind": "synthetic_reporter_input", "native_abi": False}
        assert packet["owner_policy"]["decision_guidance"]
        sources = set(packet["source_refs"])
        assert sources
        assert all(row["source_ref"] in sources for row in packet["result"]["observations"])
        assert all(row["status"] == "unknown" for row in packet["result"]["watch_results"])


def test_partial_rate_and_optional_breakdown_do_not_encode_false_comparisons():
    packets = {item["id"]: item["public_packet"] for item in public_packets()}
    rate = packets["rate-current-known-baseline-denominator-missing"]
    before, after = rate["result"]["observations"]
    assert before["denominator"] is None and before["value"] is None
    assert after["value"] == 0.09
    assert rate["result"]["outcome"] == "insufficient_data"
    additive = packets["additive-total-valid-segments-partial"]
    assert additive["result"]["outcome"] == "notify"
    assert additive["result"]["observations"][-1]["quality"]["coverage"] == "partial"
    assert additive["result"]["analyses"][0]["delta"] == 12
