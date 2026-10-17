from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from evaluations.harbor_history_reference import summarize_history

UTC = timezone.utc
MONDAY = datetime(2024, 1, 1, tzinfo=UTC)


def _event(
    event_id,
    kind,
    effective_at,
    payload,
    *,
    available_at=None,
    revision=1,
    tombstone=False,
):
    return {
        "event_id": event_id,
        "revision": revision,
        "effective_at": effective_at,
        "available_at": effective_at if available_at is None else available_at,
        "tombstone": tombstone,
        "payload": {"kind": kind, **payload},
    }


def _history(events, *, first_week=MONDAY, regions=("east",)):
    return {
        "first_week": first_week,
        "clock_definitions": [
            {
                "support_tier": "standard",
                "resolution_sla_hours": 2,
                "first_response_sla_hours": 1,
            }
        ],
        "regions": list(regions),
        "events": events,
    }


def _created(ticket_id, at, *, priority=1, region="east", available_at=None):
    return _event(
        f"create-{ticket_id}",
        "created",
        at,
        {
            "ticket_id": ticket_id,
            "support_tier": "standard",
            "region": region,
            "priority": priority,
        },
        available_at=available_at,
    )


def _child(event_id, kind, ticket_id, at, **kwargs):
    return _event(event_id, kind, at, {"ticket_id": ticket_id}, **kwargs)


def test_second_boundaries_and_clock_populations_are_independent():
    at = MONDAY
    events = [
        _created("T01", at),
        _child("EV01", "response", "T01", at + timedelta(hours=1)),
        _child("EV02", "resolution", "T01", at + timedelta(hours=2)),
        _created("T02", at),
        _child(
            "EV03",
            "resolution",
            "T02",
            at + timedelta(hours=2, seconds=1),
        ),
        _created("T03", at, priority=0),
        _child(
            "EV04",
            "response",
            "T03",
            at + timedelta(hours=1, seconds=1),
        ),
        _created("T04", at),
        _child(
            "EV05",
            "response",
            "T04",
            at + timedelta(hours=1, seconds=1),
        ),
        _created("T05", at, priority=0),
    ]
    cutoff = MONDAY + timedelta(days=6, hours=23, minutes=59, seconds=59)

    result = summarize_history(_history(events), cutoff)

    assert result["as_of_utc"] == "2024-01-07T23:59:59Z"
    assert result["resolution"] == [
        {
            "week_start_utc": "2024-01-01",
            "support_tier": "standard",
            "region": "east",
            "observed_ticket_count": 5,
            "eligible_resolved_tickets": 2,
            "resolution_sla_misses": 1,
            "resolution_sla_miss_rate": 0.5,
        }
    ]
    assert result["first_response"] == [
        {
            "week_start_utc": "2024-01-01",
            "support_tier": "standard",
            "region": "east",
            "observed_ticket_count": 5,
            "first_response_clock_tickets": 3,
            "first_response_sla_misses": 2,
            "first_response_sla_miss_rate": 2 / 3,
        }
    ]
    assert result["backlog"] == [
        {
            "week_start_utc": "2024-01-01",
            "support_tier": "standard",
            "region": "east",
            "as_of_utc": "2024-01-07T23:59:59Z",
            "open_priority_tickets": 1,
            "overdue_open_priority_tickets": 1,
            "unanswered_tickets": 1,
            "overdue_unanswered_tickets": 1,
        }
    ]
    tickets = {ticket["ticket_id"]: ticket for ticket in result["tickets"]}
    assert tickets["T02"]["first_response_at_utc"] is None
    assert tickets["T02"]["status"] == "resolved"
    assert tickets["T04"]["status"] == "open"


