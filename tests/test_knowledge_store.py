from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from signalweave.knowledge_models import KnowledgeContent, KnowledgeEntry
from signalweave.knowledge_store import SQLiteKnowledgeStore
from signalweave.models import SourceRef


def make_entry(
    entry_id="context-1",
    *,
    tenant_id="tenant-a",
    revision=1,
    actor="alice",
    title="Net sales",
    body="Net sales exclude refunds.",
    domain="finance",
    readers=None,
    sources=None,
    status="reviewed",
    review_after=None,
):
    now = datetime.now(timezone.utc)
    return KnowledgeEntry(
        id=entry_id,
        tenant_id=tenant_id,
        revision=revision,
        actor=actor,
        status=status,
        content=KnowledgeContent(
            domain=domain,
            title=title,
            body=body,
            kind="definition",
            sources=sources
            or [
                SourceRef(
                    key="sales-chart",
                    adapter="superset",
                    resource="chart:net-sales",
                    label="Net sales chart",
                )
            ],
            provenance=["owner-review:2026-10-14"],
            review_after=review_after or now + timedelta(days=30),
            reader_principal_ids=readers or [],
        ),
    )


def test_append_is_durable_tenant_scoped_and_compare_and_swap(tmp_path):
    path = tmp_path / "knowledge.db"
    store = SQLiteKnowledgeStore(path)
    original = make_entry()
    store.append(original, expected_revision=0)
    updated = original.model_copy(
        update={
            "revision": 2,
            "content": original.content.model_copy(update={"body": "Updated definition."}),
        }
    )
    store.append(updated, expected_revision=1)

    other_tenant = make_entry(tenant_id="tenant-b", body="A different tenant's note.")
    store.append(other_tenant, expected_revision=0)

    reopened = SQLiteKnowledgeStore(path)
    assert reopened.get("tenant-a", original.id, "bob").revision == 2
    assert reopened.get("tenant-b", original.id, "bob").content.body == (
        "A different tenant's note."
    )
    assert [entry.revision for entry in reopened.history("tenant-a", original.id, "bob")] == [
        1,
        2,
    ]
    stale = updated.model_copy(update={"revision": 3})
    with pytest.raises(ValueError, match="revision conflict"):
        reopened.append(stale, expected_revision=1)
    assert reopened.get("tenant-a", original.id, "bob").content.body == "Updated definition."


def test_owner_id_is_immutable_across_revisions(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    original = make_entry().model_copy(update={"owner_id": "original-owner"})
    store.append(original, expected_revision=0)
    updated = original.model_copy(update={"revision": 2, "actor": "reviewer"})
    store.append(updated, expected_revision=1)

    changed_owner = updated.model_copy(update={"revision": 3, "owner_id": "new-owner"})
    with pytest.raises(ValueError, match="owner_id is immutable"):
        store.append(changed_owner, expected_revision=2)
    assert store.get("tenant-a", original.id, "alice").owner_id == "original-owner"
    assert [entry.revision for entry in store.history("tenant-a", original.id, "alice")] == [
        1,
        2,
    ]


def test_begin_immediate_allows_only_one_concurrent_revision_writer(tmp_path):
    path = tmp_path / "knowledge.db"
    first = SQLiteKnowledgeStore(path)
    second = SQLiteKnowledgeStore(path)
    original = make_entry()
    first.append(original, expected_revision=0)
    candidates = [
        original.model_copy(
            update={
                "revision": 2,
                "content": original.content.model_copy(update={"body": f"Writer {i}."}),
            }
        )
        for i in range(2)
    ]

    def try_append(item):
        try:
            return second.append(item, expected_revision=1).content.body
        except ValueError as exc:
            assert "revision conflict" in str(exc)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(try_append, candidates))

    assert sum(outcome is not None for outcome in outcomes) == 1
    assert [entry.revision for entry in first.history("tenant-a", original.id, "alice")] == [
        1,
        2,
    ]


