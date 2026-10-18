"""Exercise actual source SQL without allowing SQLite 3.38's unixepoch()."""

import sqlite3
from contextlib import closing

import pytest

from evaluations.harbor_history import _SCHEMA as HISTORY_SCHEMA
from evaluations.harbor_workflow_sources import QUEUE_SQL
from examples.harbor_help.seed import _SCHEMA as EXAMPLE_SCHEMA


def without_unixepoch(action, arg1, arg2, _database, _view):
    # A connection-local authorizer rejects the newer built-in even on a newer
    # host. No replacement function, patched SQLite or library shim is installed.
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or arg1 or "").lower() == "unixepoch":
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


@pytest.mark.parametrize("schema", [EXAMPLE_SCHEMA, HISTORY_SCHEMA], ids=["example", "history"])
def test_actual_sla_views_and_workflow_query_work_without_unixepoch(schema):
    with closing(sqlite3.connect(":memory:")) as db:
        db.row_factory = sqlite3.Row
        db.set_authorizer(without_unixepoch)
        with pytest.raises(sqlite3.DatabaseError, match="unixepoch"):
            db.execute("SELECT unixepoch('2026-01-05T00:00:00Z')")
        db.executescript(schema)
        if schema == HISTORY_SCHEMA:
            db.execute("INSERT INTO regions VALUES('north')")
        db.execute("INSERT INTO support_tier_sla VALUES('enterprise',2,1)")
        db.execute("INSERT INTO source_snapshot VALUES(1,'2026-01-05T04:00:00Z')")
        tickets = [
            ("resolved-equal", "2026-01-05T00:00:00Z", 1, "resolved", "2026-01-05T01:00:00Z", "2026-01-05T02:00:00Z"),
            ("resolved-over", "2026-01-05T00:00:00Z", 1, "resolved", "2026-01-05T02:00:01+01:00", "2026-01-05T03:00:01+01:00"),
            ("open-resolution-equal", "2026-01-05T02:00:00Z", 1, "open", None, None),
            ("open-resolution-over", "2026-01-05T01:59:59Z", 1, "open", None, None),
            ("open-response-equal", "2026-01-05T03:00:00Z", 1, "open", None, None),
            ("open-nonpriority", "2026-01-05T00:00:00Z", 0, "open", None, None),
        ]
        db.executemany("INSERT INTO tickets VALUES(?,?,?,?,?,?,?,?,?)", [
            (identifier, "2026-01-05", created, "enterprise", "north", priority, status, response, resolved)
            for identifier, created, priority, status, response, resolved in tickets
        ])
        resolution = dict(db.execute("SELECT * FROM weekly_resolution_sla").fetchone())
        response = dict(db.execute("SELECT * FROM weekly_first_response_sla").fetchone())
        backlog = dict(db.execute("SELECT * FROM weekly_open_backlog").fetchone())
        assert resolution["eligible_resolved_tickets"] == 2
        assert resolution["resolution_sla_misses"] == 1
        assert resolution["resolution_sla_miss_rate"] == 0.5
        assert response["first_response_clock_tickets"] == 2
        assert response["first_response_sla_misses"] == 1
        assert response["first_response_sla_miss_rate"] == 0.5
        assert backlog["open_priority_tickets"] == 3
        assert backlog["overdue_open_priority_tickets"] == 1
        assert backlog["unanswered_tickets"] == 4
        assert backlog["overdue_unanswered_tickets"] == 3
        assert db.execute("SELECT * FROM weekly_source_coverage").fetchall() == []
        assert dict(db.execute(QUEUE_SQL).fetchone()) == {
            "as_of_utc": "2026-01-05T04:00:00Z", "known_ticket_count": 6,
            "known_open_priority_tickets": 3, "known_unanswered_open_priority_tickets": 3,
            "known_unanswered_open_priority_past_response_clock": 2,
            "known_open_priority_past_resolution_clock": 1,
        }
