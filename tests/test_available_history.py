from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from evaluations.available_history import project_events

UTC = timezone.utc


def event(
    event_id: str,
    revision: int,
    effective_at: datetime,
    available_at: datetime,
    payload: object,
    tombstone: bool = False,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "revision": revision,
        "effective_at": effective_at,
        "available_at": available_at,
        "payload": payload,
        "tombstone": tombstone,
    }


def test_projects_latest_known_opaque_events_without_falling_back() -> None:
    start = datetime(2026, 4, 6, 8, tzinfo=UTC)
    records = [
        event("evt-created", 1, start, start, {"kind": "creation", "amount": 31}),
        event(
            "evt-created",
            2,
            start,
            start + timedelta(hours=5),
            {"kind": "creation", "amount": 32},
        ),
        event(
            "evt-response",
            1,
            start + timedelta(minutes=20),
            start + timedelta(hours=4),
            {"kind": "response", "code": "r7"},
        ),
        event(
            "evt-resolution",
            1,
            start + timedelta(hours=1),
            start + timedelta(hours=1),
            {"kind": "resolution", "state": "closed"},
        ),
        event(
            "evt-resolution",
            2,
            start + timedelta(hours=8),
            start + timedelta(hours=3),
            {"kind": "resolution", "state": "corrected"},
        ),
        event(
            "evt-refund",
            1,
            start + timedelta(hours=2),
            start + timedelta(hours=2),
            {"kind": "refund", "amount": 12},
        ),
        event(
            "evt-refund",
            2,
            start + timedelta(hours=2),
            start + timedelta(hours=4),
            {"kind": "refund", "amount": 12},
            tombstone=True,
        ),
    ]

    before_corrections = project_events(records, start + timedelta(hours=2))
    assert [(row["event_id"], row["revision"], row["payload"]) for row in before_corrections] == [
        ("evt-created", 1, {"kind": "creation", "amount": 31}),
        ("evt-refund", 1, {"kind": "refund", "amount": 12}),
        ("evt-resolution", 1, {"kind": "resolution", "state": "closed"}),
    ]

    after_corrections = project_events(records, start + timedelta(hours=5))
    assert [(row["event_id"], row["revision"], row["payload"]) for row in after_corrections] == [
        ("evt-created", 2, {"kind": "creation", "amount": 32}),
        ("evt-response", 1, {"kind": "response", "code": "r7"}),
    ]

    # Reversing arrival order cannot change selection or deterministic output order.
    assert project_events(list(reversed(records)), start + timedelta(hours=5)) == after_corrections


def test_offset_equivalent_cutoff_is_inclusive_and_future_times_are_excluded() -> None:
    cutoff = datetime(2026, 5, 1, 12, tzinfo=UTC)
    offset = timezone(timedelta(hours=-5))
    records = [
        event(
            "evt-boundary",
            1,
            datetime(2026, 5, 1, 7, tzinfo=offset),
            datetime(2026, 5, 1, 7, tzinfo=offset),
            {"value": "exact"},
        ),
        event(
            "evt-late-availability",
            1,
            datetime(2026, 5, 1, 6, tzinfo=offset),
            datetime(2026, 5, 1, 7, 1, tzinfo=offset),
            {"value": "known-after-cutoff"},
        ),
        event(
            "evt-future-effective",
            1,
            datetime(2026, 5, 1, 7, 1, tzinfo=offset),
            datetime(2026, 5, 1, 7, tzinfo=offset),
            {"value": "effective-after-cutoff"},
        ),
    ]

    result = project_events(records, cutoff)
    assert [(row["event_id"], row["payload"]) for row in result] == [
        ("evt-boundary", {"value": "exact"})
    ]