def test_late_arrivals_corrections_and_retractions_replace_old_state():
    at = MONDAY
    events = [
        _created("T01", at, available_at=at + timedelta(minutes=30)),
        _child(
            "EV01",
            "response",
            "T01",
            at + timedelta(minutes=30),
            available_at=at + timedelta(hours=1),
        ),
        _child(
            "EV01",
            "response",
            "T01",
            at + timedelta(hours=1, seconds=1),
            available_at=at + timedelta(hours=1, seconds=1),
            revision=2,
        ),
        _child(
            "EV01",
            "response",
            "T01",
            at + timedelta(hours=1, minutes=30),
            available_at=at + timedelta(hours=1, minutes=30),
            revision=3,
            tombstone=True,
        ),
        _child(
            "EV02",
            "resolution",
            "T01",
            at + timedelta(hours=2),
            available_at=at + timedelta(hours=2),
        ),
        _child(
            "EV02",
            "resolution",
            "T01",
            at + timedelta(hours=3),
            available_at=at + timedelta(hours=3),
            revision=2,
        ),
        _child(
            "EV02",
            "resolution",
            "T01",
            at + timedelta(hours=4),
            available_at=at + timedelta(hours=4),
            revision=3,
            tombstone=True,
        ),
    ]
    history = _history(events)

    before_creation = summarize_history(history, at + timedelta(minutes=20))
    assert before_creation["tickets"] == []

    after_creation = summarize_history(history, at + timedelta(minutes=45))
    assert after_creation["tickets"][0]["first_response_at_utc"] is None
    assert after_creation["backlog"][0]["unanswered_tickets"] == 1
    assert after_creation["coverage"] == []

    before_response_correction = summarize_history(history, at + timedelta(hours=1))
    assert (
        before_response_correction["tickets"][0]["first_response_at_utc"]
        == "2024-01-01T00:30:00Z"
    )
    assert before_response_correction["first_response"][0]["first_response_sla_misses"] == 0

    after_response_correction = summarize_history(
        history, at + timedelta(hours=1, seconds=1)
    )
    assert (
        after_response_correction["tickets"][0]["first_response_at_utc"]
        == "2024-01-01T01:00:01Z"
    )
    assert after_response_correction["first_response"][0]["first_response_sla_misses"] == 1

    after_resolution = summarize_history(history, at + timedelta(hours=2))
    assert after_resolution["tickets"][0]["status"] == "resolved"
    assert after_resolution["resolution"][0]["resolution_sla_misses"] == 0

    after_resolution_correction = summarize_history(history, at + timedelta(hours=3))
    assert (
        after_resolution_correction["tickets"][0]["resolved_at_utc"]
        == "2024-01-01T03:00:00Z"
    )
    assert after_resolution_correction["resolution"][0]["resolution_sla_misses"] == 1

    after_retractions = summarize_history(history, at + timedelta(hours=4))
    assert after_retractions["tickets"][0]["status"] == "open"
    assert after_retractions["tickets"][0]["first_response_at_utc"] is None
    assert after_retractions["tickets"][0]["resolved_at_utc"] is None
    assert after_retractions["backlog"][0]["overdue_unanswered_tickets"] == 1


def test_unavailable_future_revision_does_not_leak_then_replaces_old_revision():
    at = MONDAY
    history = _history(
        [
            _event(
                "EV01",
                "created",
                at,
                {
                    "ticket_id": "T01",
                    "support_tier": "standard",
                    "region": "east",
                    "priority": 1,
                },
            ),
            _event(
                "EV01",
                "created",
                at + timedelta(hours=3),
                {
                    "ticket_id": "T01",
                    "support_tier": "standard",
                    "region": "east",
                    "priority": 1,
                },
                available_at=at + timedelta(hours=3),
                revision=2,
            ),
        ]
    )

    before_revision_arrives = summarize_history(history, at + timedelta(hours=2))
    assert before_revision_arrives["tickets"][0]["created_at_utc"] == "2024-01-01T00:00:00Z"

    corrected = summarize_history(history, at + timedelta(hours=3))
    assert corrected["tickets"][0]["created_at_utc"] == "2024-01-01T03:00:00Z"


def test_coverage_distinguishes_unknown_zero_missing_partial_and_excess():
    at = MONDAY
    cutoff = at + timedelta(days=7)
    regions = ("r1", "r2", "r3", "r4", "r5")
    events = [
        _event(
            f"manifest-{region}",
            "partition",
            cutoff,
            {
                "week_start_utc": at.date().isoformat(),
                "support_tier": "standard",
                "region": region,
                "expected_ticket_count": expected,
            },
        )
        for region, expected in (
            ("r1", 0),
            ("r2", 2),
            ("r3", 2),
            ("r4", 1),
        )
    ]
    for region, count in (
        ("r4", 2),
        ("r3", 1),
        ("r5", 1),
    ):
        for index in range(count):
            ticket_id = f"{region}-{index}"
            events.append(
                _created(ticket_id, at + timedelta(hours=1), priority=0, region=region)
            )

    result = summarize_history(_history(events, regions=regions), cutoff)
    coverage = {row["region"]: row for row in result["coverage"]}

    assert coverage["r1"]["coverage_status"] == "complete"
    assert coverage["r1"]["expected_ticket_count"] == 0
    assert coverage["r2"]["coverage_status"] == "missing"
    assert coverage["r2"]["missing_ticket_count"] == 2
    assert coverage["r3"]["coverage_status"] == "partial"
    assert coverage["r3"]["missing_ticket_count"] == 1
    assert coverage["r4"]["coverage_status"] == "excess"
    assert coverage["r4"]["missing_ticket_count"] == -1
    assert coverage["r5"]["coverage_status"] == "unknown"
    assert coverage["r5"]["expected_ticket_count"] is None
    assert coverage["r5"]["observed_ticket_count"] == 1
    assert coverage["r5"]["missing_ticket_count"] is None


