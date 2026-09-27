from copy import deepcopy

from evaluations.preset_enterprise_proof_review import review_report


def _passing_report() -> dict:
    cases = []
    for name in (
        "hosted_connector",
        "credential_and_tenant_boundary",
        "generated_generalization",
        "jev_contract",
        "runtime_shadow",
    ):
        cases.append(
            {
                "name": name,
                "producer": {"passed": True},
                "independent_review": {
                    "passed": True,
                    "report": {"passed": True},
                },
            }
        )
    return {
        "trial": "preset-enterprise-proof-pack",
        "proof_scope": {
            "synthetic_preset_transport": True,
            "synthetic_typesafe_transport": True,
            "live_external_provider_requests": 0,
            "live_jev_requests": 0,
            "delivery_enabled": False,
        },
        "cases": cases,
        "passed": True,
        "not_proven": [
            "real Preset plan, credentials, permissions, and rate limits",
            "live Jev semantic accuracy or business usefulness",
            "managed SignalWeave hosting",
        ],
    }


def test_aggregate_reviewer_accepts_complete_proof_pack() -> None:
    review = review_report(_passing_report())

    assert review["passed"] is True
    assert review["findings"] == []


def test_aggregate_reviewer_rejects_live_scope_or_missing_case() -> None:
    report = deepcopy(_passing_report())
    report["proof_scope"]["live_jev_requests"] = 1
    report["cases"].pop()

    review = review_report(report)

    assert review["passed"] is False
    assert any("live Jev" in finding for finding in review["findings"])
    assert any("each required trial" in finding for finding in review["findings"])
