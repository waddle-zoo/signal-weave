"""Researcher-prepared company SQL export, identical for both future arms.

This is source preparation, not automatic onboarding or a card decision. It
does not replace companion SQL tools or import owner policy/expected outcomes.
"""

from __future__ import annotations

import hashlib

from evaluations.harbor_history_mcp import ADAPTER
from evaluations.harbor_history_preflight import build_manifest

QUEUE_RESOURCE = "metric:known-priority-queue"
QUEUE_SQL = """SELECT s.as_of_utc,
 COUNT(t.ticket_id) AS known_ticket_count,
 SUM(CASE WHEN t.priority=1 AND t.status='open' THEN 1 ELSE 0 END) AS known_open_priority_tickets,
 SUM(CASE WHEN t.priority=1 AND t.status='open' AND t.first_response_at_utc IS NULL THEN 1 ELSE 0 END) AS known_unanswered_open_priority_tickets,
 SUM(CASE WHEN t.priority=1 AND t.status='open' AND t.first_response_at_utc IS NULL
           AND unixepoch(s.as_of_utc)-unixepoch(t.created_at_utc)>c.first_response_sla_hours*3600
          THEN 1 ELSE 0 END) AS known_unanswered_open_priority_past_response_clock,
 SUM(CASE WHEN t.priority=1 AND t.status='open'
           AND unixepoch(s.as_of_utc)-unixepoch(t.created_at_utc)>c.resolution_sla_hours*3600
          THEN 1 ELSE 0 END) AS known_open_priority_past_resolution_clock
FROM source_snapshot s LEFT JOIN tickets t ON 1=1
LEFT JOIN support_tier_sla c USING(support_tier)
GROUP BY s.as_of_utc"""


def build_workflow_manifest(snapshot, python):
    """Extend the existing fixed read catalog; no executable caller parameters."""
    manifest = build_manifest(snapshot, python)
    digest = hashlib.sha256(QUEUE_SQL.encode()).hexdigest()
    title = "Known priority queue: unanswered response and open resolution clocks"
    scope = ("All known tickets created since the fixture calendar starts, at the exact source cutoff. "
             "Priority=1; open state and recorded response/resolution events only. "
             "No opening backlog or event-completeness guarantee; counts are not proof of customer harm.")
    manifest["connections"][0]["resources"].append({
        "descriptor": {
            "adapter": ADAPTER, "resource": QUEUE_RESOURCE, "kind": "saved_query", "title": title,
            "description": "Source clock counts, not a notification rule. No recipient, incident cause or ticket-detail list.",
            "metadata": {"sql_sha256": digest},
            "contract": {"tenant_id": "local", "authorized": True, "domain": "support",
                         "scope": scope, "lineage": [f"saved-sql-sha256:{digest}"], "freshness_sla_hours": None},
        },
        "source_key": "priority-queue", "tool": "export_query",
        "arguments": {"sql": QUEUE_SQL, "resource": QUEUE_RESOURCE, "source_key": "priority-queue", "title": title},
        "snapshot_pointer": "",
    })
    return manifest