def test_calendar_and_partition_manifest_wait_for_monday_boundary():
    at = MONDAY
    sunday_last_second = at + timedelta(days=6, hours=23, minutes=59, seconds=59)
    monday_boundary = at + timedelta(days=7)
    history = _history(
        [
            _event(
                "EV01",
                "partition",
                monday_boundary,
                {
                    "week_start_utc": at.date().isoformat(),
                    "support_tier": "standard",
                    "region": "east",
                    "expected_ticket_count": 0,
                },
            )
        ]
    )

    before_close = summarize_history(history, sunday_last_second)
    assert before_close["coverage"] == []

    at_close = summarize_history(history, monday_boundary)
    assert at_close["coverage"] == [
        {
            "week_start_utc": "2024-01-01",
            "support_tier": "standard",
            "region": "east",
            "expected_ticket_count": 0,
            "observed_ticket_count": 0,
            "missing_ticket_count": 0,
            "coverage_status": "complete",
            "manifest_available_at_utc": "2024-01-08T00:00:00Z",
        }
    ]


def test_partition_week_must_follow_first_week_and_match_event_end():
    at = MONDAY
    cutoff = at + timedelta(days=7)
    incorrect_end = _history(
        [
            _event(
                "EV01",
                "partition",
                at + timedelta(days=6, hours=23, minutes=59, seconds=59),
                {
                    "week_start_utc": at.date().isoformat(),
                    "support_tier": "standard",
                    "region": "east",
                    "expected_ticket_count": 0,
                },
            )
        ]
    )
    with pytest.raises(ValueError, match="following Monday boundary"):
        summarize_history(incorrect_end, cutoff)

    prior_week = at - timedelta(days=7)
    before_first_week = _history(
        [
            _event(
                "EV01",
                "partition",
                at,
                {
                    "week_start_utc": prior_week.date().isoformat(),
                    "support_tier": "standard",
                    "region": "east",
                    "expected_ticket_count": 0,
                },
            )
        ]
    )
    with pytest.raises(ValueError, match="precedes first_week"):
        summarize_history(before_first_week, cutoff)


def test_event_semantic_identity_is_stable_while_priority_can_be_corrected():
    at = MONDAY
    changed_kind = _history(
        [
            _created("T01", at),
            _event(
                "EV01",
                "created",
                at,
                {
                    "ticket_id": "T02",
                    "support_tier": "standard",
                    "region": "east",
                    "priority": 1,
                },
            ),
            _event(
                "EV01",
                "response",
                at + timedelta(minutes=1),
                {"ticket_id": "T02"},
                available_at=at + timedelta(minutes=1),
                revision=2,
            ),
        ]
    )

    with pytest.raises(ValueError, match="changes semantic identity across revisions"):
        summarize_history(changed_kind, at)

    corrected_priority = _history(
        [
            _event(
                "EV01",
                "created",
                at,
                {
                    "ticket_id": "T01",
                    "support_tier": "standard",
                    "region": "east",
                    "priority": 0,
                },
            ),
            _event(
                "EV01",
                "created",
                at,
                {
                    "ticket_id": "T01",
                    "support_tier": "standard",
                    "region": "east",
                    "priority": 1,
                },
                available_at=at + timedelta(seconds=1),
                revision=2,
            ),
        ]
    )
    corrected = summarize_history(corrected_priority, at + timedelta(seconds=1))
    assert corrected["tickets"][0]["priority"] == 1

    changed_ticket = _history(
        [
            _event(
                "EV01",
                "created",
                at,
                {
                    "ticket_id": "T01",
                    "support_tier": "standard",
                    "region": "east",
                    "priority": 1,
                },
            ),
            _event(
                "EV01",
                "created",
                at,
                {
                    "ticket_id": "T02",
                    "support_tier": "standard",
                    "region": "east",
                    "priority": 1,
                },
                available_at=at + timedelta(seconds=1),
                revision=2,
            ),
        ]
    )
    with pytest.raises(ValueError, match="changes semantic identity across revisions"):
        summarize_history(changed_ticket, at)

    changed_partition = _history(
        [
            _event(
                "EV01",
                "partition",
                at + timedelta(days=7),
                {
                    "week_start_utc": at.date().isoformat(),
                    "support_tier": "standard",
                    "region": "east",
                    "expected_ticket_count": 0,
                },
            ),
            _event(
                "EV01",
                "partition",
                at + timedelta(days=14),
                {
                    "week_start_utc": (at + timedelta(days=7)).date().isoformat(),
                    "support_tier": "standard",
                    "region": "east",
                    "expected_ticket_count": 0,
                },
                available_at=at + timedelta(days=14),
                revision=2,
            ),
        ]
    )
    with pytest.raises(ValueError, match="changes semantic identity across revisions"):
        summarize_history(changed_partition, at + timedelta(days=14))


