from evaluations.bootstrap_onboarding_review import _card_quality, _notes_quality
from evaluations.bootstrap_scenarios import build_scenarios


def _card(scenario, *, source_variant=False, unknown_route=False):
    public = scenario["public"]
    catalog = [
        item for item in public["catalog"]
        if bool((item.get("metadata") or {}).get("scope")) == source_variant
    ]
    source = catalog[0]
    methods = []
    outcomes = {
        label["outcome"]
        for label in scenario["private"]["periods"].values()
        if label["outcome"] != "ignore"
    }
    for index, outcome in enumerate(sorted(outcomes)):
        destination = public["destinations"][index % len(public["destinations"])]
        methods.append({
            # Keys are card-local and may be human-friendly. The destination
            # is what must match the authorized route.
            "key": "business-route" if index == 0 else destination["key"],
            "outcome": outcome,
            "destination": "unknown-destination" if unknown_route and index == 0 else destination["key"],
        })
    return {
        "id": "card-test",
        "status": "approved",
        "what_to_watch": public["brief"],
        "why_watch": "Support a business decision.",
        "decision_guidance": public["owner_answers"]["materiality"],
        "sources": [{"adapter": source["adapter"], "resource": source["resource"]}],
        "numeric_conditions": [{"threshold": -10}],
        "delivery_methods": methods,
    }


def test_onboarding_card_audit_requires_authorized_non_noise_sources_and_routes():
    scenario = build_scenarios(seed=20261001, split="holdout", connector_profile=True, catalog_noise=2)[0]
    assert _card_quality(_card(scenario), scenario)["mechanical_pass"]
    assert _card_quality(_card(scenario, source_variant=True), scenario)["checks"]["sources_avoid_catalog_noise"] is False
    assert _card_quality(_card(scenario, unknown_route=True), scenario)["checks"]["routes_authorized"] is False


def test_onboarding_card_audit_accepts_configured_destination_uri_with_local_key():
    scenario = build_scenarios(seed=20261001, split="holdout", connector_profile=True)[0]
    card = _card(scenario)
    for method, destination in zip(
        card["delivery_methods"], scenario["public"]["destinations"], strict=False
    ):
        method["key"] = f"owner-route-{method['outcome']}"
        method["destination"] = destination["destination"]
    result = _card_quality(card, scenario)
    assert result["checks"]["routes_authorized"]
    assert result["mechanical_pass"]


def test_notes_audit_is_not_mistaken_for_an_executable_card():
    scenario = build_scenarios(seed=20261001, split="holdout")[0]
    row = {
        "status": "complete",
        "asked_owner_topics": scenario["public"]["owner_topics"],
        "notes": " ".join([
            scenario["public"]["owner_answers"]["materiality"],
            *(item["key"] for item in scenario["public"]["destinations"]),
        ]),
    }
    result = _notes_quality(row, scenario)
    assert result["mechanical_pass"]
    assert result["executable_artifact"] is False
