from semantic_monitor.proof import run_fixture_proof


async def test_fixture_proof_matches_expected_outcomes():
    results = await run_fixture_proof("heuristic")

    assert len(results) == 4
    assert all(result.passed for result in results)
    revenue = next(result for result in results if result.scenario == "revenue_decline")
    assert revenue.recipient == "revenue-operations"
    assert revenue.evidence
