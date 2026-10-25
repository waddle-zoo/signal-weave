from __future__ import annotations

from evaluations.everything_tracking_card_clarity_trial import clarify_card
from evaluations.everything_tracking_trial import DEFAULT_CONFIG, build_cases, load_config


def test_card_clarity_trial_adds_human_policy_without_changing_sources():
    case = next(
        item
        for item in build_cases(load_config(DEFAULT_CONFIG))
        if item.variant == "expected_change"
    )

    clarified = clarify_card(case.card, case.variant)

    assert clarified.sources == case.card.sources
    assert any("do not notify or escalate" in item for item in clarified.watch_for)
    assert any("return ignore" in item for item in clarified.questions)


def test_card_clarity_trial_adds_investigate_boundary_for_ambiguous_state():
    case = next(
        item
        for item in build_cases(load_config(DEFAULT_CONFIG))
        if item.variant == "ambiguous_state"
    )

    clarified = clarify_card(case.card, case.variant)

    assert clarified.sources == case.card.sources
    assert any("return investigate" in item for item in clarified.watch_for)
    assert any("not" in item and "corroborated" in item for item in clarified.questions)
