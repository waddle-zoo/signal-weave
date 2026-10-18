"""Controlled raw workload for formative Harbor journeys, never alert labels.

This source-only addition does not select a card, business threshold, recipient
or expected decision. Ordinary, known-open and later-resolved observations are
consecutive states of one development company, not independent companies.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from evaluations.harbor_history import make_history


def make_responded_history(*, seed: int = 20261018) -> dict:
    """Separate synthetic quiet-control background, not a repaired old cohort.

    Every ordinary ticket gets a recorded response within thirty minutes, visible
    by the time its creation arrives. Resolution delays and original ingestion
    gaps still exist. This is a designed control, not representative prevalence
    or a claim that creation manifests attest event completeness.
    """
    history = make_history(seed=seed)
    created = {}
    for row in history["events"]:
        if row["payload"]["kind"] == "created":
            ticket = row["payload"]["ticket_id"]
            if ticket not in created or row["available_at"] < created[ticket]["available_at"]:
                created[ticket] = row
    history["events"] = [row for row in history["events"] if row["payload"]["kind"] != "response"]
    for ticket, row in created.items():
        responded = row["effective_at"] + timedelta(minutes=30)
        history["events"].append({
            "event_id": f"{ticket}:response", "revision": 1, "effective_at": responded,
            "available_at": max(row["available_at"], responded + timedelta(hours=1)),
            "tombstone": False, "payload": {"kind": "response", "ticket_id": ticket},
        })
    return history


def make_queue_history(*, seed: int = 20261018, added_tickets: int = 80,
                       priority: int = 1, recorded_response: bool = True,
                       complete_background_responses: bool = False,
                       resolution_delay_hours: int = 2) -> dict:
    """Add a week-eight enterprise/north cohort that later resolves.

    Added tickets initially have no known resolution. A response, when supplied,
    is recorded within its source clock. Resolution events happen the following Tuesday; their arrival
    delay can model incomplete event knowledge without changing event time.
    Creation manifests include the additional workload on first publication. This
    manifest is not a completeness attestation for responses or resolutions.

    ``priority=0`` is a workload-volume control, not an injected quiet label.
    Private caller-side tests independently compute how any policy applies.
    No source event explains the cause of the extra work or customer impact.
    """
    if type(added_tickets) is not int or not 1 <= added_tickets <= 5_000:
        raise ValueError("added_tickets must be an integer in 1..5000")
    if type(priority) is not int or priority not in (0, 1):
        raise ValueError("priority must be zero or one")
    if type(recorded_response) is not bool:
        raise ValueError("recorded_response must be a boolean")
    if type(complete_background_responses) is not bool:
        raise ValueError("complete_background_responses must be a boolean")
    if type(resolution_delay_hours) is not int or not 0 <= resolution_delay_hours <= 24 * 30:
        raise ValueError("resolution_delay_hours must be an integer in 0..720")
    history = make_responded_history(seed=seed) if complete_background_responses else make_history(seed=seed)
    week = history["first_week"] + timedelta(weeks=7)
    resolved = week + timedelta(days=8, hours=12)
    tier, region = "enterprise", "north"
    identifiers = {row["event_id"] for row in history["events"]}

    def append(event_id, kind, effective, available, payload, *, revision=1):
        history["events"].append({
            "event_id": event_id, "revision": revision, "effective_at": effective,
            "available_at": available, "tombstone": False, "payload": {"kind": kind, **payload},
        })

    for index in range(added_tickets):
        # Same opaque ID shape as ordinary tickets; no scenario/outcome markers.
        token = hashlib.sha256(f"harbor-extra:{seed}:{index}".encode()).hexdigest()[:24]
        ticket = f"t-{token}"
        if any(f"{ticket}:{kind}" in identifiers for kind in ("created", "response", "resolution")):
            raise ValueError("Additional ticket identity collides with source history")
        identifiers.update(f"{ticket}:{kind}" for kind in ("created", "response", "resolution"))
        created = week + timedelta(days=index % 5, hours=8, seconds=index // 5)
        responded = created + timedelta(minutes=30)
        append(f"{ticket}:created", "created", created, created + timedelta(hours=2),
               {"ticket_id": ticket, "support_tier": tier, "region": region, "priority": priority})
        if recorded_response:
            append(f"{ticket}:response", "response", responded, responded + timedelta(hours=1), {"ticket_id": ticket})
        append(f"{ticket}:resolution", "resolution", resolved,
               resolved + timedelta(hours=resolution_delay_hours), {"ticket_id": ticket})

    manifest, = [row for row in history["events"] if row["payload"]["kind"] == "partition"
                 and row["payload"]["week_start_utc"] == week.date().isoformat()
                 and row["payload"]["support_tier"] == tier and row["payload"]["region"] == region]
    # This is a separate authored history, not a late correction to the old
    # cohort: the first published creation manifest already knows the new work.
    manifest["payload"]["expected_ticket_count"] += added_tickets
    return history
