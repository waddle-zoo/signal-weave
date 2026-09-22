"""Company bootstrap checks for an installed SignalWeave source boundary.

Bootstrap is intentionally a capability check, not a crawler or an orchestration
layer. A deployment supplies one representative natural-language probe per
adapter. SignalWeave verifies that the adapter can return bounded, authorized
metadata and inspect at least one resource before cards are certified against it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .models import PrincipalContext, ResourceSnapshot, SourceRef
from .sources import SourceRegistry


class BootstrapCapability(StrEnum):
    """Capabilities an enterprise can require from an adapter before use."""

    CATALOG = "catalog"
    SEARCH = "search"
    INSPECT = "inspect"
    TENANT_SCOPE = "tenant_scope"
    FRESHNESS = "freshness"
    LINEAGE = "lineage"
    METRIC_DEFINITIONS = "metric_definitions"


class AdapterBootstrapSpec(BaseModel):
    """Deployment-owned expectations for one installed source adapter."""

    adapter: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    probe_goal: str = Field(
        min_length=1,
        max_length=4000,
        description="A real onboarding goal that should return at least one sample resource.",
    )
    required: bool = True
    required_capabilities: list[BootstrapCapability] = Field(
        default_factory=lambda: [
            BootstrapCapability.CATALOG,
            BootstrapCapability.SEARCH,
            BootstrapCapability.INSPECT,
        ],
        max_length=20,
    )
    minimum_resources: int = Field(default=1, ge=1, le=1_000_000_000)

    @model_validator(mode="after")
    def validate_unique_capabilities(self) -> AdapterBootstrapSpec:
        if len(self.required_capabilities) != len(set(self.required_capabilities)):
            raise ValueError("required_capabilities must be unique")
        return self


class BootstrapManifest(BaseModel):
    """The small, portable contract a company uses to bootstrap SignalWeave."""

    tenant_id: str = Field(min_length=1, max_length=160)
    adapters: list[AdapterBootstrapSpec] = Field(min_length=1, max_length=100)
    name: str = Field(default="SignalWeave deployment", min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_unique_adapters(self) -> BootstrapManifest:
        names = [spec.adapter for spec in self.adapters]
        if len(names) != len(set(names)):
            raise ValueError("bootstrap adapters must be unique")
        return self


class AdapterBootstrapResult(BaseModel):
    """Evidence collected for one adapter during bootstrap."""

    adapter: str
    required: bool
    status: Literal["ready", "needs_review", "blocked"]
    probe_goal: str
    catalog_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    provider: str = "unknown"
    strategy: str = "unknown"
    sample_ref: str | None = None
    inspected_sample: bool = False
    capabilities: dict[str, bool] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list, max_length=50)


class BootstrapReport(BaseModel):
    """Company-level readiness report for source onboarding."""

    tenant_id: str
    manifest_name: str
    status: Literal["ready", "needs_review", "blocked"]
    adapters: list[AdapterBootstrapResult] = Field(default_factory=list, max_length=100)
    blockers: list[str] = Field(default_factory=list, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=200)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BootstrapService:
    """Run bounded, read-only bootstrap checks against a source registry."""

    def __init__(self, registry: SourceRegistry) -> None:
        self.registry = registry

    async def assess(
        self,
        manifest: BootstrapManifest,
        *,
        principal: PrincipalContext | None = None,
    ) -> BootstrapReport:
        tenant_id = principal.tenant_id if principal else manifest.tenant_id
        if tenant_id != manifest.tenant_id:
            raise ValueError(
                "bootstrap manifest tenant_id must match the authenticated principal tenant"
            )

        results: list[AdapterBootstrapResult] = []
        all_blockers: list[str] = []
        all_warnings: list[str] = []
        for spec in manifest.adapters:
            result = await self._assess_adapter(spec, tenant_id=tenant_id)
            results.append(result)
            all_blockers.extend(f"{spec.adapter}: {item}" for item in result.blockers)
            all_warnings.extend(f"{spec.adapter}: {item}" for item in result.warnings)

        if all_blockers:
            status: Literal["ready", "needs_review", "blocked"] = "blocked"
        elif all_warnings:
            status = "needs_review"
        else:
            status = "ready"
        return BootstrapReport(
            tenant_id=tenant_id,
            manifest_name=manifest.name,
            status=status,
            adapters=results,
            blockers=all_blockers,
            warnings=all_warnings,
        )

    async def _assess_adapter(
        self,
        spec: AdapterBootstrapSpec,
        *,
        tenant_id: str,
    ) -> AdapterBootstrapResult:
        if spec.adapter not in self.registry.adapter_names():
            message = "adapter is not installed in the deployment registry"
            return AdapterBootstrapResult(
                adapter=spec.adapter,
                required=spec.required,
                status="blocked" if spec.required else "needs_review",
                probe_goal=spec.probe_goal,
                catalog_count=0,
                returned_count=0,
                blockers=[message] if spec.required else [],
                warnings=[] if spec.required else [message],
            )

        try:
            page = await self.registry.search_resources(
                spec.probe_goal,
                adapter_name=spec.adapter,
                limit=min(max(spec.minimum_resources, 5), 50),
                authorized_tenants=[tenant_id],
            )
        except Exception as error:  # noqa: BLE001 - bootstrap must identify adapter failures
            message = f"authorized catalog probe failed: {type(error).__name__}: {error}"
            return AdapterBootstrapResult(
                adapter=spec.adapter,
                required=spec.required,
                status="blocked" if spec.required else "needs_review",
                probe_goal=spec.probe_goal,
                catalog_count=0,
                returned_count=0,
                blockers=[message] if spec.required else [],
                warnings=[] if spec.required else [message],
            )

        resources = page.resources
        warnings = list(page.warnings)
        blockers: list[str] = []
        if len(resources) < spec.minimum_resources:
            blockers.append(
                f"catalog probe returned {len(resources)} authorized resource(s); "
                f"minimum is {spec.minimum_resources}"
            )
        if not resources:
            blockers.append("probe returned no authorized resources to inspect")

        sample = resources[0] if resources else None
        sample_snapshot: ResourceSnapshot | None = None
        if sample is not None:
            try:
                sample_snapshot = await self.registry.inspect(
                    SourceRef(
                        key=f"bootstrap-{spec.adapter}",
                        adapter=sample.adapter,
                        resource=sample.resource,
                        label=sample.title,
                    ),
                    authorized_tenants=[tenant_id],
                )
            except Exception as error:  # noqa: BLE001 - report the adapter boundary
                warnings.append(
                    f"sample inspection failed: {type(error).__name__}: {error}"
                )

        capabilities = {
            BootstrapCapability.CATALOG.value: len(resources) >= spec.minimum_resources,
            BootstrapCapability.SEARCH.value: (
                bool(resources) and page.strategy not in {"local-scan-fallback", "unknown"}
            ),
            BootstrapCapability.INSPECT.value: bool(
                sample_snapshot is not None and not sample_snapshot.error
            ),
            BootstrapCapability.TENANT_SCOPE.value: bool(resources)
            and all(
                resource.contract.tenant_id == tenant_id and resource.contract.authorized
                for resource in resources
            ),
            BootstrapCapability.FRESHNESS.value: any(
                resource.contract.freshness_sla_hours is not None for resource in resources
            ),
            BootstrapCapability.LINEAGE.value: any(
                bool(resource.contract.lineage)
                or bool(resource.metadata.get("related_resources"))
                or bool(resource.metadata.get("related_refs"))
                for resource in resources
            ),
            BootstrapCapability.METRIC_DEFINITIONS.value: any(
                bool(resource.contract.metric_definitions)
                or bool(resource.contract.metric_names)
                for resource in resources
            ),
        }
        for capability in spec.required_capabilities:
            if capabilities[capability.value]:
                continue
            message = f"required capability is not proven: {capability.value}"
            blockers.append(message)
        if page.strategy == "local-scan-fallback":
            warnings.append(
                "adapter is using local-scan-fallback; install a bounded native catalog "
                "search before claiming large-catalog readiness"
            )
        if page.has_more:
            warnings.append("catalog probe was paginated; complete coverage is not represented by this page")

        if not spec.required and blockers:
            warnings.extend(blockers)
            blockers = []
        status: Literal["ready", "needs_review", "blocked"]
        if blockers:
            status = "blocked"
        elif warnings:
            status = "needs_review"
        else:
            status = "ready"
        return AdapterBootstrapResult(
            adapter=spec.adapter,
            required=spec.required,
            status=status,
            probe_goal=spec.probe_goal,
            catalog_count=page.total_count,
            returned_count=len(resources),
            provider=page.provider,
            strategy=page.strategy,
            sample_ref=(f"{sample.adapter}|{sample.resource}" if sample else None),
            inspected_sample=bool(sample_snapshot is not None and not sample_snapshot.error),
            capabilities=capabilities,
            blockers=blockers,
            warnings=warnings,
        )
