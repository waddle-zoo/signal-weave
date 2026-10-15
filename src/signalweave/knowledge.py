"""Bounded, attributed context retrieval; no analysis, scheduler, or delivery loop."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from .knowledge_models import KnowledgeContent, KnowledgeEntry, KnowledgePacket
from .knowledge_store import SQLiteKnowledgeStore
from .models import PrincipalContext
from .sources import SourceRegistry


class KnowledgeService:
    def __init__(self, store: SQLiteKnowledgeStore, sources: SourceRegistry):
        self.store = store
        self.sources = sources

    async def _authorized(
        self, content: KnowledgeContent, principal: PrincipalContext,
        cache: dict[str, bool] | None = None,
    ) -> bool:
        for source in content.sources:
            canonical = json.dumps(source.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            key = hashlib.sha256(canonical.encode()).hexdigest()
            if cache is not None and key in cache:
                if not cache[key]:
                    return False
                continue
            if cache is not None and len(cache) >= 60:
                return False
            try:
                descriptor = await self.sources.authorize(
                    source, authorized_tenants=[principal.tenant_id],
                )
            except Exception:  # noqa: BLE001 - never expose private source diagnostics
                if cache is not None:
                    cache[key] = False
                return False
            allowed = not (
                descriptor is None
                or descriptor.adapter != source.adapter
                or descriptor.resource != source.resource
                or not descriptor.contract.authorized
                or descriptor.contract.tenant_id != principal.tenant_id
            )
            if cache is not None:
                cache[key] = allowed
            if not allowed:
                return False
        return True

    async def save(
        self, content: KnowledgeContent, principal: PrincipalContext, *,
        entry_id: str | None = None, expected_revision: int = 0,
        confirm_visibility_change: bool = False,
    ) -> KnowledgeEntry:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must not be negative")
        owner_id = principal.principal_id
        if entry_id:
            # Check current visibility, not an actor supplied by the caller.
            current = self.store.get(principal.tenant_id, entry_id, principal.principal_id)
            owner_id = current.owner_id
            if owner_id != principal.principal_id:
                raise ValueError("only the context owner may edit or change visibility")
            if set(content.reader_principal_ids) != set(current.content.reader_principal_ids) and not confirm_visibility_change:
                raise ValueError("visibility changes require explicit confirmation")
        elif expected_revision:
            raise ValueError("a new entry requires expected_revision=0")
        readers = content.reader_principal_ids
        if readers and principal.principal_id not in readers:
            raise ValueError("a private entry must remain visible to its author")
        if not await self._authorized(content, principal):
            raise ValueError("context sources are not available in the current authorized scope")
        entry = KnowledgeEntry(
            id=entry_id or uuid4().hex,
            tenant_id=principal.tenant_id,
            revision=expected_revision + 1,
            content=content,
            actor=principal.principal_id,
            owner_id=owner_id,
        )
        self.store.append(entry, expected_revision=expected_revision)
        return entry

    async def review(
        self, entry_id: str, expected_revision: int, principal: PrincipalContext, *,
        action: str, reason: str,
    ) -> KnowledgeEntry:
        if action not in {"approve", "retire"} or not reason.strip() or len(reason) > 2000:
            raise ValueError("review requires approve/retire and a bounded nonempty reason")
        current = self.store.get(principal.tenant_id, entry_id, principal.principal_id)
        if current.owner_id != principal.principal_id and "knowledge:review" not in principal.scopes:
            raise ValueError("context review requires its owner or an authorized reviewer")
        if current.revision != expected_revision:
            raise ValueError("knowledge revision changed; retrieve and review the current revision")
        if not await self._authorized(current.content, principal):
            raise ValueError("context sources are not available in the current authorized scope")
        if action == "approve":
            if current.content.review_after <= datetime.now(timezone.utc):
                raise ValueError("set a future review date in a new draft before approving")
        updated = current.model_copy(update={
            "revision": current.revision + 1,
            "status": "reviewed" if action == "approve" else "retired",
            "actor": principal.principal_id,
            "reason": reason,
            "created_at": datetime.now(timezone.utc),
        })
        self.store.append(updated, expected_revision=expected_revision)
        return updated

    async def retrieve(
        self, principal: PrincipalContext, *, query: str = "", domain: str | None = None,
        source_refs: list[str] | None = None, include_drafts: bool = False,
        review_due_only: bool = False, limit: int = 10, max_bytes: int = 24_000,
        now: datetime | None = None,
    ) -> KnowledgePacket:
        if (
            len(query) > 2000 or type(limit) is not int or not 1 <= limit <= 30
            or type(max_bytes) is not int or not 4096 <= max_bytes <= 64_000
        ):
            raise ValueError("context query, result count or byte budget is outside its bounds")
        if domain is not None and (not domain.strip() or len(domain) > 160):
            raise ValueError("domain must be a bounded nonempty name")
        anchors = source_refs or []
        if len(anchors) > 12 or any(
            "|" not in value or len(value) > 600
            or not all(part.strip() for part in value.split("|", 1)) for value in anchors
        ):
            raise ValueError("provide at most twelve exact adapter|resource source anchors")
        captured_at = now or datetime.now(timezone.utc)
        if captured_at.tzinfo is None:
            raise ValueError("context retrieval requires an aware clock")
        candidates = []
        for offset in (0, 100, 200):
            page = self.store.search(
                principal.tenant_id, principal.principal_id, query=query, domain=domain,
                source_refs=anchors, limit=100, offset=offset,
                review_due_before=captured_at if review_due_only else None, include_drafts=include_drafts,
            )
            candidates.extend(page)
            if len(page) < 100:
                break
        entries, freshness = [], {}
        authorization_cache: dict[str, bool] = {}
        warnings = []
        truncated = False
        for entry in candidates:
            if entry.status == "draft" and not include_drafts:
                continue
            if review_due_only and entry.content.review_after > captured_at:
                continue
            if not await self._authorized(entry.content, principal, authorization_cache):
                # Do not disclose whether a hidden/stale link or an outage caused exclusion.
                continue
            if len(entries) == limit:
                truncated = True
                break
            proposed = [*entries, entry]
            proposed_freshness = {**freshness, entry.id: entry.freshness(captured_at)}
            if len(json.dumps({"entries": [x.model_dump(mode="json") for x in proposed],
                               "freshness": proposed_freshness}, ensure_ascii=False).encode()) > max_bytes - 2000:
                truncated = True
                continue
            entries, freshness = proposed, proposed_freshness
        warnings.append("Context coverage is bounded and source-filtered; an empty packet does not establish absence.")
        if truncated:
            warnings.append("Bounded context packet; refine the task, domain or source anchors for further coverage.")
        if any(value != "current" for value in freshness.values()):
            warnings.append("Some context is not current; confirm its meaning before relying on it.")
        if any(entry.status == "draft" or entry.content.kind == "hypothesis" for entry in entries):
            warnings.append("Drafts and hypotheses are attributed working context, not established facts.")
        identity = json.dumps({"entries": [x.model_dump(mode="json") for x in entries],
                               "freshness": freshness}, sort_keys=True, ensure_ascii=False)
        return KnowledgePacket(
            entries=entries, freshness=freshness,
            packet_id=hashlib.sha256(identity.encode()).hexdigest(), captured_at=captured_at,
            truncated=truncated, warnings=warnings,
        )

    async def history(self, entry_id: str, principal: PrincipalContext, limit: int = 20) -> list[KnowledgeEntry]:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("history limit must be between 1 and 50")
        records = self.store.history(principal.tenant_id, entry_id, principal.principal_id, limit=limit)
        visible, size = [], 0
        cache: dict[str, bool] = {}
        for entry in records:
            if await self._authorized(entry.content, principal, cache):
                size += len(entry.model_dump_json().encode())
                if size > 24_000:
                    break
                visible.append(entry)
        return visible
