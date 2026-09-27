from __future__ import annotations

from copy import deepcopy

from evaluations.preset_live_onboarding_review import _digest, review_report


def _passing_report() -> dict:
    card = {"id": "card-1", "version": 3}
    report = {
        "trial": "preset-live-onboarding-shadow",
        "adapter": "preset__customer-workspace",
        "tenant_id": "northstar",
        "request": {
            "goal": "Monitor growth",
            "why": "Support the growth team",
            "destination": "slack://growth",
            "limit": 10,
        },
        "approval_requested": True,
        "passed": True,
        "not_proven": [
            "business usefulness or correctness without operator labels",
            "provider permission coverage beyond the sources selected by this card",
            "production delivery reliability or autonomous side effects",
            "managed SignalWeave hosting",
        ],
        "onboarding": {"status": "ready_for_approval", "card": card},
        "approval": {"status": "approved"},
        "evaluation": {
            "result": {
                "evaluator": "jev-latest",
                "evidence": [{"subject_id": "dashboard:1"}],
                "observations": [{"subject_id": "dashboard:1"}],
            },
            "receipt": {
                "receipt_id": "receipt-1",
                "idempotency_key": "shadow-1",
                "card_id": "card-1",
                "card_version": 3,
                "status": "delivery_disabled",
                "delivery_enabled": False,
            },
            "resources": [
                {
                    "adapter": "preset__customer-workspace",
                    "resource": "dashboard:1",
                    "contract": {"tenant_id": "northstar"},
                    "metadata": {
                        "dashboard_scope": {
                            "dashboard_scoped_requests": 1,
                            "chart_query_fallbacks": 0,
                        }
                    },
                }
            ],
        },
        "summary": {
            "evaluator": "jev-latest",
            "evidence_count": 1,
            "observation_count": 1,
            "receipt_id": "receipt-1",
            "receipt_status": "delivery_disabled",
            "delivery_enabled": False,
        },
        "replay": {
            "replayed": True,
            "receipt": {"status": "replayed"},
        },
        "receipt_lookup": {
            "status": "found",
            "receipt": {
                "receipt_id": "receipt-1",
                "idempotency_key": "shadow-1",
                "card_id": "card-1",
                "card_version": 3,
            },
        },
        "provider_checks": {
            "onboarding_contract": {
                "approval_required": True,
                "delivery_disabled": True,
            },
            "provider_transport_used": True,
            "provider_workspace_origin": "https://workspace.preset.test",
            "provider_auth_origin": "https://api.preset.test",
            "provider_credentials_loaded": True,
            "provider_secrets_absent_from_artifacts": True,
            "provider_requests_for_onboarding": 1,
            "provider_request_paths_before_onboarding": {},
            "provider_request_paths_after_onboarding": {"/api/v1/dashboard/": 1},
            "provider_request_paths_for_onboarding": {"/api/v1/dashboard/": 1},
            "provider_catalog_searches_for_onboarding": 1,
            "provider_request_paths_before_approval": {"/api/v1/dashboard/": 1},
            "provider_request_paths_after_approval": {
                "/api/v1/dashboard/": 1,
                "/api/v1/chart/1": 1,
            },
            "provider_request_paths_for_approval": {"/api/v1/chart/1": 1},
            "provider_requests_for_approval": 1,
            "provider_request_paths_before_first_evaluation": {"/api/v1/dashboard/": 1},
            "provider_request_paths_after_first_evaluation": {
                "/api/v1/dashboard/": 1,
                "/api/v1/chart/1/data": 1,
            },
            "provider_request_paths_for_first_evaluation": {"/api/v1/chart/1/data": 1},
            "provider_requests_for_first_evaluation": 1,
            "provider_data_requests_for_first_evaluation": 1,
            "replay_made_no_jev_call": True,
            "replay_made_no_provider_call": True,
            "jev_requests_for_first_evaluation": 1,
            "jev_requests_for_approval": 1,
            "all_resources_use_requested_preset_adapter": True,
            "all_resources_match_runtime_tenant": True,
            "data_policy": {
                "mode": "cached_results",
                "allow_live_queries": False,
                "allow_refresh": False,
                "max_result_rows": 500,
                "max_snapshot_bytes": 1_000_000,
            },
            "provider_force_refresh": False,
        },
    }
    report["approval_basis"] = {
        "review_report": "draft.json",
        "card_id": card["id"],
        "card_version": card["version"],
        "reviewed_card_digest": _digest(card),
        "stored_card_digest": _digest(card),
        "exact_draft_reused": True,
        "reviewed_data_policy": report["provider_checks"]["data_policy"],
        "reviewed_provider_force_refresh": False,
        "reviewed_provider_workspace_origin": "https://workspace.preset.test",
        "reviewed_provider_auth_origin": "https://api.preset.test",
        "current_provider_workspace_origin": "https://workspace.preset.test",
        "current_provider_auth_origin": "https://api.preset.test",
        "provider_workspace_unchanged": True,
        "provider_auth_origin_unchanged": True,
        "current_data_policy_digest": _digest(report["provider_checks"]["data_policy"]),
        "reviewed_data_policy_digest": _digest(report["provider_checks"]["data_policy"]),
        "data_policy_unchanged": True,
    }
    return report


