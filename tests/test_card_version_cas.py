from concurrent.futures import ThreadPoolExecutor

import pytest

from signalweave.models import InsightCard
from signalweave.store import JsonInsightCardStore, SQLiteInsightCardStore


def make_card(card_id="card-1", *, version=1, title="Sales pulse"):
    return InsightCard(
        id=card_id,
        title=title,
        what_to_watch="Sales movement.",
        why_watch="Decide whether the team should act.",
        version=version,
    )


@pytest.fixture(params=[JsonInsightCardStore, SQLiteInsightCardStore], ids=["json", "sqlite"])
def store_setup(request, tmp_path):
    store_type = request.param
    filename = "cards.json" if store_type is JsonInsightCardStore else "cards.db"
    path = tmp_path / filename
    return store_type, path, store_type(path)


def test_save_card_if_version_advances_exactly_one_version(store_setup):
    _, _, store = store_setup
    original = make_card()
    store.save_card(original)
    updated = original.model_copy(update={"version": 2, "title": "Updated sales pulse"})

    assert store.save_card_if_version(updated, expected_version=1) is None
    saved = store.get_card(original.id)
    assert saved.version == 2
    assert saved.title == "Updated sales pulse"


def test_save_card_if_version_rejects_missing_stale_and_wrong_versions(store_setup):
    _, _, store = store_setup
    candidate = make_card(version=2)
    with pytest.raises(KeyError, match="Unknown insight card"):
        store.save_card_if_version(candidate, expected_version=1)

    original = make_card()
    store.save_card(original)
    wrong_increment = original.model_copy(update={"version": 3})
    with pytest.raises(ValueError, match="exactly 1"):
        store.save_card_if_version(wrong_increment, expected_version=1)

    advanced = original.model_copy(update={"version": 2, "title": "Winner"})
    store.save_card_if_version(advanced, expected_version=1)
    stale = original.model_copy(update={"version": 2, "title": "Stale overwrite"})
    with pytest.raises(ValueError, match="version conflict"):
        store.save_card_if_version(stale, expected_version=1)
    assert store.get_card(original.id).title == "Winner"


@pytest.mark.parametrize("expected_version", [0, -1, True, "1"])
def test_save_card_if_version_requires_a_strict_positive_expected_version(
    store_setup, expected_version
):
    _, _, store = store_setup
    with pytest.raises(ValueError, match="expected_version"):
        store.save_card_if_version(make_card(version=2), expected_version=expected_version)


def test_concurrent_card_cas_writers_cannot_both_win(store_setup):
    store_type, path, first_store = store_setup
    second_store = store_type(path)
    original = make_card()
    first_store.save_card(original)
    candidates = [
        original.model_copy(update={"version": 2, "title": f"Writer {index}"})
        for index in range(2)
    ]

    def try_update(store, card):
        try:
            store.save_card_if_version(card, expected_version=1)
            return True
        except ValueError as exc:
            assert "version conflict" in str(exc)
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda item: try_update(item[0], item[1]),
                [(first_store, candidates[0]), (second_store, candidates[1])],
            )
        )

    assert sorted(results) == [False, True]
    assert first_store.get_card(original.id).version == 2
