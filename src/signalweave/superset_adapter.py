from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable

from .models import (
    CatalogSearchPage,
    Evidence,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from .superset_client import SupersetClient


class SupersetAdapter:
    """First shipped Superset adapter for saved dashboards and chart data.

    Insight cards can reference several dashboards, or narrow one dashboard with
    ``parameters.chart_ids``. The adapter preserves dashboard owners, chart
    relationships, saved metric definitions, and normalized chart observations
    in the generic snapshot consumed by the insight engine.
    """

    name = "superset"

    def __init__(
        self,
        client: SupersetClient,
        *,
        adapter_name: str = "superset",
        tenant_id: str | None = None,
        provider_name: str | None = None,
        max_search_fallback_terms: int = 18,
    ) -> None:
        if not 1 <= max_search_fallback_terms <= 32:
            raise ValueError("max_search_fallback_terms must be between 1 and 32")
        self.client = client
        self.name = adapter_name
        self.tenant_id = tenant_id
        self.provider_name = provider_name or adapter_name
        self.max_search_fallback_terms = max_search_fallback_terms

    async def list_resources(self) -> list[ResourceDescriptor]:
        dashboards = await self.client.list_dashboards()
        return self._descriptors(dashboards)

    async def search_resources(
        self,
        query: str,
        *,
        limit: int,
        cursor: str | None = None,
        authorized_tenants: Iterable[str] | None = None,
    ) -> CatalogSearchPage:
        """Use Superset search with a bounded natural-language fallback.

        Superset's native dashboard filter treats a natural-language goal as one
        literal substring. That works for an exact title but returns nothing for
        a free-form onboarding request such as "what changed on the executive
        command center?". If the phrase returns no rows, retry a bounded set of
        terms and union the permission-filtered results. Jev still performs the
        semantic ranking; this is recall only.
        """
        if authorized_tenants is not None and self.tenant_id is not None:
            if self.tenant_id not in set(authorized_tenants):
                return CatalogSearchPage(
                    provider=self.name,
                    strategy=f"{self.name}-tenant-denied",
                    total_count=0,
                )
        page = 0
        if cursor:
            try:
                page = int(cursor)
            except ValueError as error:
                raise ValueError("Superset catalog cursors must be numeric pages") from error
        list_page = getattr(self.client, "list_dashboards_page", None)
        if not callable(list_page):
            resources = await self.list_resources()
            return CatalogSearchPage(
                resources=resources,
                total_count=len(resources),
                provider=self.name,
                strategy="local-scan-fallback",
                warnings=[
                    "The configured Superset client does not expose paginated search; "
                    "the full dashboard catalog was materialized."
                ],
            )
        dashboards, count = await list_page(page=page, page_size=limit, query=query)
        strategy = "superset-server-filter"
        warnings: list[str] = []
        if not dashboards and not cursor and len(query.split()) > 1:
            fallback_terms: list[str] = []
            for clause in re.split(r"[\n.;:?!]+", query):
                terms = [
                    term
                    for term in re.findall(r"[a-z0-9]+", clause.lower())
                    if len(term) > 2 or (term.isdigit() and len(term) >= 2)
                ]
                # Titles commonly appear at either end of a free-form clause.
                # Numeric title tokens are often the distinguishing identity in
                # generated or catalog dashboards, so retain them even when
                # they occur in the middle of a longer sentence.
                fallback_terms.extend(
                    terms[:3] + terms[-3:] + [term for term in terms if term.isdigit()]
                )
            # The cap bounds API fan-out for large enterprise catalogs while
            # preserving title terms from each card section.
            fallback_terms = list(dict.fromkeys(fallback_terms))[
                : self.max_search_fallback_terms
            ]
            fallback_results = await asyncio.gather(
                *(
                    list_page(page=0, page_size=limit, query=term)
                    for term in fallback_terms
                )
            )
            seen: set[str] = set()
            for fallback_dashboards, _ in fallback_results:
                for dashboard in fallback_dashboards:
                    key = str(dashboard.get("id"))
                    if key not in seen:
                        seen.add(key)
                        dashboards.append(dashboard)
            if dashboards:
                count = len(dashboards)
                strategy = "superset-server-filter-term-fallback"
                warnings.append(
                    "Superset returned no exact phrase matches; bounded title-term "
                    "fallback expanded candidate recall before Jev ranking; "
                    f"the adapter capped this fallback at {len(fallback_terms)} provider queries."
                )
        resources = self._descriptors(dashboards)
        total_count = count if count is not None else len(resources)
        has_more = (count is not None and (page + 1) * limit < count) or (
            count is None and len(resources) >= limit
        )
        return CatalogSearchPage(
            resources=resources,
            total_count=total_count,
            has_more=has_more,
            next_cursor=str(page + 1) if has_more else None,
            provider=self.name,
            strategy=strategy,
            warnings=warnings,
        )

    async def authorize(
        self,
        source: SourceRef,
        *,
        authorized_tenants: Iterable[str] | None = None,
    ) -> ResourceDescriptor | None:
        """Authorize one dashboard or chart without materializing the catalog.

        A card can contain an explicit resource selected during onboarding.  A
        large Superset workspace must not turn that one-resource check into a
        full dashboard listing, both because that is slow and because the
        provider catalog can be much larger than the card's scope.  The
        provider metadata endpoint is the bounded identity/permission check;
        data inspection remains a separate operation.
        """

        if (
            authorized_tenants is not None
            and self.tenant_id is not None
            and self.tenant_id not in set(authorized_tenants)
        ):
            return None
        resource_type, resource_id = _resource_id(source.resource)
        if resource_type == "dashboard":
            metadata = await self.client.get_dashboard_metadata(resource_id)
            if str(metadata.get("id")) != resource_id:
                return None
            return self._descriptors([metadata])[0]
        if resource_type == "chart":
            metadata = await self.client.get_chart_metadata(resource_id)
            if str(metadata.get("id")) != resource_id:
                return None
            metric_names = metadata.get("metric_names", [])
            return ResourceDescriptor(
                adapter=self.name,
                resource=source.resource,
                kind="chart",
                title=str(metadata.get("slice_name") or "Untitled chart"),
                description=str(metadata.get("description") or ""),
                source_url=metadata.get("url"),
                metadata={"viz_type": self._chart_viz_type(metadata)},
                contract=ResourceContract(
                    tenant_id=str(metadata.get("tenant_id") or self.tenant_id or "default"),
                    domain=str(metadata.get("domain") or "bi"),
                    metric_names=(
                        [str(metric) for metric in metric_names]
                        if isinstance(metric_names, list)
                        else []
                    ),
                    available_comparison_windows=SupersetClient.comparison_windows_from_metadata(
                        metadata
                    ),
                    population=str(metadata.get("population") or ""),
                    grain=str(metadata.get("grain") or ""),
                    lineage=[str(value) for value in metadata.get("lineage", [])]
                    if isinstance(metadata.get("lineage", []), list)
                    else [],
                    roles=[str(value) for value in metadata.get("roles", ["primary"])]
                    if isinstance(metadata.get("roles", ["primary"]), list)
                    else ["primary"],
                    source_status=str(metadata.get("source_status") or "healthy"),
                ),
            )
        raise ValueError("Superset resources must use dashboard:<id> or chart:<id>")

    def _descriptors(self, dashboards: list[dict[str, object]]) -> list[ResourceDescriptor]:
        return [
            ResourceDescriptor(
                adapter=self.name,
                resource=f"dashboard:{item.get('id')}",
                kind="dashboard",
                title=str(item.get("dashboard_title") or "Untitled dashboard"),
                description=str(item.get("description") or ""),
                source_url=item.get("url"),
                metadata={
                    "owners": [
                        str(owner.get("username", owner))
                        if isinstance(owner, dict)
                        else str(owner)
                        for owner in item.get("owners", [])
                    ]
                },
                contract=ResourceContract(
                    tenant_id=str(item.get("tenant_id") or self.tenant_id or "default"),
                    domain=str(item.get("domain") or "bi"),
                    metric_names=[str(metric) for metric in item.get("metric_names", [])],
                    available_comparison_windows=SupersetClient.comparison_windows_from_metadata(
                        item
                    ),
                    population=str(item.get("population") or ""),
                    grain=str(item.get("grain") or ""),
                    freshness_sla_hours=item.get("freshness_sla_hours"),
                    lineage=[str(value) for value in item.get("lineage", [])],
                    roles=[str(value) for value in item.get("roles", ["primary"])],
                    source_status=str(item.get("source_status") or "healthy"),
                ),
            )
            for item in dashboards
        ]

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        resource_type, resource_id = _resource_id(source.resource)
        if resource_type == "dashboard":
            return await self._inspect_dashboard(source, resource_id)
        if resource_type == "chart":
            return await self._inspect_chart(source, resource_id)
        raise ValueError(f"unsupported Superset resource kind: {resource_type}")

    async def _inspect_dashboard(self, source: SourceRef, dashboard_id: str) -> ResourceSnapshot:
        chart_ids = source.parameters.get("chart_ids")
        if chart_ids is not None and (
            not isinstance(chart_ids, list)
            or not all(isinstance(item, str) for item in chart_ids)
        ):
            raise ValueError("Superset dashboard parameters.chart_ids must be a list of strings")
        dashboard = await self.client.dashboard_snapshot(
            dashboard_id,
            include_data=True,
            chart_ids=chart_ids,
        )
        observations = [
            observation.model_copy(update={"source_key": source.key})
            for chart in dashboard.charts
            for observation in chart.observations
        ]
        evidence = [
            Evidence(
                source_key=source.key,
                subject_id=chart.id,
                subject_label=chart.title,
                statement=(
                    f"Superset chart {chart.title} ({chart.viz_type}) exposes "
                    f"{', '.join(chart.metrics or [chart.metric])} as normalized evidence."
                ),
                values={
                    "metric": chart.metric,
                    "metrics": chart.metrics,
                    "viz_type": chart.viz_type,
                    "semantic_status": chart.semantic_status,
                    "semantic_notes": chart.semantic_notes,
                    "data_scope": chart.data_scope,
                    "cache_status": chart.cache_status,
                    "dashboard_filters": chart.dashboard_filters,
                    "related_chart_ids": chart.related_chart_ids,
                    "description": chart.description,
                    "error": chart.error,
                },
                source_url=dashboard.source_url,
            )
            for chart in dashboard.charts
        ]
        metadata = {
            "provider": self.provider_name,
            "dashboard_id": dashboard.id,
            "owners": dashboard.owners,
            "charts": [
                chart.model_dump(mode="json", exclude={"observations"})
                for chart in dashboard.charts
            ],
            "dashboard_scope": dashboard.scope_telemetry,
            "parameters": source.parameters,
        }
        chart_errors = [
            f"{chart.title}: {chart.error}" for chart in dashboard.charts if chart.error
        ]
        semantic_issues = [
            f"{chart.title}: {note}"
            for chart in dashboard.charts
            if chart.semantic_status not in {"extracted", "metadata_only"}
            for note in chart.semantic_notes
        ]
        charts_with_observations = [chart for chart in dashboard.charts if chart.observations]
        missing_baseline_chart_ids = [
            chart.id
            for chart in charts_with_observations
            if any(
                observation.current is not None
                and (observation.baseline is None or observation.change_pct is None)
                for observation in chart.observations
            )
        ]
        quality_status = (
            "failed"
            if dashboard.charts
            and not charts_with_observations
            and all(
                chart.semantic_status in {"unsupported", "no_data"}
                or chart.error
                for chart in dashboard.charts
            )
            else "partial"
            if chart_errors or semantic_issues or missing_baseline_chart_ids
            else "healthy"
        )
        metadata["data_quality"] = {
            "status": quality_status,
            "chart_count": len(dashboard.charts),
            "charts_with_observations": len(charts_with_observations),
            "chart_errors": chart_errors,
            "semantic_issues": semantic_issues,
            "missing_baseline_chart_ids": missing_baseline_chart_ids,
        }
        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=dashboard.title,
            description=dashboard.description,
            observations=observations,
            evidence=evidence,
            metadata=metadata,
            contract=ResourceContract(
                tenant_id=str(self.tenant_id or "default"),
                domain="bi",
                available_comparison_windows=list(dashboard.available_comparison_windows),
                roles=["primary"],
            ),
            error=("All Superset charts were unavailable: " + "; ".join(chart_errors))
            if chart_errors and not charts_with_observations
            else None,
            source_url=dashboard.source_url,
            captured_at=dashboard.captured_at,
        )

    async def _inspect_chart(self, source: SourceRef, chart_id: str) -> ResourceSnapshot:
        chart = await self.client.get_chart_metadata(chart_id)
        if str(chart.get("id")) != str(chart_id):
            raise ValueError(
                "Superset chart response did not match the requested chart ID"
            )
        extraction = self.client.extract_chart_data(chart, await self.client.chart_data(chart))
        observations = extraction.observations
        observations = [
            observation.model_copy(update={"source_key": source.key})
            for observation in observations
        ]
        title = str(chart.get("slice_name") or chart_id)
        metric = observations[0].metric if observations else "unknown"
        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=title,
            description=str(chart.get("description") or ""),
            observations=observations,
            evidence=[
                Evidence(
                    source_key=source.key,
                    subject_id=str(chart_id),
                    subject_label=title,
                    statement=(
                        f"Superset chart {title} ({self._chart_viz_type(chart)}) exposes "
                        f"{', '.join(extraction.metrics or [metric])} as normalized evidence."
                    ),
                    values={
                        "metric": metric,
                        "metrics": extraction.metrics,
                        "viz_type": self._chart_viz_type(chart),
                        "semantic_status": extraction.semantic_status,
                        "semantic_notes": extraction.notes,
                        "result_row_count": extraction.row_count,
                        "result_columns": extraction.columns or [],
                    },
                    source_url=chart.get("url"),
                )
            ],
            metadata={
                "provider": self.provider_name,
                "chart_id": str(chart_id),
                "viz_type": self._chart_viz_type(chart),
                "semantic_status": extraction.semantic_status,
                "semantic_notes": extraction.notes,
                "result_row_count": extraction.row_count,
                "result_columns": extraction.columns or [],
                "parameters": source.parameters,
            },
            contract=ResourceContract(
                tenant_id=str(chart.get("tenant_id") or self.tenant_id or "default"),
                domain=str(chart.get("domain") or "bi"),
                available_comparison_windows=SupersetClient.comparison_windows_from_metadata(
                    chart
                ),
                roles=["primary"],
            ),
            error=(
                "; ".join(extraction.notes)
                if extraction.semantic_status in {"unsupported", "no_data"}
                else None
            ),
            source_url=chart.get("url"),
        )

    @staticmethod
    def _chart_viz_type(chart: dict[str, object]) -> str:
        params = chart.get("params")
        if isinstance(params, str):
            import json

            try:
                params = json.loads(params)
            except json.JSONDecodeError:
                params = {}
        return str(
            chart.get("viz_type")
            or (params.get("viz_type") if isinstance(params, dict) else None)
            or "unknown"
        )


def _resource_id(resource: str) -> tuple[str, str]:
    """Parse a Superset resource without allowing a path/query injection."""

    resource_type, separator, resource_id = resource.partition(":")
    if not separator or not resource_id or any(
        character in resource_id for character in "/?#\x00\r\n"
    ):
        raise ValueError("Superset resources must use dashboard:<id> or chart:<id>")
    if resource_type not in {"dashboard", "chart"}:
        raise ValueError("Superset resources must use dashboard:<id> or chart:<id>")
    return resource_type, resource_id
