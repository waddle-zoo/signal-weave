from semantic_monitor.demo import load_demo_cases


def test_demo_cases_are_external_labeled_inputs():
    cases = load_demo_cases()

    assert {case.id for case in cases} == {
        "data_freshness",
        "mobile_conversion",
        "revenue_decline",
        "seasonal_normal",
    }
    assert all(case.monitor_card.chart_ids for case in cases)
    assert all(case.expected_outcome for case in cases)
