from evaluations.cases import load_evaluation_cases


def test_demo_cases_are_external_labeled_inputs():
    cases = load_evaluation_cases()

    assert {case.id for case in cases} == {
        "data_freshness",
        "mobile_conversion",
        "revenue_decline",
        "seasonal_normal",
    }
    assert all(case.card.sources for case in cases)
    assert all(case.card.what_to_watch and case.card.why_watch for case in cases)
    assert all(case.card.questions or case.card.watch_for for case in cases)
    assert all(case.expected_outcome for case in cases)
