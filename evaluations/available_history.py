"""Point-in-time projection for synthetic append-only event revisions.

This small helper answers only which event revisions are visible at one
availability cutoff. It is not entity-state reconstruction, a source adapter,
a business oracle or policy engine, an operational scheduler, or a general
bitemporal database. Callers are responsible for keeping separate source or
company stores separate; this helper does not enforce tenancy.

Records are mappings with ``event_id``, positive integer ``revision``, aware
``effective_at`` and ``available_at`` datetimes, a ``payload`` value, and a
boolean ``tombstone``. For each event, the greatest revision number available
at the cutoff is selected first. Only then are revisions with a future
effective time or a tombstone excluded. Consequently, a correction that moves
an event into the future or a tombstone never causes an older revision to
reappear. Comparisons use UTC instants, including named-zone DST folds; results
preserve the original timestamps, sort by event ID and are deeply copied.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

_REQUIRED_FIELDS = {
    "event_id",
    "revision",
    "effective_at",
    "available_at",
    "payload",
    "tombstone",
}


def _aware_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be an aware datetime")
    try:
        is_aware = value.utcoffset() is not None
    except Exception as exc:
        raise ValueError(f"{field} must be an aware datetime") from exc
    if not is_aware:
        raise ValueError(f"{field} must be an aware datetime")
    return value.astimezone(timezone.utc)


def project_events(
    records: Iterable[Mapping[str, Any]], cutoff: datetime
) -> list[dict[str, Any]]:
    """Return event revisions visible at the single availability ``cutoff``.

    Revision numbers define revision order; ``available_at`` determines which
    revisions are knowable at the cutoff. Duplicate ``(event_id, revision)``
    pairs are rejected even when one copy would not yet be available. Both
    cutoff comparisons are inclusive. Timestamps must be aware ``datetime``
    objects; ISO strings and naive datetimes are intentionally not coerced.
    """
    cutoff = _aware_datetime(cutoff, "cutoff")
    latest_available: dict[str, tuple[Mapping[str, Any], datetime]] = {}
    seen_revisions: set[tuple[str, int]] = set()

    for position, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"record at position {position} must be a mapping")
        missing = _REQUIRED_FIELDS.difference(record)
        if missing:
            raise ValueError(
                f"record at position {position} is missing required fields: "
                f"{', '.join(sorted(missing))}"
            )

        event_id = record["event_id"]
        if not isinstance(event_id, str) or not event_id:
            raise ValueError(f"record at position {position} has an invalid event_id")
        revision = record["revision"]
        if type(revision) is not int or revision <= 0:
            raise ValueError(
                f"record at position {position} revision must be a positive integer"
            )
        effective_at = _aware_datetime(
            record["effective_at"], f"record at position {position} effective_at"
        )
        available_at = _aware_datetime(
            record["available_at"], f"record at position {position} available_at"
        )
        if type(record["tombstone"]) is not bool:
            raise ValueError(f"record at position {position} tombstone must be boolean")

        revision_key = (event_id, revision)
        if revision_key in seen_revisions:
            raise ValueError(
                f"duplicate revision for event_id {event_id!r}: {revision}"
            )
        seen_revisions.add(revision_key)

        if available_at <= cutoff:
            current = latest_available.get(event_id)
            if current is None or revision > current[0]["revision"]:
                latest_available[event_id] = (record, effective_at)

    visible = [
        deepcopy(dict(record))
        for record, effective_at in latest_available.values()
        if effective_at <= cutoff and not record["tombstone"]
    ]
    return sorted(visible, key=lambda record: record["event_id"])
