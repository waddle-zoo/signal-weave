from __future__ import annotations

from datetime import datetime

import pytest

from signalweave.models import InsightCard, InsightCardStatus
from signalweave.store import JsonInsightCardStore, SQLiteInsightCardStore
from tests.test_onboarding import make_server, tool


def make_store(tmp_path, sqlite):
    if sqlite:
        return SQLiteInsightCardStore(tmp_path / "cards.db")
    return JsonInsightCardStore(tmp_path / "cards.json")


def minimal_card(card_id="snapshot-cas-card"):
    return InsightCard(
        id=card_id,
        title="Snapshot CAS card",
        what_to_watch="Watch the approved measure.",
        why_watch="Keep the owner informed about material change.",
    )


class RevisionAtSnapshotCheckStore:
    """Return the checked snapshot, then commit a revision before lifecycle CAS."""

    def __init__(self, inner, card_id):
        self.inner = inner
        self.card_id = card_id
        self.card_reads = 0
        self.concurrent_revision = None

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def get_card(self, card_id):
        snapshot = self.inner.get_card(card_id)
        if card_id == self.card_id:
            self.card_reads += 1
            if self.card_reads == 2:
                payload = snapshot.model_dump(mode="json")
                payload.update(
                    {
                        "title": "Concurrent revised title",
                        "what_to_watch": "The policy changed while review was in progress.",
                        "version": snapshot.version + 1,
                        "status": InsightCardStatus.DRAFT.value,
                        "approved_by": None,
                        "approved_at": None,
                        "compiled_plan": None,
                        "onboarding_review": None,
                    }
                )
                self.concurrent_revision = InsightCard.model_validate(payload)
                self.inner.save_card_if_version(
                    self.concurrent_revision,
                    snapshot.version,
                    expected_card=snapshot,
                )
        return snapshot


class CountingCardStore:
    def __init__(self, inner):
        self.inner = inner
        self.calls = {"save": 0, "version_cas": 0, "snapshot_cas": 0, "set_status": 0}

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def save_card(self, card):
        self.calls["save"] += 1
        return self.inner.save_card(card)

    def save_card_if_version(self, card, expected_version, *, expected_card=None):
        self.calls["version_cas"] += 1
        return self.inner.save_card_if_version(
            card,
            expected_version,
            expected_card=expected_card,
        )

    def save_card_if_unchanged(self, card, *, expected_card):
        self.calls["snapshot_cas"] += 1
        return self.inner.save_card_if_unchanged(card, expected_card=expected_card)

    def set_card_status(self, card_id, status):
        self.calls["set_status"] += 1
        return self.inner.set_card_status(card_id, status)


async def prepare_card(server, *, reviewed=False):
    draft = await tool(server, "draft_insight_card")(
        title="Weekly checkout conversion",
        what_to_watch="Watch checkout conversion for material movement.",
        why_watch="Help Growth decide when to investigate a change.",
        watch_for=["Checkout conversion materially declines."],
        sources=[
            {
                "key": "growth",
                "adapter": "superset",
                "resource": "dashboard:7",
                "label": "Growth overview",
            }
        ],
    )
    card_id = draft["card"]["id"]
    if reviewed:
        review = await tool(server, "review_insight_card")(card_id)
        assert review["review"]["readiness_status"] == "ready_for_approval"
    return card_id


@pytest.mark.parametrize("sqlite", [False, True], ids=["json-store", "sqlite-store"])
async def test_review_snapshot_cas_preserves_a_concurrent_revision(tmp_path, sqlite):
    server = make_server(tmp_path, sqlite=sqlite)
    runtime = server._test_runtime
    card_id = await prepare_card(server)
    inner = runtime.card_store
    racing_store = RevisionAtSnapshotCheckStore(inner, card_id)
    runtime.card_store = racing_store

    with pytest.raises(ValueError, match="changed since expected snapshot"):
        await tool(server, "review_insight_card")(card_id)

    assert racing_store.concurrent_revision is not None
    assert racing_store.card_reads == 2
    stored = inner.get_card(card_id)
    assert stored == racing_store.concurrent_revision
    assert stored.version == 2
    assert stored.title == "Concurrent revised title"
    assert stored.status is InsightCardStatus.DRAFT
    assert stored.onboarding_review is None
    assert stored.compiled_plan is None


