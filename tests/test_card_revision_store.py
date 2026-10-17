import pytest

from signalweave.models import InsightCard, OnboardingCorrection, OnboardingCorrectionKind
from signalweave.store import JsonInsightCardStore, SQLiteInsightCardStore


def make_card(card_id: str = "card-1", *, version: int = 1) -> InsightCard:
    return InsightCard(
        id=card_id,
        title="Sales pulse",
        what_to_watch="Sales movement.",
        why_watch="Decide whether the team should act.",
        decision_guidance="Investigate an unexpected movement.",
        version=version,
    )


@pytest.fixture(params=[JsonInsightCardStore, SQLiteInsightCardStore], ids=["json", "sqlite"])
def store_setup(request, tmp_path):
    store_type = request.param
    filename = "cards.json" if store_type is JsonInsightCardStore else "cards.db"
    path = tmp_path / filename
    return store_type, path, store_type(path)


def test_expected_card_cas_updates_and_survives_store_restart(store_setup):
    store_type, path, store = store_setup
    original = make_card()
    store.save_card(original)
    updated = original.model_copy(update={"version": 2, "title": "Revised sales pulse"})

    reopened = store_type(path)
    assert reopened.save_card_if_version(
        updated, expected_version=1, expected_card=original
    ) is None

    restarted = store_type(path)
    assert restarted.get_card(original.id) == updated


def test_expected_card_cas_rejects_stale_version_without_overwrite(store_setup):
    _, _, store = store_setup
    original = make_card()
    store.save_card(original)
    winner = original.model_copy(update={"version": 2, "title": "Winner"})
    store.save_card_if_version(winner, expected_version=1, expected_card=original)
    stale = original.model_copy(update={"version": 2, "title": "Stale overwrite"})

    with pytest.raises(ValueError, match="version conflict"):
        store.save_card_if_version(stale, expected_version=1, expected_card=original)

    assert store.get_card(original.id) == winner


def test_expected_card_cas_rejects_same_version_policy_change_without_overwrite(store_setup):
    _, _, store = store_setup
    original = make_card()
    store.save_card(original)
    policy_revision = original.model_copy(
        update={"decision_guidance": "Escalate an unexpected movement."}
    )
    store.save_card(policy_revision)
    owner_revision = original.model_copy(update={"version": 2, "title": "Owner revision"})

    with pytest.raises(ValueError, match="changed since expected snapshot"):
        store.save_card_if_version(owner_revision, expected_version=1, expected_card=original)

    assert store.get_card(original.id) == policy_revision


def test_expected_card_cas_rejects_same_version_correction_change_without_overwrite(store_setup):
    _, _, store = store_setup
    original = make_card()
    store.save_card(original)
    correction = OnboardingCorrection(
        correction_id="correction-1",
        card_id=original.id,
        card_version=original.version,
        kind=OnboardingCorrectionKind.INTENT_CLARIFIED,
        note="Compare sales with the planned promotion calendar.",
    )
    corrected = original.model_copy(update={"onboarding_corrections": [correction]})
    store.save_card(corrected)
    owner_revision = original.model_copy(update={"version": 2, "title": "Owner revision"})

    with pytest.raises(ValueError, match="changed since expected snapshot"):
        store.save_card_if_version(owner_revision, expected_version=1, expected_card=original)

    assert store.get_card(original.id) == corrected


@pytest.mark.parametrize(
    "snapshot_changes",
    [{"id": "another-card"}, {"version": 2}],
    ids=["wrong-card-id", "wrong-version"],
)
def test_expected_card_cas_rejects_incorrect_snapshot_identity_without_overwrite(
    store_setup, snapshot_changes
):
    _, _, store = store_setup
    original = make_card()
    store.save_card(original)
    incorrect_snapshot = original.model_copy(update=snapshot_changes)
    owner_revision = original.model_copy(update={"version": 2, "title": "Owner revision"})

    with pytest.raises(ValueError, match="expected_card must match"):
        store.save_card_if_version(
            owner_revision, expected_version=1, expected_card=incorrect_snapshot
        )

    assert store.get_card(original.id) == original
