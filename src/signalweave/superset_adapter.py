from __future__ import annotations

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

    def __init__(self, client: SupersetClient) -> None:
        self.client = client

    async def list_resources(self) -> list[ResourceDescriptor]:
        dashboards = await self.client.list_dashboards()
        return self._descriptors(dashboards)

    async def search_resources(
        self, query: str, *, limit: int, cursor: str | None = None
    ) -> CatalogSearchPage:
        """Use Superset's paginated, permission-filtered dashboard API when available."""
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
            strategy="superset-server-filter",
        )

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
                    tenant_id=str(item.get("tenant_id") or "default"),
                    domain=str(item.get("domain") or "bi"),
                    metric_names=[str(metric) for metric in item.get("metric_names", [])],
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
        resource_type, separator, resource_id = source.resource.partition(":")
        if not separator or not resource_id:
            raise ValueError("Superset resources must use dashboard:<id> or chart:<id>")
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
                    f"Superset chart {chart.title} uses metric definition `{chart.metric}`."
                ),
                values={
                    "metric": chart.metric,
                    "related_chart_ids": chart.related_chart_ids,
                    "description": chart.description,
                    "error": chart.error,
                },
                source_url=dashboard.source_url,
            )
            for chart in dashboard.charts
        ]
        metadata = {
            "provider": "superset",
            "dashboard_id": dashboard.id,
            "owners": dashboard.owners,
            "charts": [
                chart.model_dump(mode="json", exclude={"observations"})
                for chart in dashboard.charts
            ],
            "parameters": source.parameters,
        }
        chart_errors = [
            f"{chart.title}: {chart.error}" for chart in dashboard.charts if chart.error
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
            if dashboard.charts and not charts_with_observations
            else "partial"
            if chart_errors or missing_baseline_chart_ids
            else "healthy"
        )
        metadata["data_quality"] = {
            "status": quality_status,
            "chart_count": len(dashboard.charts),
            "charts_with_observations": len(charts_with_observations),
            "chart_errors": chart_errors,
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
            error=("All Superset charts were unavailable: " + "; ".join(chart_errors))
            if chart_errors and not charts_with_observations
            else None,
            source_url=dashboard.source_url,
            captured_at=dashboard.captured_at,
        )

    async def _inspect_chart(self, source: SourceRef, chart_id: str) -> ResourceSnapshot:
        chart = await self.client.get_chart_metadata(chart_id)
        observations = self.client.observations_from_chart_data(
            chart, await self.client.chart_data(chart)
        )
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
                    statement=f"Superset chart {title} uses metric definition `{metric}`.",
                    values={"metric": metric},
                    source_url=chart.get("url"),
                )
            ],
            metadata={
                "provider": "superset",
                "chart_id": str(chart_id),
                "parameters": source.parameters,
            },
            source_url=chart.get("url"),
        )
