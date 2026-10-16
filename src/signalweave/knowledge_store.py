"""Tenant-scoped, append-only SQLite storage for reviewed business context."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .knowledge_models import KnowledgeEntry

_MAX_HISTORY = 50
_MAX_SEARCH = 100
_MAX_SOURCE_REFS = 100


class SQLiteKnowledgeStore:
    """Durable knowledge revisions with bounded FTS5 and exact-anchor retrieval."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS knowledge_revisions ("
                "tenant_id TEXT NOT NULL, entry_id TEXT NOT NULL, revision INTEGER NOT NULL, "
                "payload TEXT NOT NULL, domain TEXT NOT NULL, title TEXT NOT NULL, "
                "status TEXT NOT NULL, "
                "PRIMARY KEY (tenant_id, entry_id, revision))"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS knowledge_revisions_lookup "
                "ON knowledge_revisions (tenant_id, entry_id, revision)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS knowledge_current ("
                "rowid INTEGER PRIMARY KEY, tenant_id TEXT NOT NULL, entry_id TEXT NOT NULL, "
                "revision INTEGER NOT NULL, domain TEXT NOT NULL, status TEXT NOT NULL, "
                "review_after_jd REAL NOT NULL, UNIQUE (tenant_id, entry_id))"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS knowledge_current_tenant "
                "ON knowledge_current (tenant_id, entry_id, revision)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS knowledge_current_due "
                "ON knowledge_current (tenant_id, review_after_jd, entry_id) "
                "WHERE status != 'retired'"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS knowledge_current_domain_due "
                "ON knowledge_current (tenant_id, domain, review_after_jd, entry_id) "
                "WHERE status != 'retired'"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS knowledge_revision_readers ("
                "tenant_id TEXT NOT NULL, entry_id TEXT NOT NULL, revision INTEGER NOT NULL, "
                "principal_id TEXT NOT NULL, "
                "PRIMARY KEY (tenant_id, entry_id, revision, principal_id))"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS knowledge_readers_principal "
                "ON knowledge_revision_readers (tenant_id, principal_id, entry_id, revision)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS knowledge_current_anchors ("
                "tenant_id TEXT NOT NULL, entry_id TEXT NOT NULL, anchor TEXT NOT NULL, "
                "PRIMARY KEY (tenant_id, entry_id, anchor))"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS knowledge_anchor_lookup "
                "ON knowledge_current_anchors (tenant_id, anchor, entry_id)"
            )
            connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5("
                "tenant_id UNINDEXED, entry_id UNINDEXED, title, body, domain, "
                "tokenize='unicode61')"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.row_factory = sqlite3.Row
        return connection

    def get(self, tenant_id: str, entry_id: str, principal_id: str) -> KnowledgeEntry:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT e.payload FROM knowledge_current c "
                "JOIN knowledge_revisions e ON e.tenant_id = c.tenant_id "
                "AND e.entry_id = c.entry_id AND e.revision = c.revision "
                "WHERE c.tenant_id = ? AND c.entry_id = ? AND "
                + self._visible_sql("c"),
                (tenant_id, entry_id, principal_id),
            ).fetchone()
        if row is None:
            raise KeyError("knowledge entry not found")
        return KnowledgeEntry.model_validate_json(row["payload"])

    def get_revision(
        self, tenant_id: str, entry_id: str, revision: int, principal_id: str
    ) -> KnowledgeEntry:
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError("revision must be an integer greater than or equal to 1")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT e.payload FROM knowledge_current c "
                "JOIN knowledge_revisions e ON e.tenant_id = c.tenant_id "
                "AND e.entry_id = c.entry_id AND e.revision = ? "
                "WHERE c.tenant_id = ? AND c.entry_id = ? AND "
                + self._visible_sql("c")
                + " AND "
                + self._visible_sql("e"),
                (revision, tenant_id, entry_id, principal_id, principal_id),
            ).fetchone()
        if row is None:
            raise KeyError("knowledge entry not found")
        return KnowledgeEntry.model_validate_json(row["payload"])

    def append(self, entry: KnowledgeEntry, expected_revision: int) -> KnowledgeEntry:
        """Append the next revision iff the tenant-scoped revision still matches."""
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            raise ValueError("expected_revision must be non-negative")

        payload = entry.model_dump_json()
        sources = [f"{source.adapter}|{source.resource}" for source in entry.content.sources]
        readers = sorted(set(entry.content.reader_principal_ids))

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = connection.execute(
                    "SELECT c.rowid, c.revision FROM knowledge_current c "
                    "WHERE c.tenant_id = ? AND c.entry_id = ?",
                    (entry.tenant_id, entry.id),
                ).fetchone()
                current_revision = current["revision"] if current else 0

                # An existing private entry cannot be replaced by an actor who
                # cannot see its current revision. Keep this indistinguishable
                # from an absent ID, even when the supplied CAS value is stale.
                if current is not None and not self._is_visible(
                    connection, entry.tenant_id, entry.id, current_revision, entry.actor
                ):
                    raise KeyError("knowledge entry not found")
                if current_revision != expected_revision:
                    raise ValueError("knowledge revision conflict")
                if entry.revision != expected_revision + 1:
                    raise ValueError("entry revision must follow expected_revision")
                if current is not None:
                    current_payload = connection.execute(
                        "SELECT payload FROM knowledge_revisions "
                        "WHERE tenant_id = ? AND entry_id = ? AND revision = ?",
                        (entry.tenant_id, entry.id, current_revision),
                    ).fetchone()["payload"]
                    current_entry = KnowledgeEntry.model_validate_json(current_payload)
                    if entry.owner_id != current_entry.owner_id:
                        raise ValueError("knowledge owner_id is immutable")
                review_after_jd = connection.execute(
                    "SELECT julianday(?)", (entry.content.review_after.isoformat(),)
                ).fetchone()[0]

                connection.execute(
                    "INSERT INTO knowledge_revisions "
                    "(tenant_id, entry_id, revision, payload, domain, title, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        entry.tenant_id,
                        entry.id,
                        entry.revision,
                        payload,
                        entry.content.domain,
                        entry.content.title,
                        entry.status,
                    ),
                )
                connection.executemany(
                    "INSERT INTO knowledge_revision_readers "
                    "(tenant_id, entry_id, revision, principal_id) VALUES (?, ?, ?, ?)",
                    [
                        (entry.tenant_id, entry.id, entry.revision, reader)
                        for reader in readers
                    ],
                )

                if current is None:
                    connection.execute(
                        "INSERT INTO knowledge_current "
                        "(tenant_id, entry_id, revision, domain, status, review_after_jd) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            entry.tenant_id,
                            entry.id,
                            entry.revision,
                            entry.content.domain,
                            entry.status,
                            review_after_jd,
                        ),
                    )
                else:
                    connection.execute(
                        "UPDATE knowledge_current SET revision = ?, domain = ?, status = ?, "
                        "review_after_jd = ? WHERE rowid = ?",
                        (
                            entry.revision,
                            entry.content.domain,
                            entry.status,
                            review_after_jd,
                            current["rowid"],
                        ),
                    )
                    connection.execute(
                        "DELETE FROM knowledge_fts WHERE rowid = ?", (current["rowid"],)
                    )
                    connection.execute(
                        "DELETE FROM knowledge_current_anchors "
                        "WHERE tenant_id = ? AND entry_id = ?",
                        (entry.tenant_id, entry.id),
                    )

                current_row = connection.execute(
                    "SELECT rowid FROM knowledge_current WHERE tenant_id = ? AND entry_id = ?",
                    (entry.tenant_id, entry.id),
                ).fetchone()
                rowid = current_row["rowid"]
                if entry.status != "retired":
                    connection.execute(
                        "INSERT INTO knowledge_fts "
                        "(rowid, tenant_id, entry_id, title, body, domain) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            rowid,
                            entry.tenant_id,
                            entry.id,
                            entry.content.title,
                            entry.content.body,
                            entry.content.domain,
                        ),
                    )
                    connection.executemany(
                        "INSERT INTO knowledge_current_anchors (tenant_id, entry_id, anchor) "
                        "VALUES (?, ?, ?)",
                        [(entry.tenant_id, entry.id, anchor) for anchor in sources],
                    )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

        return entry

    def history(
        self,
        tenant_id: str,
        entry_id: str,
        principal_id: str,
        limit: int = _MAX_HISTORY,
    ) -> list[KnowledgeEntry]:
        self._validate_limit(limit, _MAX_HISTORY, "history")
        current_visible = self._visible_sql("c")
        historical_visible = self._visible_sql("e")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT e.payload FROM knowledge_current c "
                "JOIN knowledge_revisions e ON e.tenant_id = c.tenant_id "
                "AND e.entry_id = c.entry_id "
                "WHERE c.tenant_id = ? AND c.entry_id = ? AND "
                + current_visible
                + " AND "
                + historical_visible
                + " ORDER BY e.revision DESC LIMIT ?",
                (
                    tenant_id,
                    entry_id,
                    principal_id,
                    principal_id,
                    limit,
                ),
            ).fetchall()
        if not rows:
            # Current visibility is deliberately indistinguishable from absence.
            try:
                self.get(tenant_id, entry_id, principal_id)
            except KeyError:
                raise KeyError("knowledge entry not found") from None
        entries = [KnowledgeEntry.model_validate_json(row["payload"]) for row in rows]
        return list(reversed(entries))

    def search(
        self,
        tenant_id: str,
        principal_id: str,
        query: str,
        domain: str | None = None,
        source_refs: list[str] | None = None,
        limit: int = _MAX_SEARCH,
        review_due_before: datetime | None = None,
        include_drafts: bool = True,
        offset: int = 0,
        entry_ids: list[str] | None = None,
    ) -> list[KnowledgeEntry]:
        self._validate_limit(limit, _MAX_SEARCH, "search")
        if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= 300:
            raise ValueError("search offset must be between 0 and 300")
        if not isinstance(query, str):
            raise ValueError("query must be text")
        if len(query.encode("utf-8")) > 2000:
            raise ValueError("query must be at most 2000 UTF-8 bytes")
        if not isinstance(include_drafts, bool):
            raise ValueError("include_drafts must be boolean")
        if entry_ids is not None and (
            not isinstance(entry_ids, list) or not 1 <= len(entry_ids) <= 12
            or any(not isinstance(value, str) or not value.strip() or len(value) > 160 for value in entry_ids)
            or len(set(entry_ids)) != len(entry_ids)
        ):
            raise ValueError("entry_ids must contain one to twelve distinct nonempty IDs of at most 160 characters")
        anchors = source_refs or []
        if len(anchors) > _MAX_SOURCE_REFS:
            raise ValueError(f"source_refs may contain at most {_MAX_SOURCE_REFS} anchors")
        if any(not isinstance(anchor, str) for anchor in anchors):
            raise ValueError("source_refs must contain exact adapter|resource strings")
        if review_due_before is not None:
            if review_due_before.tzinfo is None or review_due_before.utcoffset() is None:
                raise ValueError("review_due_before must be timezone-aware")
            due_cutoff = review_due_before.astimezone(timezone.utc).isoformat()
        else:
            due_cutoff = None

        tokens_by_casefold: dict[str, str] = {}
        for token in re.findall(r"[^\W_]+", query, flags=re.UNICODE):
            tokens_by_casefold.setdefault(token.casefold(), token)
        tokens = list(tokens_by_casefold.values())
        if len(tokens) > 64:
            raise ValueError("query may contain at most 64 distinct search tokens")
        # Quote every token so FTS operators and punctuation supplied by a caller
        # remain literal text, never executable MATCH syntax.
        match_query = " AND ".join(f'"{token}"' for token in tokens)
        if query.strip() and not match_query and not anchors:
            return []

        cte_parts: list[str] = []
        params: list[object] = []
        if match_query:
            cte_parts.append(
                "SELECT rowid, 0.0 AS score FROM knowledge_fts "
                "WHERE knowledge_fts MATCH ? AND tenant_id = ?"
            )
            params.extend((match_query, tenant_id))
        if anchors:
            placeholders = ", ".join("?" for _ in anchors)
            cte_parts.append(
                "SELECT c.rowid, -1.0 AS score FROM knowledge_current c "
                "JOIN knowledge_current_anchors a ON a.tenant_id = c.tenant_id "
                "AND a.entry_id = c.entry_id "
                f"WHERE c.tenant_id = ? AND a.anchor IN ({placeholders})"
            )
            params.extend((tenant_id, *anchors))

        if cte_parts:
            candidates = (
                "WITH raw_candidates AS ("
                + " UNION ALL ".join(cte_parts)
                + "), candidates AS (SELECT rowid, MIN(score) AS score "
                "FROM raw_candidates GROUP BY rowid) "
            )
            candidate_join = "JOIN candidates x ON x.rowid = c.rowid"
            order_by = "x.score, c.entry_id"
        elif query.strip():
            # Punctuation-only text is not an invitation to browse the catalog.
            return []
        else:
            candidates = ""
            candidate_join = ""
            order_by = "c.review_after_jd, c.entry_id"

        sql = (
            candidates
            + "SELECT e.payload FROM knowledge_current c "
            + (f" {candidate_join} " if candidate_join else " ")
            + "JOIN knowledge_revisions e ON e.tenant_id = c.tenant_id "
            "AND e.entry_id = c.entry_id AND e.revision = c.revision "
            "WHERE c.tenant_id = ? AND c.status != 'retired' AND "
            + self._visible_sql("c")
        )
        params.extend((tenant_id, principal_id))
        if entry_ids is not None:
            placeholders = ", ".join("?" for _ in entry_ids)
            sql += f" AND c.entry_id IN ({placeholders})"
            params.extend(entry_ids)
        if not include_drafts:
            sql += " AND c.status != 'draft'"
        # Keep optional filtering in SQL so hidden, retired, or not-yet-due rows
        # cannot consume the bounded candidate window.
        if domain is not None:
            sql += " AND e.domain = ?"
            params.append(domain)
        if due_cutoff is not None:
            sql += (
                " AND c.review_after_jd <= julianday(?) "
                "AND julianday(json_extract(e.payload, '$.content.review_after')) <= julianday(?)"
            )
            params.extend((due_cutoff, due_cutoff))
        sql += f" ORDER BY {order_by} LIMIT ?"
        params.append(limit)
        sql += " OFFSET ?"
        params.append(offset)

        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [KnowledgeEntry.model_validate_json(row["payload"]) for row in rows]

    @staticmethod
    def _validate_limit(limit: int, maximum: int, label: str) -> None:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= maximum:
            raise ValueError(f"{label} limit must be between 1 and {maximum}")

    @staticmethod
    def _visible_sql(alias: str) -> str:
        return (
            "(NOT EXISTS (SELECT 1 FROM knowledge_revision_readers r "
            f"WHERE r.tenant_id = {alias}.tenant_id AND r.entry_id = {alias}.entry_id "
            f"AND r.revision = {alias}.revision) OR EXISTS ("
            "SELECT 1 FROM knowledge_revision_readers r "
            f"WHERE r.tenant_id = {alias}.tenant_id AND r.entry_id = {alias}.entry_id "
            f"AND r.revision = {alias}.revision AND r.principal_id = ?))"
        )

    @staticmethod
    def _is_visible(
        connection: sqlite3.Connection,
        tenant_id: str,
        entry_id: str,
        revision: int,
        principal_id: str,
    ) -> bool:
        rows = connection.execute(
            "SELECT principal_id FROM knowledge_revision_readers "
            "WHERE tenant_id = ? AND entry_id = ? AND revision = ?",
            (tenant_id, entry_id, revision),
        ).fetchall()
        return not rows or any(row["principal_id"] == principal_id for row in rows)