def test_sparse_out_of_order_revisions_and_explicit_revival_after_tombstone() -> None:
    start = datetime(2026, 5, 12, tzinfo=UTC)
    records = [
        event("evt-versioned", 1, start, start, {"value": "initial"}),
        event(
            "evt-versioned",
            7,
            start,
            start + timedelta(hours=2),
            {"value": "removed"},
            tombstone=True,
        ),
        # A lower, sparse revision arrives after revision 7 and cannot regress it.
        event(
            "evt-versioned",
            3,
            start,
            start + timedelta(hours=3),
            {"value": "late-lower-revision"},
        ),
        event(
            "evt-versioned",
            12,
            start + timedelta(hours=4),
            start + timedelta(hours=5),
            {"value": "explicit-revival"},
        ),
    ]

    assert [row["revision"] for row in project_events(records, start + timedelta(hours=1))] == [1]
    assert project_events(records, start + timedelta(hours=2)) == []
    assert project_events(records, start + timedelta(hours=4)) == []
    revived = project_events(records, start + timedelta(hours=6))
    assert [(row["revision"], row["payload"]) for row in revived] == [
        (12, {"value": "explicit-revival"})
    ]


@pytest.mark.parametrize("kind", ["correction", "tombstone", "future_effective"])
def test_named_zone_fall_back_compares_instants_not_equal_wall_times(kind) -> None:
    early = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/Toronto"), fold=0)
    late = early.replace(fold=1)
    assert early.astimezone(UTC) < late.astimezone(UTC)
    past = early - timedelta(days=1)
    if kind == "future_effective":
        records = [event("future", 1, late, early, {"value": "future"})]
        assert project_events(records, early) == []
        assert [row["event_id"] for row in project_events(records, late)] == ["future"]
    else:
        records = [event("known", 1, past, past, {"value": "original"}),
            event("known", 2, past, late, {"value": "correction"}, tombstone=kind == "tombstone")]
        assert [row["revision"] for row in project_events(records, early)] == [1]
        expected = [] if kind == "tombstone" else [2]
        assert [row["revision"] for row in project_events(records, late)] == expected


def test_future_revision_does_not_leak_into_earlier_projection() -> None:
    cutoff = datetime(2026, 6, 10, 12, tzinfo=UTC)
    original = event(
        "evt-late-fix",
        1,
        cutoff - timedelta(days=1),
        cutoff - timedelta(days=1),
        {"value": "known"},
    )
    future_revision = event(
        "evt-late-fix",
        2,
        cutoff - timedelta(days=1),
        cutoff + timedelta(seconds=1),
        {"value": "not-yet-known"},
    )

    assert project_events([original, future_revision], cutoff) == project_events([original], cutoff)
    assert project_events([original, future_revision], cutoff + timedelta(seconds=2))[0][
        "payload"
    ] == {"value": "not-yet-known"}


def test_result_payload_is_deeply_isolated_from_input_and_other_projections() -> None:
    cutoff = datetime(2026, 7, 2, tzinfo=UTC)
    source = event(
        "evt-copy",
        1,
        cutoff,
        cutoff,
        {"nested": {"items": ["original"]}},
    )

    first = project_events([source], cutoff)
    first[0]["payload"]["nested"]["items"].append("changed")  # type: ignore[index]
    second = project_events([source], cutoff)

    assert source["payload"] == {"nested": {"items": ["original"]}}
    assert second[0]["payload"] == {"nested": {"items": ["original"]}}


@pytest.mark.parametrize(
    "record,cutoff",
    [
        (event("evt-naive-effective", 1, datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=UTC), {}), datetime(2026, 1, 2, tzinfo=UTC)),
        (event("evt-naive-available", 1, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 1), {}), datetime(2026, 1, 2, tzinfo=UTC)),
        (event("evt-aware", 1, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC), {}), datetime(2026, 1, 2)),
        (event("evt-bad-revision", True, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC), {}), datetime(2026, 1, 2, tzinfo=UTC)),
        (event("evt-zero-revision", 0, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC), {}), datetime(2026, 1, 2, tzinfo=UTC)),
        (event("evt-negative-revision", -1, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC), {}), datetime(2026, 1, 2, tzinfo=UTC)),
    ],
)
def test_rejects_naive_timestamps_and_nonpositive_integer_contract(
    record: dict[str, object], cutoff: datetime
) -> None:
    with pytest.raises(ValueError):
        project_events([record], cutoff)


