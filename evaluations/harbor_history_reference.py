"""Independent calculations for the Harbor operational-history fixture."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

_SECONDS_PER_HOUR = 60 * 60
_EVENT_KINDS = {"created", "response", "resolution", "partition"}


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    if value.microsecond:
        raise ValueError(f"{field} must have whole-second precision")
    return value.astimezone(timezone.utc)


def _utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _whole_integer(value: Any, field: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer of at least {minimum}")
    return value


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _elapsed_seconds(start: datetime, end: datetime) -> int:
    elapsed = end - start
    return elapsed.days * 86_400 + elapsed.seconds


def _week_start(value: datetime) -> datetime:
    monday = value.date() - timedelta(days=value.weekday())
    return datetime.combine(monday, time.min, tzinfo=timezone.utc)


def _date_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date string") from exc
    if parsed.isoformat() != value or parsed.weekday() != 0:
        raise ValueError(f"{field} must be a canonical Monday date")
    return value


def _clock_seconds(history: dict[str, Any]) -> dict[str, tuple[int, int]]:
    definitions = history.get("clock_definitions")
    if not isinstance(definitions, list):
        raise ValueError("clock_definitions must be a list")

    result: dict[str, tuple[int, int]] = {}
    for index, definition in enumerate(definitions):
        if not isinstance(definition, dict):
            raise ValueError(f"clock_definitions[{index}] must be a dictionary")
        tier = _name(definition.get("support_tier"), "support_tier")
        if tier in result:
            raise ValueError(f"duplicate clock definition for {tier}")
        resolution_hours = _whole_integer(
            definition.get("resolution_sla_hours"),
            "resolution_sla_hours",
            1,
        )
        response_hours = _whole_integer(
            definition.get("first_response_sla_hours"),
            "first_response_sla_hours",
            1,
        )
        result[tier] = (
            resolution_hours * _SECONDS_PER_HOUR,
            response_hours * _SECONDS_PER_HOUR,
        )
    if not result:
        raise ValueError("clock_definitions must not be empty")
    return result


def _semantic_identity(kind: str, payload: dict[str, Any]) -> tuple[str, ...]:
    fields_by_kind = {
        "created": {"kind", "ticket_id", "support_tier", "region", "priority"},
        "response": {"kind", "ticket_id"},
        "resolution": {"kind", "ticket_id"},
        "partition": {
            "kind",
            "week_start_utc",
            "support_tier",
            "region",
            "expected_ticket_count",
        },
    }
    expected_fields = fields_by_kind[kind]
    if set(payload) != expected_fields:
        missing = sorted(expected_fields - set(payload))
        unknown = sorted(set(payload) - expected_fields)
        raise ValueError(f"payload fields differ from contract (missing={missing}, unknown={unknown})")

    if kind in {"created", "response", "resolution"}:
        ticket_id = _name(payload["ticket_id"], "ticket_id")
        if kind == "created":
            _name(payload["support_tier"], "support_tier")
            _name(payload["region"], "region")
            priority = _whole_integer(payload["priority"], "priority", 0)
            if priority not in (0, 1):
                raise ValueError("priority must be 0 or 1")
        return (kind, ticket_id)

    week_start = _date_text(payload["week_start_utc"], "week_start_utc")
    tier = _name(payload["support_tier"], "support_tier")
    region = _name(payload["region"], "region")
    _whole_integer(payload["expected_ticket_count"], "expected_ticket_count", 0)
    return (kind, week_start, tier, region)


def _latest_visible_events(
    history: dict[str, Any], cutoff: datetime
) -> list[dict[str, Any]]:
    raw_events = history.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("events must be a list")

    revisions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    identities_by_id: dict[str, tuple[str, ...]] = {}
    revisions_by_id: dict[str, set[int]] = defaultdict(set)
    event_fields = {
        "event_id",
        "revision",
        "effective_at",
        "available_at",
        "tombstone",
        "payload",
    }

    for index, raw in enumerate(raw_events):
        if not isinstance(raw, dict):
            raise ValueError(f"events[{index}] must be a dictionary")
        if set(raw) != event_fields:
            raise ValueError(f"events[{index}] fields differ from contract")
        event_id = _name(raw.get("event_id"), "event_id")
        revision = _whole_integer(raw.get("revision"), "revision", 1)
        payload = raw.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dictionary")
        kind = payload.get("kind")
        if kind not in _EVENT_KINDS:
            raise ValueError(f"unsupported payload kind: {kind!r}")
        identity = _semantic_identity(kind, payload)
        effective_at = _utc(raw.get("effective_at"), "effective_at")
        available_at = _utc(raw.get("available_at"), "available_at")
        if available_at < effective_at:
            raise ValueError("available_at cannot precede effective_at")
        tombstone = raw.get("tombstone")
        if not isinstance(tombstone, bool):
            raise ValueError("tombstone must be a boolean")
        prior_identity = identities_by_id.setdefault(event_id, identity)
        if prior_identity != identity:
            raise ValueError(f"event {event_id} changes semantic identity across revisions")
        if revision in revisions_by_id[event_id]:
            raise ValueError(f"event {event_id} has duplicate revision {revision}")
        revisions_by_id[event_id].add(revision)
        revisions[event_id].append(
            {
                "event_id": event_id,
                "revision": revision,
                "kind": kind,
                "effective_at": effective_at,
                "available_at": available_at,
                "tombstone": tombstone,
                "payload": payload,
            }
        )

    visible: list[dict[str, Any]] = []
    for event_versions in revisions.values():
        available_versions = [
            event for event in event_versions if event["available_at"] <= cutoff
        ]
        if not available_versions:
            continue
        latest = max(available_versions, key=lambda event: event["revision"])
        if latest["effective_at"] <= cutoff and not latest["tombstone"]:
            visible.append(latest)
    return visible


def summarize_history(history: dict[str, Any], cutoff: datetime) -> dict[str, Any]:
    """Compute the public Harbor history summary from raw event revisions."""
    if not isinstance(history, dict):
        raise TypeError("history must be a dictionary")

    cutoff_utc = _utc(cutoff, "cutoff")
    first_week = _utc(history.get("first_week"), "first_week")
    if (
        first_week.weekday() != 0
        or first_week.hour != 0
        or first_week.minute != 0
        or first_week.second != 0
    ):
        raise ValueError("first_week must be Monday at 00:00:00 UTC")
    if cutoff_utc < first_week:
        raise ValueError("cutoff must be at or after first_week")

    clock_seconds = _clock_seconds(history)
    raw_regions = history.get("regions")
    if not isinstance(raw_regions, list):
        raise ValueError("regions must be a list")
    regions = [_name(region, "region") for region in raw_regions]
    if len(set(regions)) != len(regions):
        raise ValueError("regions must be distinct")
    if not regions:
        raise ValueError("regions must not be empty")

    visible_events = _latest_visible_events(history, cutoff_utc)
    calendar_weeks: list[datetime] = []
    week = first_week
    while week + timedelta(days=7) <= cutoff_utc:
        calendar_weeks.append(week)
        week += timedelta(days=7)

    calendar_keys = {
        (week_start.date().isoformat(), tier, region)
        for week_start in calendar_weeks
        for tier in clock_seconds
        for region in regions
    }

    creation_events: dict[str, dict[str, Any]] = {}
    child_events: dict[str, dict[str, dict[str, Any]]] = {
        "response": {},
        "resolution": {},
    }
    manifests: dict[tuple[str, str, str], dict[str, Any]] = {}
    seen_children: dict[tuple[str, str], str] = {}

    for event in visible_events:
        payload = event["payload"]
        kind = event["kind"]
        if kind == "partition":
            week_text = _date_text(payload.get("week_start_utc"), "week_start_utc")
            partition_start = datetime.combine(
                date.fromisoformat(week_text), time.min, tzinfo=timezone.utc
            )
            if partition_start < first_week:
                raise ValueError("partition week_start_utc precedes first_week")
            if event["effective_at"] != partition_start + timedelta(days=7):
                raise ValueError("partition effective_at must be the following Monday boundary")
            tier = _name(payload.get("support_tier"), "support_tier")
            region = _name(payload.get("region"), "region")
            if tier not in clock_seconds:
                raise ValueError(f"partition uses unknown support tier: {tier}")
            if region not in regions:
                raise ValueError(f"partition uses unknown region: {region}")
            expected = _whole_integer(
                payload.get("expected_ticket_count"), "expected_ticket_count", 0
            )
            key = (week_text, tier, region)
            if key in manifests:
                raise ValueError(f"multiple visible manifests for partition {key}")
            manifests[key] = {"expected": expected, "event": event}
            continue

        ticket_id = _name(payload.get("ticket_id"), "ticket_id")
        if kind == "created":
            if event["effective_at"] < first_week:
                raise ValueError("creation effective_at precedes first_week")
            tier = _name(payload.get("support_tier"), "support_tier")
            region = _name(payload.get("region"), "region")
            priority = payload.get("priority")
            if tier not in clock_seconds:
                raise ValueError(f"creation uses unknown support tier: {tier}")
            if region not in regions:
                raise ValueError(f"creation uses unknown region: {region}")
            if (
                isinstance(priority, bool)
                or not isinstance(priority, int)
                or priority not in (0, 1)
            ):
                raise ValueError("priority must be 0 or 1")
            if ticket_id in creation_events:
                raise ValueError(f"multiple visible creation events for ticket {ticket_id}")
            creation_events[ticket_id] = event
            continue

        child_key = (kind, ticket_id)
        if child_key in seen_children:
            raise ValueError(
                f"multiple visible {kind} events for ticket {ticket_id}"
            )
        seen_children[child_key] = event["event_id"]
        child_events[kind][ticket_id] = event

    orphan_event_ids: list[str] = []
    for kind, events_by_ticket in child_events.items():
        for ticket_id, event in events_by_ticket.items():
            creation = creation_events.get(ticket_id)
            if creation is None:
                orphan_event_ids.append(event["event_id"])
            elif event["effective_at"] < creation["effective_at"]:
                raise ValueError(
                    f"{kind} event {event['event_id']} precedes ticket creation"
                )

    ticket_rows: list[dict[str, Any]] = []
    facts_by_group: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for ticket_id, creation in creation_events.items():
        payload = creation["payload"]
        created_at = creation["effective_at"]
        tier = payload["support_tier"]
        region = payload["region"]
        week_text = _week_start(created_at).date().isoformat()
        response = child_events["response"].get(ticket_id)
        resolution = child_events["resolution"].get(ticket_id)
        response_at = response["effective_at"] if response else None
        resolved_at = resolution["effective_at"] if resolution else None
        row = {
            "ticket_id": ticket_id,
            "week_start_utc": week_text,
            "created_at_utc": _utc_text(created_at),
            "support_tier": tier,
            "region": region,
            "priority": payload["priority"],
            "status": "resolved" if resolution else "open",
            "first_response_at_utc": _utc_text(response_at),
            "resolved_at_utc": _utc_text(resolved_at),
        }
        ticket_rows.append(row)
        facts_by_group[(week_text, tier, region)].append(
            {
                "row": row,
                "created_at": created_at,
                "response_at": response_at,
                "resolved_at": resolved_at,
            }
        )

    ordered_groups = sorted(facts_by_group)
    resolution_rows: list[dict[str, Any]] = []
    response_rows: list[dict[str, Any]] = []
    backlog_rows: list[dict[str, Any]] = []

    for key in ordered_groups:
        week_text, tier, region = key
        tickets = facts_by_group[key]
        resolution_sla, response_sla = clock_seconds[tier]
        eligible_resolved = [
            ticket
            for ticket in tickets
            if ticket["row"]["priority"] == 1 and ticket["resolved_at"] is not None
        ]
        resolution_misses = sum(
            _elapsed_seconds(ticket["created_at"], ticket["resolved_at"])
            > resolution_sla
            for ticket in eligible_resolved
        )
        responded = [ticket for ticket in tickets if ticket["response_at"] is not None]
        response_misses = sum(
            _elapsed_seconds(ticket["created_at"], ticket["response_at"])
            > response_sla
            for ticket in responded
        )
        open_priority = [
            ticket
            for ticket in tickets
            if ticket["row"]["priority"] == 1 and ticket["resolved_at"] is None
        ]
        unanswered = [
            ticket
            for ticket in tickets
            if ticket["resolved_at"] is None and ticket["response_at"] is None
        ]

        resolution_rows.append(
            {
                "week_start_utc": week_text,
                "support_tier": tier,
                "region": region,
                "observed_ticket_count": len(tickets),
                "eligible_resolved_tickets": len(eligible_resolved),
                "resolution_sla_misses": resolution_misses,
                "resolution_sla_miss_rate": (
                    resolution_misses / len(eligible_resolved)
                    if eligible_resolved
                    else None
                ),
            }
        )
        response_rows.append(
            {
                "week_start_utc": week_text,
                "support_tier": tier,
                "region": region,
                "observed_ticket_count": len(tickets),
                "first_response_clock_tickets": len(responded),
                "first_response_sla_misses": response_misses,
                "first_response_sla_miss_rate": (
                    response_misses / len(responded) if responded else None
                ),
            }
        )
        backlog_rows.append(
            {
                "week_start_utc": week_text,
                "support_tier": tier,
                "region": region,
                "as_of_utc": _utc_text(cutoff_utc),
                "open_priority_tickets": len(open_priority),
                "overdue_open_priority_tickets": sum(
                    _elapsed_seconds(ticket["created_at"], cutoff_utc) > resolution_sla
                    for ticket in open_priority
                ),
                "unanswered_tickets": len(unanswered),
                "overdue_unanswered_tickets": sum(
                    _elapsed_seconds(ticket["created_at"], cutoff_utc) > response_sla
                    for ticket in unanswered
                ),
            }
        )

    coverage_rows: list[dict[str, Any]] = []
    for key in sorted(calendar_keys):
        week_text, tier, region = key
        manifest = manifests.get(key)
        expected = manifest["expected"] if manifest else None
        observed = len(facts_by_group.get(key, []))
        if expected is None:
            missing = None
            status = "unknown"
        else:
            missing = expected - observed
            if observed > expected:
                status = "excess"
            elif observed == expected:
                status = "complete"
            elif observed == 0:
                status = "missing"
            else:
                status = "partial"
        coverage_rows.append(
            {
                "week_start_utc": week_text,
                "support_tier": tier,
                "region": region,
                "expected_ticket_count": expected,
                "observed_ticket_count": observed,
                "missing_ticket_count": missing,
                "coverage_status": status,
                "manifest_available_at_utc": (
                    _utc_text(manifest["event"]["available_at"]) if manifest else None
                ),
            }
        )

    ticket_rows.sort(
        key=lambda row: (
            row["week_start_utc"],
            row["support_tier"],
            row["region"],
            row["ticket_id"],
        )
    )
    return {
        "as_of_utc": _utc_text(cutoff_utc),
        "tickets": ticket_rows,
        "resolution": resolution_rows,
        "first_response": response_rows,
        "backlog": backlog_rows,
        "coverage": coverage_rows,
        "orphan_event_ids": sorted(orphan_event_ids),
    }