@pytest.mark.parametrize("sqlite", [False, True], ids=["json-store", "sqlite-store"])
async def test_approval_snapshot_cas_preserves_a_concurrent_revision(tmp_path, sqlite):
    server = make_server(tmp_path, sqlite=sqlite)
    runtime = server._test_runtime
    card_id = await prepare_card(server, reviewed=True)
    inner = runtime.card_store
    racing_store = RevisionAtSnapshotCheckStore(inner, card_id)
    runtime.card_store = racing_store

    with pytest.raises(ValueError, match="changed since expected snapshot"):
        await tool(server, "approve_insight_card")(card_id)

    assert racing_store.concurrent_revision is not None
    assert racing_store.card_reads == 2
    stored = inner.get_card(card_id)
    assert stored == racing_store.concurrent_revision
    assert stored.version == 2
    assert stored.title == "Concurrent revised title"
    assert stored.status is InsightCardStatus.DRAFT
    assert stored.approved_by is None
    assert stored.approved_at is None
    assert stored.onboarding_review is None
    assert stored.compiled_plan is None


@pytest.mark.parametrize("sqlite", [False, True], ids=["json-store", "sqlite-store"])
async def test_approval_commits_review_plan_status_and_owner_in_one_same_version_cas(
    tmp_path, sqlite
):
    server = make_server(tmp_path, sqlite=sqlite)
    runtime = server._test_runtime
    card_id = await prepare_card(server, reviewed=True)
    inner = runtime.card_store
    before = inner.get_card(card_id)
    counting_store = CountingCardStore(inner)
    runtime.card_store = counting_store

    result = await tool(server, "approve_insight_card")(card_id)

    stored = inner.get_card(card_id)
    assert result["status"] == "approved"
    assert stored.status is InsightCardStatus.APPROVED
    assert stored.version == before.version
    assert stored.approved_by == "test-principal"
    assert isinstance(stored.approved_at, datetime)
    assert stored.compiled_plan is not None
    assert stored.compiled_plan.card_version == stored.version
    assert stored.onboarding_review is not None
    assert counting_store.calls == {
        "save": 0,
        "version_cas": 0,
        "snapshot_cas": 1,
        "set_status": 0,
    }


@pytest.mark.parametrize("sqlite", [False, True], ids=["json-store", "sqlite-store"])
def test_same_version_snapshot_cas_is_strict_and_increment_cas_still_requires_plus_one(
    tmp_path, sqlite
):
    store = make_store(tmp_path, sqlite)
    original = minimal_card()
    store.save_card(original)

    unchanged_version_update = original.model_copy(update={"title": "Review metadata saved"})
    with pytest.raises(ValueError, match="increment expected_version by exactly 1"):
        store.save_card_if_version(
            unchanged_version_update,
            original.version,
            expected_card=original,
        )
    assert store.get_card(original.id) == original

    store.save_card_if_unchanged(unchanged_version_update, expected_card=original)
    saved = store.get_card(original.id)
    assert saved.version == original.version
    assert saved.title == "Review metadata saved"

    stale_writer = saved.model_copy(update={"why_watch": "Stale concurrent update."})
    with pytest.raises(ValueError, match="changed since expected snapshot"):
        store.save_card_if_unchanged(stale_writer, expected_card=original)
    assert store.get_card(original.id) == saved

    version_two = saved.model_copy(update={"title": "A real policy revision", "version": 2})
    store.save_card_if_version(version_two, saved.version, expected_card=saved)
    assert store.get_card(original.id) == version_two

    version_four = version_two.model_copy(update={"title": "Skipped a version", "version": 4})
    with pytest.raises(ValueError, match="increment expected_version by exactly 1"):
        store.save_card_if_version(version_four, version_two.version, expected_card=version_two)
    assert store.get_card(original.id) == version_two