def test_independent_reviewer_accepts_complete_live_shadow_report():
    review = review_report(_passing_report())

    assert review["passed"] is True
    assert review["findings"] == []


def test_independent_reviewer_rejects_delivery_or_tenant_mutation():
    report = _passing_report()
    report["evaluation"]["receipt"]["delivery_enabled"] = True
    report["evaluation"]["resources"][0]["contract"]["tenant_id"] = "foreign"

    review = review_report(report)

    assert review["passed"] is False
    assert any("enabled delivery" in finding for finding in review["findings"])
    assert any("not bound to the runtime tenant" in finding for finding in review["findings"])


def test_independent_reviewer_rejects_overclaim_and_missing_jev_request():
    report = deepcopy(_passing_report())
    report["not_proven"] = []
    report["provider_checks"]["jev_requests_for_first_evaluation"] = 0

    review = review_report(report)

    assert review["passed"] is False
    assert any("non-claims" in finding for finding in review["findings"])
    assert any("no recorded Jev request" in finding for finding in review["findings"])


def test_independent_reviewer_rejects_missing_preset_transport_proof():
    report = deepcopy(_passing_report())
    report["provider_checks"].pop("provider_transport_used")
    report["provider_checks"].pop("provider_requests_for_onboarding")

    review = review_report(report)

    assert review["passed"] is False
    assert any("Preset provider request" in finding for finding in review["findings"])


def test_independent_reviewer_rejects_missing_approval_revalidation_proof():
    report = deepcopy(_passing_report())
    report["provider_checks"].pop("provider_requests_for_approval")
    report["provider_checks"].pop("jev_requests_for_approval")

    review = review_report(report)

    assert review["passed"] is False
    assert any("approval did not record a Preset" in finding for finding in review["findings"])
    assert any("approval did not record a Jev-backed" in finding for finding in review["findings"])


def test_independent_reviewer_rejects_missing_credential_artifact_proof():
    report = deepcopy(_passing_report())
    report["provider_checks"]["provider_secrets_absent_from_artifacts"] = False

    review = review_report(report)

    assert review["passed"] is False
    assert any("provider secrets stayed out" in finding for finding in review["findings"])


def test_independent_reviewer_rejects_live_refresh_without_policy_proof():
    report = deepcopy(_passing_report())
    report["provider_checks"]["provider_force_refresh"] = True

    review = review_report(report)

    assert review["passed"] is False
    assert any("force=false" in finding for finding in review["findings"])


def test_independent_reviewer_rejects_mutated_policy_approval_basis():
    report = deepcopy(_passing_report())
    report["approval_basis"]["data_policy_unchanged"] = False

    review = review_report(report)

    assert review["passed"] is False
    assert any("unchanged" in finding for finding in review["findings"])


def test_independent_reviewer_rejects_mutated_workspace_approval_basis():
    report = deepcopy(_passing_report())
    report["approval_basis"]["provider_workspace_unchanged"] = False

    review = review_report(report)

    assert review["passed"] is False
    assert any("workspace was unchanged" in finding for finding in review["findings"])


def test_independent_reviewer_rejects_mutated_auth_origin_approval_basis():
    report = deepcopy(_passing_report())
    report["approval_basis"]["provider_auth_origin_unchanged"] = False

    review = review_report(report)

    assert review["passed"] is False
    assert any("auth origin was unchanged" in finding for finding in review["findings"])


