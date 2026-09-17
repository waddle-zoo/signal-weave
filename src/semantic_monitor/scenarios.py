from __future__ import annotations

from copy import deepcopy

from .models import ChartSnapshot, DashboardSnapshot, MonitorCard, Observation, Recipient


def _recipient(key: str, label: str) -> Recipient:
    return Recipient(key=key, label=label, destination=f"slack://{key}")


def scenario_catalog() -> dict[str, DashboardSnapshot]:
    """Small, intentionally varied company environments for local simulation."""
    return {
        "revenue_decline": DashboardSnapshot(
            id="dash-revenue",
            title="Revenue Health",
            description="Executive view of revenue quality and growth drivers.",
            owners=["revenue-analytics"],
            charts=[
                ChartSnapshot(
                    id="revenue-total",
                    title="Weekly Revenue",
                    metric="weekly_revenue",
                    observations=[
                        Observation(
                            chart_id="revenue-total",
                            chart_title="Weekly Revenue",
                            metric="weekly_revenue",
                            unit="USD",
                            current=860_000,
                            baseline=1_000_000,
                            previous=980_000,
                            change_pct=-14.0,
                            source_url="superset://chart/revenue-total",
                        )
                    ],
                    related_chart_ids=["enterprise-churn", "pipeline-value", "new-customers"],
                ),
                ChartSnapshot(
                    id="enterprise-churn",
                    title="Enterprise Churn Rate",
                    metric="enterprise_churn_rate",
                    observations=[
                        Observation(
                            chart_id="enterprise-churn",
                            chart_title="Enterprise Churn Rate",
                            metric="enterprise_churn_rate",
                            unit="percentage_points",
                            current=7.8,
                            baseline=2.0,
                            previous=2.2,
                            change_pct=290.0,
                            dimensions={"enterprise": 7.8, "smb": 2.1},
                            source_url="superset://chart/enterprise-churn",
                        )
                    ],
                    related_chart_ids=["revenue-total"],
                ),
                ChartSnapshot(
                    id="pipeline-value",
                    title="Pipeline Value",
                    metric="pipeline_value",
                    observations=[
                        Observation(
                            chart_id="pipeline-value",
                            chart_title="Pipeline Value",
                            metric="pipeline_value",
                            unit="USD",
                            current=2_100_000,
                            baseline=2_050_000,
                            previous=2_080_000,
                            change_pct=2.4,
                            source_url="superset://chart/pipeline-value",
                        )
                    ],
                    related_chart_ids=["revenue-total"],
                ),
                ChartSnapshot(
                    id="new-customers",
                    title="New Customers",
                    metric="new_customers",
                    observations=[
                        Observation(
                            chart_id="new-customers",
                            chart_title="New Customers",
                            metric="new_customers",
                            unit="count",
                            current=112,
                            baseline=119,
                            previous=121,
                            change_pct=-5.9,
                            source_url="superset://chart/new-customers",
                        )
                    ],
                    related_chart_ids=["revenue-total"],
                ),
            ],
        ),
        "seasonal_normal": DashboardSnapshot(
            id="dash-retail",
            title="Retail Weekly Pulse",
            description="Retail sales dashboard with a strong holiday pattern.",
            owners=["retail-ops"],
            charts=[
                ChartSnapshot(
                    id="retail-sales",
                    title="Weekly Sales",
                    metric="weekly_sales",
                    observations=[
                        Observation(
                            chart_id="retail-sales",
                            chart_title="Weekly Sales",
                            metric="weekly_sales",
                            unit="USD",
                            current=410_000,
                            baseline=500_000,
                            previous=505_000,
                            change_pct=-18.0,
                            source_url="superset://chart/retail-sales",
                        )
                    ],
                    related_chart_ids=["retail-orders", "retail-seasonality"],
                ),
                ChartSnapshot(
                    id="retail-orders",
                    title="Orders",
                    metric="orders",
                    observations=[
                        Observation(
                            chart_id="retail-orders",
                            chart_title="Orders",
                            metric="orders",
                            unit="count",
                            current=4_100,
                            baseline=5_000,
                            previous=5_050,
                            change_pct=-18.0,
                            source_url="superset://chart/retail-orders",
                        )
                    ],
                    related_chart_ids=["retail-sales"],
                ),
                ChartSnapshot(
                    id="retail-seasonality",
                    title="Seasonality Index",
                    metric="seasonality_index",
                    observations=[
                        Observation(
                            chart_id="retail-seasonality",
                            chart_title="Seasonality Index",
                            metric="seasonality_index",
                            unit="index",
                            current=0.82,
                            baseline=0.80,
                            previous=0.81,
                            change_pct=2.5,
                            source_url="superset://chart/retail-seasonality",
                        )
                    ],
                    related_chart_ids=["retail-sales", "retail-orders"],
                ),
            ],
        ),
        "mobile_conversion": DashboardSnapshot(
            id="dash-growth",
            title="Growth Funnel",
            description="Acquisition and conversion performance by device.",
            owners=["growth"],
            charts=[
                ChartSnapshot(
                    id="conversion-rate",
                    title="Checkout Conversion",
                    metric="checkout_conversion",
                    observations=[
                        Observation(
                            chart_id="conversion-rate",
                            chart_title="Checkout Conversion",
                            metric="checkout_conversion",
                            unit="percentage_points",
                            current=2.4,
                            baseline=3.5,
                            previous=3.6,
                            change_pct=-31.4,
                            dimensions={"mobile": 1.2, "desktop": 4.9},
                            source_url="superset://chart/conversion-rate",
                        )
                    ],
                    related_chart_ids=["mobile-errors", "traffic"],
                ),
                ChartSnapshot(
                    id="mobile-errors",
                    title="Mobile Checkout Errors",
                    metric="mobile_checkout_errors",
                    observations=[
                        Observation(
                            chart_id="mobile-errors",
                            chart_title="Mobile Checkout Errors",
                            metric="mobile_checkout_errors",
                            unit="count",
                            current=830,
                            baseline=90,
                            previous=84,
                            change_pct=822.2,
                            dimensions={"mobile": 830, "desktop": 14},
                            source_url="superset://chart/mobile-errors",
                        )
                    ],
                    related_chart_ids=["conversion-rate"],
                ),
                ChartSnapshot(
                    id="traffic",
                    title="Traffic",
                    metric="traffic",
                    observations=[
                        Observation(
                            chart_id="traffic",
                            chart_title="Traffic",
                            metric="traffic",
                            unit="count",
                            current=101_000,
                            baseline=100_000,
                            previous=99_000,
                            change_pct=1.0,
                            source_url="superset://chart/traffic",
                        )
                    ],
                    related_chart_ids=["conversion-rate"],
                ),
            ],
        ),
        "data_freshness": DashboardSnapshot(
            id="dash-ops",
            title="Operations Control Tower",
            description="Operational KPIs sourced from the daily warehouse load.",
            owners=["data-platform"],
            charts=[
                ChartSnapshot(
                    id="orders-volume",
                    title="Orders Processed",
                    metric="orders_processed",
                    observations=[
                        Observation(
                            chart_id="orders-volume",
                            chart_title="Orders Processed",
                            metric="orders_processed",
                            unit="count",
                            current=None,
                            baseline=24_000,
                            change_pct=None,
                            freshness="stale: 31h",
                            source_url="superset://chart/orders-volume",
                        )
                    ],
                    related_chart_ids=["load-freshness"],
                ),
                ChartSnapshot(
                    id="load-freshness",
                    title="Warehouse Load Freshness",
                    metric="warehouse_load_freshness",
                    observations=[
                        Observation(
                            chart_id="load-freshness",
                            chart_title="Warehouse Load Freshness",
                            metric="warehouse_load_freshness",
                            unit="hours",
                            current=31,
                            baseline=2,
                            change_pct=1450.0,
                            freshness="stale",
                            source_url="superset://chart/load-freshness",
                        )
                    ],
                    related_chart_ids=["orders-volume"],
                ),
            ],
        ),
    }


