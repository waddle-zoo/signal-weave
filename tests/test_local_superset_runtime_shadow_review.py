from evaluations.local_superset_runtime_shadow_review import review


def _report() -> dict:
    return {
        "trial": "local-superset-runtime-shadow",
        "real_local_superset_transport": True,
        "synthetic_typesafe_transport": True,
        "live_jev_semantics_proven": False,
        "managed_hosting_proven": False,
        "discovery": {
            "match_count": 1,
            "selected_ref": "superset|dashboard:1",
        },
        "onboarding": {
            "status": "ready_for_approval",
            "review_status": "ready_for_approval",
        },
        "approval": {"status": "approved"},
        "evaluation": {
            "evaluator": "jev-latest",
            "chart_summary": {"charts": 2},
            "observation_count": 4,
            "evidence_count": 3,
            "jev_calls_for_evaluation": 1,
        },
        "receipt": {
            "status": "delivery_disabled",
            "delivery_enabled": False,
            "replayed": True,
        },
        "provider": {
            "requests_for_evaluation": 2,
            "requests_for_replay": 0,
            "request_path_counts": {"/api/v1/chart/1/data/": 1},
            "dashboard_scope": {
                "dashboard_scoped_requests": 1,
                "chart_query_fallbacks": 0,
            },
            "dashboard_scope_warning": None,
        },
        "checks": {"tenant_bound_runtime": True},
        "passed": True,
        "not_proven": [
            "live Jev semantic accuracy or business usefulness",
            "managed SignalWeave hosting",
        ],
    }


def test_independent_review_accepts_complete_report():
    result = review(_report())

    assert result["passed"] is True
    assert result["failures"] == []


def test_independent_review_rejects_providerless_pass_looking_report():
    report = _report()
    report["provider"]["requests_for_evaluation"] = 0
    report["passed"] = True

    result = review(report)

    assert result["passed"] is False
    assert "evaluation did not cross the provider" in result["failures"]


def test_independent_review_rejects_undisclosed_scope_fallback():
    report = _report()
    report["provider"]["dashboard_scope"] = {
        "dashboard_scoped_requests": 0,
        "chart_query_fallbacks": 1,
    }
    report["provider"]["dashboard_scope_warning"] = None

    result = review(report)

    assert result["passed"] is False
    assert "unscoped chart-query fallback was not disclosed" in result["failures"]