def test_independent_reviewer_rejects_unsafe_cached_policy_permissions():
    report = deepcopy(_passing_report())
    report["provider_checks"]["data_policy"]["allow_refresh"] = True

    review = review_report(report)

    assert review["passed"] is False
    assert any("live execution permissions" in finding for finding in review["findings"])


def test_independent_reviewer_rejects_policy_bounds_above_connection_maximum():
    report = deepcopy(_passing_report())
    report["provider_checks"]["data_policy"]["max_result_rows"] = 10_001

    review = review_report(report)

    assert review["passed"] is False
    assert any("max_result_rows" in finding for finding in review["findings"])


def test_independent_reviewer_rejects_unbounded_catalog_search_fanout():
    report = deepcopy(_passing_report())
    report["provider_checks"]["provider_catalog_searches_for_onboarding"] = 22

    review = review_report(report)

    assert review["passed"] is False
    assert any("catalog search fan-out" in finding for finding in review["findings"])


def test_independent_reviewer_rejects_inconsistent_receipt_artifacts():
    report = deepcopy(_passing_report())
    report["onboarding"]["status"] = "needs_human_review"
    report["replay"]["receipt"]["status"] = "delivery_disabled"
    report["receipt_lookup"]["receipt"]["card_version"] = 99

    review = review_report(report)

    assert review["passed"] is False
    assert any("onboarding readiness" in finding for finding in review["findings"])
    assert any("replayed receipt" in finding for finding in review["findings"])
    assert any("card_version" in finding for finding in review["findings"])


def test_independent_reviewer_rejects_catalog_only_shadow():
    report = deepcopy(_passing_report())
    report["provider_checks"]["provider_request_paths_after_first_evaluation"] = {
        "/api/v1/dashboard/": 1
    }
    report["provider_checks"]["provider_request_paths_for_first_evaluation"] = {}
    report["provider_checks"]["provider_requests_for_first_evaluation"] = 0
    report["provider_checks"]["provider_data_requests_for_first_evaluation"] = 0

    review = review_report(report)

    assert review["passed"] is False
    assert any("chart data" in finding for finding in review["findings"])


def test_independent_reviewer_rejects_dashboard_scope_fallback_or_missing_telemetry():
    report = deepcopy(_passing_report())
    report["evaluation"]["resources"][0]["metadata"]["dashboard_scope"] = {
        "dashboard_scoped_requests": 0,
        "chart_query_fallbacks": 1,
    }

    review = review_report(report)

    assert review["passed"] is False
    assert any("no dashboard-scoped Preset request" in finding for finding in review["findings"])
    assert any("chart-query fallback" in finding for finding in review["findings"])

    report = deepcopy(_passing_report())
    report["evaluation"]["resources"][0]["metadata"] = {}
    review = review_report(report)

    assert review["passed"] is False
    assert any("missing dashboard-scope telemetry" in finding for finding in review["findings"])


def test_independent_reviewer_accepts_unapproved_draft_without_claiming_acceptance():
    report = deepcopy(_passing_report())
    for key in ("approval", "evaluation", "summary", "replay", "receipt_lookup", "approval_basis"):
        report.pop(key, None)
    report["approval_requested"] = False
    report["passed"] = False
    report["onboarding"] = {
        "status": "needs_human_review",
        "approval_required": True,
        "delivery_enabled": False,
        "card": {"id": "card-1", "version": 3},
    }
    report["next_action"] = "review the draft before approval"
    report["provider_checks"].pop("onboarding_contract", None)

    review = review_report(report)

    assert review["passed"] is True


def test_independent_reviewer_rejects_incomplete_unapproved_draft():
    report = {
        "trial": "preset-live-onboarding-shadow",
        "adapter": "preset__customer-workspace",
        "tenant_id": "northstar",
        "approval_requested": False,
        "passed": False,
        "onboarding": {"status": "needs_human_review"},
        "next_action": "review the draft before approval",
    }

    review = review_report(report)

    assert review["passed"] is False
    assert any("persisted card draft" in finding for finding in review["findings"])
    assert any("provider checks" in finding for finding in review["findings"])