def default_cards() -> dict[str, MonitorCard]:
    return {
        "monitor-revenue": MonitorCard(
            id="monitor-revenue",
            dashboard_id="dash-revenue",
            title="Revenue deterioration",
            intent="Alert when revenue quality materially deteriorates. Compare revenue with enterprise churn, pipeline, and new customers. Ignore normal small movements. If enterprise churn explains the movement, notify revenue operations.",
            chart_ids=["revenue-total", "enterprise-churn", "pipeline-value", "new-customers"],
            investigation_hints=[
                "Compare total revenue with enterprise churn.",
                "Check whether pipeline moved with revenue.",
                "Separate enterprise from SMB effects.",
            ],
            materiality_threshold_pct=10.0,
            recipients=[
                _recipient("revenue-operations", "Revenue Operations"),
                _recipient("executive-escalation", "Executive Escalation"),
            ],
        ),
        "monitor-retail": MonitorCard(
            id="monitor-retail",
            dashboard_id="dash-retail",
            title="Retail sales pulse",
            intent="Alert only when retail sales move outside normal seasonal behavior. Use orders and the seasonality index before notifying retail operations.",
            chart_ids=["retail-sales", "retail-orders", "retail-seasonality"],
            investigation_hints=[
                "Check whether orders moved with sales.",
                "Use the seasonality index before escalating.",
            ],
            materiality_threshold_pct=12.0,
            recipients=[_recipient("retail-operations", "Retail Operations")],
        ),
        "monitor-growth": MonitorCard(
            id="monitor-growth",
            dashboard_id="dash-growth",
            title="Checkout conversion regression",
            intent="Notify growth when checkout conversion materially falls and the movement is concentrated in mobile. Inspect mobile checkout errors before routing.",
            chart_ids=["conversion-rate", "mobile-errors", "traffic"],
            investigation_hints=[
                "Compare mobile and desktop conversion.",
                "Check mobile checkout errors.",
                "Confirm traffic is not the explanation.",
            ],
            materiality_threshold_pct=15.0,
            recipients=[
                _recipient("growth", "Growth"),
                _recipient("engineering-oncall", "Engineering On-call"),
            ],
        ),
        "monitor-ops": MonitorCard(
            id="monitor-ops",
            dashboard_id="dash-ops",
            title="Operations data freshness",
            intent="Escalate when operational metrics cannot be trusted because the warehouse load is stale. Do not treat missing data as a normal metric decline.",
            chart_ids=["orders-volume", "load-freshness"],
            investigation_hints=[
                "Check warehouse load freshness before interpreting KPI movement."
            ],
            materiality_threshold_pct=20.0,
            recipients=[_recipient("data-platform", "Data Platform")],
        ),
    }


def copy_dashboard(dashboard: DashboardSnapshot) -> DashboardSnapshot:
    return deepcopy(dashboard)
