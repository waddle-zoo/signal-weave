from evaluations.cases import load_evaluation_cases


def test_demo_cases_are_external_labeled_inputs():
    cases = load_evaluation_cases()

    assert {case.id for case in cases} == {
        "data_freshness",
        "mobile_conversion",
        "revenue_decline",
        "seasonal_normal",
    }
    assert all(case.workflow.sources for case in cases)
    assert all(case.expected_outcome for case in cases)