def test_history_requires_current_visibility_and_filters_each_old_acl(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    shared = make_entry()
    store.append(shared, expected_revision=0)
    private = shared.model_copy(
        update={
            "revision": 2,
            "content": shared.content.model_copy(
                update={"body": "Private revision.", "reader_principal_ids": ["alice"]}
            ),
        }
    )
    store.append(private, expected_revision=1)

    hidden_replacement = private.model_copy(
        update={
            "revision": 3,
            "actor": "bob",
            "content": private.content.model_copy(update={"body": "Unauthorized replacement."}),
        }
    )
    with pytest.raises(KeyError) as hidden_get:
        store.get("tenant-a", shared.id, "bob")
    with pytest.raises(KeyError) as hidden_append:
        store.append(hidden_replacement, expected_revision=2)
    with pytest.raises(KeyError) as hidden_history:
        store.history("tenant-a", shared.id, "bob")
    assert hidden_get.value.args == hidden_append.value.args == hidden_history.value.args

    shared_again = private.model_copy(
        update={
            "revision": 3,
            "content": private.content.model_copy(
                update={"body": "Shared again.", "reader_principal_ids": []}
            ),
        }
    )
    store.append(shared_again, expected_revision=2)

    assert [entry.revision for entry in store.history("tenant-a", shared.id, "bob")] == [1, 3]
    assert store.history("tenant-a", shared.id, "alice")[1].content.body == "Private revision."


def test_search_uses_unicode_literal_tokens_and_exact_anchor_union(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    multilingual = make_entry(
        title="Café — Q4",
        body="The 東京 cohort uses the verified metric.",
        sources=[
            SourceRef(
                key="cafe-chart",
                adapter="superset",
                resource="chart:cafe-q4",
                label="Café chart",
            )
        ],
    )
    anchored = make_entry(
        "context-2",
        title="Another definition",
        body="An unrelated sentence.",
        sources=[
            SourceRef(
                key="metric-query",
                adapter="trino",
                resource="query:customer-health",
                label="Customer health query",
            )
        ],
    )
    store.append(multilingual, expected_revision=0)
    store.append(anchored, expected_revision=0)

    assert [item.id for item in store.search("tenant-a", "alice", "café—Q4 東京")] == [
        multilingual.id
    ]
    # The anchor arm is a union with text matches, and compares exact values.
    assert [
        item.id
        for item in store.search(
            "tenant-a",
            "alice",
            "no lexical match",
            source_refs=["trino|query:customer-health"],
        )
    ] == [anchored.id]
    union_ids = {
        item.id
        for item in store.search(
            "tenant-a", "alice", "café", source_refs=["trino|query:customer-health"]
        )
    }
    assert union_ids == {multilingual.id, anchored.id}
    assert store.search(
        "tenant-a", "alice", "", source_refs=["trino|query:customer-health' OR 1=1 --"]
    ) == []


def test_search_treats_fts_operators_and_sql_like_input_as_literal(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    store.append(make_entry("one", body="ordinary context"), expected_revision=0)
    store.append(make_entry("two", body="OR 1 1 MATCH NEAR"), expected_revision=0)

    assert store.search("tenant-a", "alice", '" OR 7=7 --') == []
    assert store.search("tenant-a", "alice", "ordinary') OR 1=1 --") == []


def test_revision_update_replaces_only_current_fts_and_anchor_indexes(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    original = make_entry(
        title="Alpha definition",
        body="Alpha is the current name.",
        sources=[
            SourceRef(key="old", adapter="superset", resource="chart:old", label="Old")
        ],
    )
    store.append(original, expected_revision=0)
    revised = original.model_copy(
        update={
            "revision": 2,
            "content": original.content.model_copy(
                update={
                    "title": "Beta definition",
                    "body": "Beta is the current name.",
                    "sources": [
                        SourceRef(
                            key="new", adapter="superset", resource="chart:new", label="New"
                        )
                    ],
                }
            ),
        }
    )
    store.append(revised, expected_revision=1)

    assert store.search("tenant-a", "alice", "alpha") == []
    assert store.search("tenant-a", "alice", "", source_refs=["superset|chart:old"]) == []
    assert [item.id for item in store.search("tenant-a", "alice", "beta")] == [original.id]
    assert [
        item.id
        for item in store.search("tenant-a", "alice", "", source_refs=["superset|chart:new"])
    ] == [original.id]


def test_search_filters_visibility_retirement_domain_and_due_date_before_limit(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    store.append(
        make_entry(
            "a-hidden",
            body="needle recurring issue",
            readers=["alice"],
            review_after=now - timedelta(days=4),
        ),
        expected_revision=0,
    )
    store.append(
        make_entry(
            "b-retired",
            body="needle retired issue",
            status="retired",
            review_after=now - timedelta(days=3),
        ),
        expected_revision=0,
    )
    store.append(
        make_entry(
            "z-visible",
            body="needle visible issue",
            review_after=now - timedelta(days=2),
        ),
        expected_revision=0,
    )
    store.append(
        make_entry(
            "a-due",
            domain="operations",
            review_after=now - timedelta(days=2),
        ),
        expected_revision=0,
    )
    store.append(
        make_entry(
            "b-due",
            domain="operations",
            review_after=now - timedelta(days=1),
        ),
        expected_revision=0,
    )
    store.append(
        make_entry(
            "aa-due",
            domain="operations",
            review_after=now - timedelta(days=2),
        ),
        expected_revision=0,
    )
    store.append(
        make_entry("c-future", domain="operations", review_after=now + timedelta(days=1)),
        expected_revision=0,
    )

    assert [item.id for item in store.search("tenant-a", "bob", "needle", limit=1)] == [
        "z-visible"
    ]
    assert [
        item.id
        for item in store.search(
            "tenant-a", "bob", "", domain="operations", review_due_before=now, limit=3
        )
    ] == ["a-due", "aa-due", "b-due"]


def test_reviewed_only_filter_is_applied_before_candidate_limit(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    store.append(make_entry("a-draft", body="needle draft", status="draft"), expected_revision=0)
    store.append(make_entry("z-reviewed", body="needle reviewed"), expected_revision=0)

    assert [item.id for item in store.search("tenant-a", "alice", "needle", limit=1)] == [
        "a-draft"
    ]
    assert [
        item.id
        for item in store.search("tenant-a", "alice", "needle", limit=1, include_drafts=False)
    ] == ["z-reviewed"]


def test_search_offset_pages_bounded_sorted_results(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    for entry_id in ("a", "b", "c", "d"):
        store.append(make_entry(entry_id, body="pagination marker"), expected_revision=0)

    page_one = store.search("tenant-a", "alice", "pagination", limit=2, offset=0)
    page_two = store.search("tenant-a", "alice", "pagination", limit=2, offset=2)
    page_three = store.search("tenant-a", "alice", "pagination", limit=2, offset=4)
    assert [entry.id for entry in page_one] == ["a", "b"]
    assert [entry.id for entry in page_two] == ["c", "d"]
    assert page_three == []


def test_search_bounds_utf8_query_and_deduplicates_literal_tokens(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    store.append(make_entry(body="needle context"), expected_revision=0)

    with pytest.raises(ValueError, match="2000 UTF-8 bytes"):
        store.search("tenant-a", "alice", "é" * 1001)
    with pytest.raises(ValueError, match="64 distinct"):
        store.search("tenant-a", "alice", " ".join(f"token{i}" for i in range(65)))
    assert [item.id for item in store.search("tenant-a", "alice", "needle " * 65)] == [
        "context-1"
    ]


def test_search_and_history_enforce_hard_result_bounds(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    entry = make_entry()
    store.append(entry, expected_revision=0)

    with pytest.raises(ValueError, match="between 1 and 100"):
        store.search("tenant-a", "alice", "sales", limit=101)
    with pytest.raises(ValueError, match="offset must be between 0 and 300"):
        store.search("tenant-a", "alice", "sales", offset=301)
    with pytest.raises(ValueError, match="at most 100 anchors"):
        store.search("tenant-a", "alice", "", source_refs=["superset|chart:1"] * 101)
    with pytest.raises(ValueError, match="between 1 and 50"):
        store.history("tenant-a", entry.id, "alice", limit=51)
