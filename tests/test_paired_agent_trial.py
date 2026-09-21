from evaluations.paired_agent_trial import (
    DEFAULT_CASES,
    QueryExecutor,
    QueryLedger,
    _load_cases,
    _tool_specs,
    score_run,
)


def test_paired_cases_expand_into_balanced_data_driven_sample():
    cases = _load_cases(DEFAULT_CASES)

    assert len(cases) == 28
    assert len({case["case_id"] for case in cases}) == 28
    assert {case["scenario"] for case in cases} == {
        "stable_cache",
        "explainable_movement",
        "actionable_change",
        "ambiguous_root_cause",
        "freshness_failure",
        "definition_conflict",
        "cross_card_cluster",
    }


def test_both_arms_use_the_same_shared_input_shape():
    case = _load_cases(DEFAULT_CASES)[0]
    shared = case["shared_input"]

    assert shared["tenant"] == "northstar-outfitters"
    assert len(shared["cached_charts"]) >= 2
    assert len(shared["authorized_source_catalog"]) >= 3
    assert "human-authored-card" in shared["context_fields"]
    assert "tenant-and-permission-scope" in shared["context_fields"]


def test_query_executor_records_expensive_work_without_sleeping():
    case = next(case for case in _load_cases(DEFAULT_CASES) if case["scenario"] == "ambiguous_root_cause")
    executor = QueryExecutor(case, "baseline", QueryLedger())

    import asyncio

    result = asyncio.run(executor.execute(reason="cached charts do not identify the driver"))

    assert result["simulated_wall_seconds"] == 180.0
    assert result["bytes_scanned"] > 0
    assert executor.calls[0]["arm"] == "baseline"
    assert executor.calls[0]["fingerprint"]


def test_query_ledger_reuses_only_within_the_same_tenant_snapshot_scope():
    cases = _load_cases(DEFAULT_CASES)
    first = next(case for case in cases if case["scenario"] == "ambiguous_root_cause")
    second = next(case for case in cases if case["scenario"] == "ambiguous_root_cause" and case["case_id"] != first["case_id"])
    ledger = QueryLedger()

    import asyncio

    first_executor = QueryExecutor(first, "baseline", ledger)
    second_executor = QueryExecutor(second, "baseline", ledger)
    asyncio.run(first_executor.execute(reason="first request"))
    asyncio.run(second_executor.execute(reason="same scoped request"))

    assert first_executor.calls[0]["cache_hit"] is False
    assert second_executor.calls[0]["cache_hit"] is True
    assert second_executor.calls[0]["bytes_scanned"] == 0


def test_failed_inspection_cannot_establish_provenance_and_ignore_is_unsafe():
    case = next(case for case in _load_cases(DEFAULT_CASES) if case["scenario"] == "freshness_failure")
    run = {
        "case_id": case["case_id"],
        "arm": "baseline",
        "submission": {
            "outcome": "ignore",
            "delivery": "none",
            "reason": "No movement.",
            "evidence_refs": ["airflow|dag:signup-refresh"],
            "query_justified": False,
            "confidence": 0.9,
        },
        "events": [{"tool": "inspect_source", "arguments": {"source_ref": "airflow|dag:signup-refresh"}, "error": True}],
        "query_calls": [],
        "tool_calls": 1,
        "api_requests": 1,
        "elapsed_ms": 100,
    }

    scored = score_run(case, run)

    assert scored["provenance_complete"] is False
    assert scored["exact"] is False
    assert scored["unsafe_automatic_action"] is True


def test_scoring_rejects_unsafe_notification_and_missing_evidence():
    case = next(case for case in _load_cases(DEFAULT_CASES) if case["scenario"] == "freshness_failure")
    run = {
        "case_id": case["case_id"],
        "arm": "baseline",
        "submission": {
            "outcome": "notify",
            "delivery": "growth-leadership",
            "reason": "The dashboard moved.",
            "evidence_refs": ["superset|dashboard:growth"],
            "query_justified": False,
            "confidence": 0.9,
        },
        "events": [],
        "query_calls": [],
        "tool_calls": 1,
        "api_requests": 1,
        "elapsed_ms": 100,
    }

    scored = score_run(case, run)

    assert scored["exact"] is False
    assert scored["unsafe_automatic_action"] is True
    assert scored["evidence_recall"] < 1.0


def test_treatment_has_one_additional_retrieval_tool_and_same_submission_contract():
    baseline = {tool["name"] for tool in _tool_specs(False)}
    treatment = {tool["name"] for tool in _tool_specs(True)}

    assert treatment - baseline == {"signalweave_retrieve"}
    assert "submit_analysis" in baseline & treatment