def test_rejects_duplicate_revisions_even_when_one_is_not_yet_available() -> None:
    cutoff = datetime(2026, 8, 1, tzinfo=UTC)
    first = event("evt-duplicate", 1, cutoff, cutoff, {"value": 1})
    duplicate = event(
        "evt-duplicate", 1, cutoff, cutoff + timedelta(days=1), {"value": 2}
    )

    with pytest.raises(ValueError, match="duplicate revision"):
        project_events([first, duplicate], cutoff)


def test_rejects_missing_payload_and_non_boolean_tombstone() -> None:
    cutoff = datetime(2026, 9, 1, tzinfo=UTC)
    missing_payload = event("evt-missing", 1, cutoff, cutoff, {})
    del missing_payload["payload"]
    invalid_tombstone = event("evt-tombstone", 1, cutoff, cutoff, {}, tombstone=1)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="missing required fields"):
        project_events([missing_payload], cutoff)
    with pytest.raises(ValueError, match="tombstone must be boolean"):
        project_events([invalid_tombstone], cutoff)


def _software_reference_projection(
    records: list[dict[str, object]], cutoff: datetime
) -> list[tuple[str, int, object]]:
    """Test-side software reference; it encodes projection mechanics, not business truth."""
    by_event: dict[str, list[dict[str, object]]] = {}
    for record in records:
        if record["available_at"] <= cutoff:  # type: ignore[operator]
            by_event.setdefault(record["event_id"], []).append(record)  # type: ignore[arg-type]

    expected = []
    for event_id, eligible in by_event.items():
        chosen = max(eligible, key=lambda record: record["revision"])
        if chosen["effective_at"] <= cutoff and not chosen["tombstone"]:  # type: ignore[operator]
            expected.append((event_id, chosen["revision"], chosen["payload"]))
    return sorted(expected)


def test_scaled_separate_company_stores_across_twelve_weekly_cutoffs() -> None:
    start = datetime(2026, 1, 5, tzinfo=UTC)
    cutoffs = [start + timedelta(weeks=week) for week in range(1, 13)]
    stores: dict[str, list[dict[str, object]]] = {}

    for company_index in range(12):
        # Each store is supplied separately; records have no tenant field and
        # this helper makes no claim to enforce company isolation.
        company_key = f"company-{company_index:02d}"
        records = []
        for event_index in range(1000):
            event_id = f"{company_key}-event-{event_index:04d}"
            effective_at = start + timedelta(days=event_index % 84)
            available_at = effective_at + timedelta(hours=2)
            records.append(
                event(
                    event_id,
                    1,
                    effective_at,
                    available_at,
                    {"value": event_index, "version": "base"},
                )
            )

            if event_index % 10 == 0:
                correction_available = start + timedelta(weeks=2 + event_index % 11)
                is_deletion = event_index % 25 == 0
                records.append(
                    event(
                        event_id,
                        2,
                        effective_at + timedelta(days=2),
                        correction_available,
                        {"value": event_index + 1, "version": "correction"},
                        tombstone=is_deletion,
                    )
                )
        stores[company_key] = records

    for company_key, records in stores.items():
        assert len({record["event_id"] for record in records}) == 1000
        assert len(records) == 1100
        assert sum(record["revision"] == 1 for record in records) == 1000
        assert sum(record["revision"] == 2 for record in records) == 100
        for cutoff in cutoffs:
            actual = [
                (row["event_id"], row["revision"], row["payload"])
                for row in project_events(records, cutoff)
            ]
            expected = _software_reference_projection(records, cutoff)
            assert actual == expected
            assert all(event_id.startswith(f"{company_key}-") for event_id, _, _ in actual)