def test_history_rejects_unknown_payload_fields_and_top_level_kind():
    unknown_payload = _history([_created("T01", MONDAY)])
    unknown_payload["events"][0]["payload"]["private_answer"] = "ignore"
    with pytest.raises(ValueError, match="payload fields differ from contract"):
        summarize_history(unknown_payload, MONDAY)

    top_level_kind = _history([_created("T01", MONDAY)])
    top_level_kind["events"][0]["kind"] = top_level_kind["events"][0]["payload"].pop("kind")
    with pytest.raises(ValueError, match="fields differ from contract"):
        summarize_history(top_level_kind, MONDAY)


def test_history_requires_start_at_or_after_first_week_and_nonempty_dimensions():
    history = _history([])
    with pytest.raises(ValueError, match="at or after first_week"):
        summarize_history(history, MONDAY - timedelta(seconds=1))

    empty_clocks = _history([])
    empty_clocks["clock_definitions"] = []
    with pytest.raises(ValueError, match="clock_definitions must not be empty"):
        summarize_history(empty_clocks, MONDAY)

    empty_regions = _history([])
    empty_regions["regions"] = []
    with pytest.raises(ValueError, match="regions must not be empty"):
        summarize_history(empty_regions, MONDAY)


def test_creation_before_first_week_is_rejected_as_unincluded_prehistory():
    before_first_week = _history([_created("T01", MONDAY - timedelta(seconds=1))])

    with pytest.raises(ValueError, match="creation effective_at precedes first_week"):
        summarize_history(before_first_week, MONDAY)


def test_empty_clock_denominator_and_resolved_backlog_group_are_explicit():
    at = MONDAY
    history = _history(
        [
            _created("T01", at),
            _child(
                "resolved-event",
                "resolution",
                "T01",
                at + timedelta(hours=2),
            ),
        ]
    )

    result = summarize_history(history, at + timedelta(hours=3))

    assert result["resolution"][0]["eligible_resolved_tickets"] == 1
    assert result["resolution"][0]["resolution_sla_miss_rate"] == 0.0
    assert result["first_response"][0]["first_response_clock_tickets"] == 0
    assert result["first_response"][0]["first_response_sla_miss_rate"] is None
    assert result["backlog"][0]["open_priority_tickets"] == 0
    assert result["backlog"][0]["overdue_open_priority_tickets"] == 0
    assert result["backlog"][0]["unanswered_tickets"] == 0
    assert result["backlog"][0]["overdue_unanswered_tickets"] == 0


def test_orphans_are_reported_and_child_before_creation_is_rejected():
    at = MONDAY
    orphan_history = _history(
        [
            _child("EV02", "resolution", "T99", at + timedelta(minutes=2)),
            _child("EV01", "response", "T99", at + timedelta(minutes=1)),
        ]
    )
    orphan_result = summarize_history(orphan_history, at + timedelta(minutes=3))
    assert orphan_result["tickets"] == []
    assert orphan_result["orphan_event_ids"] == ["EV01", "EV02"]

    invalid_parent_order = _history(
        [
            _created("T01", at + timedelta(minutes=1)),
            _child("EV01", "response", "T01", at),
        ]
    )
    with pytest.raises(ValueError, match="precedes ticket creation"):
        summarize_history(invalid_parent_order, at + timedelta(minutes=1))


def test_dst_fold_is_normalized_to_utc_before_clock_arithmetic():
    eastern = ZoneInfo("America/Toronto")
    first_0130 = datetime(2024, 11, 3, 1, 30, tzinfo=eastern, fold=0)
    second_0130 = datetime(2024, 11, 3, 1, 30, tzinfo=eastern, fold=1)
    history = _history(
        [
            _created("T01", first_0130),
            _child("EV01", "response", "T01", second_0130),
        ],
        first_week=datetime(2024, 10, 28, tzinfo=UTC),
    )

    result = summarize_history(history, second_0130)

    assert result["as_of_utc"] == "2024-11-03T06:30:00Z"
    assert result["tickets"][0]["created_at_utc"] == "2024-11-03T05:30:00Z"
    assert result["tickets"][0]["first_response_at_utc"] == "2024-11-03T06:30:00Z"
    assert result["first_response"][0]["first_response_sla_misses"] == 0


def test_naive_and_subsecond_times_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        summarize_history(_history([]), datetime(2024, 1, 1))

    subsecond = MONDAY.replace(microsecond=1)
    with pytest.raises(ValueError, match="whole-second precision"):
        summarize_history(_history([]), subsecond)
