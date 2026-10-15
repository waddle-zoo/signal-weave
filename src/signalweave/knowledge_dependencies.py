"""Exact reviewed context dependencies, without injecting a knowledge base into inference."""

from __future__ import annotations

from datetime import datetime, timezone

from .knowledge import KnowledgeService
from .models import ContextBinding, PrincipalContext
from .source_identity import namespace_fingerprint


class ContextDependencies:
    def __init__(self, knowledge: KnowledgeService):
        self.knowledge = knowledge

    async def _source_digest(self, entry, principal: PrincipalContext, cache: dict | None = None) -> str:
        identities = []
        for source in entry.content.sources:
            adapter = self.knowledge.sources._get(source.adapter)
            namespace = getattr(adapter, "binding_namespace", None)
            if not isinstance(namespace, str) or not namespace:
                raise ValueError("source connector has no stable binding namespace")
            cache_key = namespace_fingerprint({"source": source.model_dump(mode="json"), "namespace": namespace})
            if cache is not None and cache_key in cache:
                identities.append(cache[cache_key])
                continue
            descriptor = await self.knowledge.sources.authorize(
                source, authorized_tenants=[principal.tenant_id],
            )
            if (descriptor is None or descriptor.adapter != source.adapter
                    or descriptor.resource != source.resource or not descriptor.contract.authorized
                    or descriptor.contract.tenant_id != principal.tenant_id):
                raise ValueError("context source is unavailable")
            # Meaning and scope, not data values, capture times or operational health.
            contract = descriptor.contract.model_dump(mode="json", include={
                "tenant_id", "domain", "scope", "metric_names", "metric_definitions",
                "comparison_contracts", "available_comparison_windows", "required_comparison_keys",
                "population", "grain", "lineage",
            })
            identity = {
                "source": source.model_dump(mode="json"), "namespace": namespace,
                "kind": descriptor.kind, "contract": contract,
            }
            identities.append(identity)
            if cache is not None:
                cache[cache_key] = identity
        return namespace_fingerprint({"sources": identities})

    async def pin(
        self, entry_id: str, revision: int, principal: PrincipalContext, *,
        required_for_action: bool = False, now: datetime | None = None,
    ) -> ContextBinding:
        clock = now or datetime.now(timezone.utc)
        if clock.tzinfo is None or type(revision) is not int or revision < 1:
            raise ValueError("pin requires a positive revision and aware clock")
        current = self.knowledge.store.get(principal.tenant_id, entry_id, principal.principal_id)
        if current.content.reader_principal_ids:
            raise ValueError("tenant-visible cards can bind only tenant-shared context")
        if current.revision != revision or current.status != "reviewed" or current.freshness(clock) != "current":
            raise ValueError("bind the current reviewed revision with a current review date")
        if required_for_action and current.content.kind == "hypothesis":
            raise ValueError("a hypothesis cannot be a required policy prerequisite")
        try:
            digest = await self._source_digest(current, principal)
        except Exception:  # noqa: BLE001 - connector diagnostics can contain private endpoint data
            raise ValueError("context source identity unavailable; check authorization and stable connector namespace") from None
        # Authorization may yield; detect a concurrent edit before creating a pin.
        if self.knowledge.store.get(principal.tenant_id, entry_id, principal.principal_id).revision != revision:
            raise ValueError("context revision changed during binding; review again")
        return ContextBinding(
            entry_id=entry_id, revision=revision,
            content_digest=namespace_fingerprint(current.content.model_dump(mode="json")),
            source_digest=digest, required_for_action=required_for_action,
        )

    async def inspect(
        self, bindings: list[ContextBinding], principal: PrincipalContext, *,
        now: datetime | None = None,
    ) -> dict:
        clock = now or datetime.now(timezone.utc)
        if clock.tzinfo is None or len(bindings) > 12:
            raise ValueError("dependency checks require an aware clock and at most twelve pins")
        states = []
        # Shared definitions often cite the same asset. Reuse metadata only within
        # this principal-scoped check, with parameters and connector identity in the key.
        source_cache: dict = {}
        for pin in bindings:
            status = "unavailable"
            try:
                current = self.knowledge.store.get(principal.tenant_id, pin.entry_id, principal.principal_id)
                pinned = self.knowledge.store.get_revision(
                    principal.tenant_id, pin.entry_id, pin.revision, principal.principal_id,
                )
                # Once private, a formerly shared note is no longer a tenant card dependency.
                if current.content.reader_principal_ids or pinned.content.reader_principal_ids:
                    raise ValueError("context is no longer tenant-shared")
                source_digest = await self._source_digest(pinned, principal, source_cache)
                if (pinned.status != "reviewed"
                        or namespace_fingerprint(pinned.content.model_dump(mode="json")) != pin.content_digest):
                    raise ValueError("invalid reviewed context pin")
                # Recheck after metadata IO to avoid presenting an intervening edit as current.
                current = self.knowledge.store.get(principal.tenant_id, pin.entry_id, principal.principal_id)
                if current.content.reader_principal_ids:
                    raise ValueError("context is no longer tenant-shared")
                if current.revision != pin.revision or current.status != "reviewed":
                    status = "superseded"
                elif source_digest != pin.source_digest:
                    status = "source_changed"
                else:
                    status = current.freshness(clock)
            except Exception:  # noqa: BLE001 - hide private note and source diagnostics
                pass
            states.append({
                "entry_id": pin.entry_id, "revision": pin.revision,
                "required_for_action": pin.required_for_action, "status": status,
            })
        affected = any(item["status"] != "current" for item in states)
        return {
            "entries": states,
            "required_current": all(item["status"] == "current" or not item["required_for_action"] for item in states),
            "all_current": not affected,
            "warnings": ["Review changed context before relying on its meaning; current measurements may still be investigated."] if affected else [],
            "freshness_basis": "Reviewed revision, review deadline and declared source identity/semantics; not data freshness.",
        }
