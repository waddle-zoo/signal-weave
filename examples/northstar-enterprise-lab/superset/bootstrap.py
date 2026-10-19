#!/usr/bin/env python3
"""Seed the local Superset instance through its supported REST API."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any
from urllib.parse import quote_plus

import requests

BASE = os.environ.get("SUPERSET_BASE_URL", "http://superset:8088").rstrip("/")
USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
PASSWORD = os.environ["ADMIN_PASSWORD"]
SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json", "Content-Type": "application/json", "Referer": BASE})


DATASETS = [
    ("gold", "mart_executive_daily"),
    ("gold", "mart_store_performance"),
    ("gold", "mart_customer_value"),
    ("gold", "mart_marketing_efficiency"),
    ("gold", "mart_supply_chain"),
    ("gold", "mart_finance_daily"),
    ("gold", "mart_support_ops"),
    ("gold", "mart_digital_funnel"),
    ("gold", "mart_delivery_performance"),
    ("gold", "mart_workforce_productivity"),
    ("gold", "data_quality_checks"),
    ("silver", "dim_store"),
    ("silver", "dim_product"),
    ("silver", "dim_customer"),
    ("silver", "dim_supplier"),
    ("silver", "fct_sales_order_line"),
    ("silver", "fct_inventory_snapshot"),
    ("silver", "fct_purchase_order_line"),
    ("silver", "fct_web_session"),
    ("silver", "fct_marketing_daily"),
    ("silver", "fct_support_ticket"),
    ("silver", "fct_delivery"),
    ("silver", "fct_employee_shift"),
    ("silver", "fct_finance_daily"),
]


def api(method: str, path: str, *, _allow_auth_retry: bool = True, **kwargs: Any) -> dict[str, Any]:
    url = f"{BASE}{path}"
    last = None
    auth_retried = False
    for attempt in range(6):
        response = SESSION.request(method, url, timeout=120, **kwargs)
        if (
            response.status_code == 401
            and _allow_auth_retry
            and not auth_retried
            and path != "/api/v1/security/login"
        ):
            auth_retried = True
            login()
            continue
        if response.status_code < 500:
            if response.status_code >= 400:
                raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text[:800]}")
            if not response.content:
                return {}
            return response.json()
        last = response.text[:500]
        time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"{method} {path} failed after retries: {last}")


def list_items(path: str, page_size: int = 2000) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 0
    while True:
        payload = api("GET", path, params={"q": json.dumps({"page": page, "page_size": page_size})})
        batch = payload.get("result", [])
        items.extend(batch)
        if not batch or len(items) >= int(payload.get("count", len(items))):
            return items
        page += 1


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:240] or "northstar"


def login() -> None:
    token = api("POST", "/api/v1/security/login", json={
        "username": USERNAME,
        "password": PASSWORD,
        "provider": "db",
        "refresh": True,
    }).get("access_token")
    if not token:
        raise RuntimeError("Superset login did not return an access token")
    SESSION.headers.update({"Authorization": f"Bearer {token}"})
    csrf = api("GET", "/api/v1/security/csrf_token/", _allow_auth_retry=False).get("result")
    if csrf:
        SESSION.headers.update({"X-CSRFToken": csrf})


def get_database() -> int:
    databases = list_items("/api/v1/database/", 100)
    for database in databases:
        if database.get("database_name") == "Northstar Lakehouse":
            return int(database["id"])
    payload = {
        "database_name": "Northstar Lakehouse",
        "sqlalchemy_uri": (
            "postgresql+psycopg2://enterprise:"
            f"{quote_plus(os.environ['NORTHSTAR_WAREHOUSE_PASSWORD'])}"
            "@warehouse:5432/enterprise_lake"
        ),
        "expose_in_sqllab": True,
        "allow_ctas": False,
        "allow_cvas": False,
        "allow_dml": False,
        "allow_run_async": False,
        "allow_file_upload": False,
        "configuration_method": "sqlalchemy_form",
        "extra": json.dumps({"metadata_params": {}, "engine_params": {}}),
    }
    result = api("POST", "/api/v1/database/", json=payload)
    return int(result.get("id") or result.get("result", {}).get("id"))


def get_datasets(database_id: int) -> dict[str, int]:
    result: dict[str, int] = {}
    for schema, table in DATASETS:
        created = api("POST", "/api/v1/dataset/get_or_create/", json={
            "database_id": database_id,
            "schema": schema,
            "table_name": table,
            "normalize_columns": False,
            "always_filter_main_dttm": False,
        })
        dataset_id = int(created.get("result", {}).get("table_id") or created.get("id"))
        result[f"{schema}.{table}"] = dataset_id
    # Sync columns after all dataset records exist; views and tables are both supported.
    for key, dataset_id in result.items():
        try:
            api("PUT", f"/api/v1/dataset/{dataset_id}/refresh", json={})
        except RuntimeError as exc:
            print(f"warning: column refresh failed for {key}: {exc}", file=sys.stderr)
    return result


def metric(column: str, label: str | None = None, aggregate: str = "SUM") -> dict[str, Any]:
    return {
        "expressionType": "SIMPLE",
        "column": {"column_name": column},
        "aggregate": aggregate,
        "label": label or f"{aggregate}({column})",
    }


def normalized_viz_type(viz_type: str) -> str:
    return "pie" if viz_type in ("echarts_bar", "bar") else viz_type


def chart_params(dataset_id: int, viz_type: str, metric_col: str, dimensions: list[str], time_col: str | None = None) -> dict[str, Any]:
    viz_type = normalized_viz_type(viz_type)
    base: dict[str, Any] = {
        "viz_type": viz_type,
        "datasource": f"{dataset_id}__table",
        "time_range": "No filter",
        "adhoc_filters": [],
        "row_limit": 10000,
        "show_legend": True,
        "rich_tooltip": True,
    }
    m = metric(metric_col)
    if viz_type == "big_number_total":
        base.update({"metric": m, "header_font_size": 0.4, "subheader_font_size": 0.15})
    elif viz_type == "table":
        base.update({
            "all_columns": dimensions[:5] + [metric_col],
            "page_length": 20,
            "include_search": True,
        })
    elif viz_type == "pie":
        base.update({"metric": m, "groupby": dimensions[:1], "show_labels": True, "show_total": True})
    else:
        base.update({
            "metrics": [m],
            "groupby": dimensions[:2],
            "show_labels": False,
            "line_interpolation": "linear",
            "order_desc": True,
        })
        if time_col:
            base.update({
                "granularity_sqla": time_col,
                "time_grain_sqla": "P1M",
                "x_axis": time_col,
                "x_axis_format": "%Y-%m",
            })
    return base


def create_or_get_dashboard(title: str, description: str, dashboards: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if title in dashboards:
        return dashboards[title]
    slug = slugify(title)
    existing = next((item for item in list_items("/api/v1/dashboard/", 1000) if item.get("dashboard_title") == title), None)
    if existing:
        dashboards[title] = existing
        return existing
    result = api("POST", "/api/v1/dashboard/", json={
        "dashboard_title": title,
        "slug": slug,
        "published": True,
        "position_json": "{}",
        "json_metadata": json.dumps({"timed_refresh_immune_slices": []}),
    })
    record = result.get("result", result)
    if "id" not in record:
        record = next(item for item in list_items("/api/v1/dashboard/", 1000) if item.get("dashboard_title") == title)
    dashboards[title] = record
    return record


def create_or_get_chart(
    title: str,
    description: str,
    dataset_id: int,
    dashboard_id: int,
    viz_type: str,
    metric_col: str,
    dimensions: list[str],
    time_col: str | None,
    charts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    existing = charts.get(title)
    if existing is None:
        existing = next((item for item in list_items("/api/v1/chart/", 3000) if item.get("slice_name") == title), None)
    if existing:
        api("PUT", f"/api/v1/chart/{int(existing['id'])}", json={
            "slice_name": title,
            "datasource_id": dataset_id,
            "datasource_type": "table",
            "viz_type": normalized_viz_type(viz_type),
            "params": json.dumps(chart_params(dataset_id, viz_type, metric_col, dimensions, time_col)),
        })
        charts[title] = existing
        return existing
    payload = {
        "slice_name": title,
        "description": description,
        "datasource_id": dataset_id,
        "datasource_type": "table",
        "viz_type": normalized_viz_type(viz_type),
        "params": json.dumps(chart_params(dataset_id, viz_type, metric_col, dimensions, time_col)),
        "dashboards": [dashboard_id],
    }
    try:
        result = api("POST", "/api/v1/chart/", json=payload)
    except RuntimeError as exc:
        # Table charts are a safe fallback for long-tail catalog examples if a new Superset
        # release renames an optional ECharts visualization type.
        if viz_type != "table":
            payload["viz_type"] = "table"
            payload["params"] = json.dumps(chart_params(dataset_id, "table", metric_col, dimensions, time_col))
            result = api("POST", "/api/v1/chart/", json=payload)
        else:
            raise exc
    record = result.get("result", result)
    if "id" not in record:
        record = next(item for item in list_items("/api/v1/chart/", 3000) if item.get("slice_name") == title)
    charts[title] = record
    return record


def position_json(chart_records: list[dict[str, Any]]) -> str:
    nodes: dict[str, Any] = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT", "children": ["GRID_ID"]},
        "GRID_ID": {"id": "GRID_ID", "type": "GRID", "parents": ["ROOT_ID"], "children": []},
        "HEADER_ID": {"id": "HEADER_ID", "type": "HEADER", "meta": {"text": "[ untitled dashboard ]"}},
    }
    for row_index in range(0, len(chart_records), 2):
        row_id = f"ROW-{row_index // 2 + 1:03d}"
        row_charts = chart_records[row_index:row_index + 2]
        nodes["GRID_ID"]["children"].append(row_id)
        nodes[row_id] = {
            "id": row_id,
            "type": "ROW",
            "parents": ["ROOT_ID", "GRID_ID"],
            "children": [],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for record in row_charts:
            chart_id = int(record["id"])
            key = f"CHART-{chart_id}"
            nodes[row_id]["children"].append(key)
            nodes[key] = {
                "id": key,
                "type": "CHART",
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "children": [],
                "meta": {
                    "chartId": chart_id,
                    "sliceName": record.get("slice_name", ""),
                    "uuid": record.get("uuid"),
                    "width": 6,
                    "height": 50,
                },
            }
    return json.dumps(nodes)


def save_dashboard(dashboard: dict[str, Any], charts: list[dict[str, Any]]) -> None:
    dashboard_id = int(dashboard["id"])
    api("PUT", f"/api/v1/dashboard/{dashboard_id}", json={
        "dashboard_title": dashboard.get("dashboard_title"),
        "slug": dashboard.get("slug") or slugify(dashboard.get("dashboard_title", "")),
        "published": True,
        "position_json": position_json(charts),
        "json_metadata": json.dumps({"timed_refresh_immune_slices": []}),
    })


CURATED = [
    ("01 | Executive Command Center", "Daily cross-functional operating picture.", [
        ("Revenue trend", "gold.mart_executive_daily", "echarts_timeseries_line", "net_sales", ["channel"], "order_date"),
        ("Gross margin dollars", "gold.mart_executive_daily", "big_number_total", "gross_margin", ["channel"], None),
        ("Orders by region", "gold.mart_executive_daily", "bar", "orders", ["region"], None),
        ("Average order value", "gold.mart_executive_daily", "big_number_total", "average_order_value", ["channel"], None),
        ("Sales mix by channel", "gold.mart_executive_daily", "pie", "net_sales", ["channel"], None),
        ("Units trend", "gold.mart_executive_daily", "echarts_timeseries_bar", "units", ["channel"], "order_date"),
        ("Return rate trend", "gold.mart_executive_daily", "echarts_timeseries_line", "return_rate", ["channel"], "order_date"),
        ("Active customers trend", "gold.mart_executive_daily", "echarts_timeseries_line", "active_customers", ["region"], "order_date"),
        ("Margin by region", "gold.mart_executive_daily", "bar", "gross_margin", ["region"], None),
        ("Executive daily detail", "gold.mart_executive_daily", "table", "net_sales", ["order_date", "channel", "region"], "order_date"),
    ]),
    ("02 | Store Performance", "Store productivity, margin, labor, and returns.", [
        ("Store revenue trend", "gold.mart_store_performance", "echarts_timeseries_line", "net_sales", ["store_type"], "order_date"),
        ("Revenue by region", "gold.mart_store_performance", "echarts_bar", "net_sales", ["region"], None),
        ("Orders by store type", "gold.mart_store_performance", "echarts_bar", "orders", ["store_type"], None),
        ("Gross margin by market", "gold.mart_store_performance", "echarts_bar", "gross_margin", ["market"], None),
        ("Sales per labor hour", "gold.mart_store_performance", "echarts_timeseries_line", "sales_per_labor_hour", ["store_type"], "order_date"),
        ("Units trend", "gold.mart_store_performance", "echarts_timeseries_bar", "units", ["region"], "order_date"),
        ("Return rate by store", "gold.mart_store_performance", "echarts_bar", "return_rate", ["store_type"], None),
        ("Store revenue headline", "gold.mart_store_performance", "big_number_total", "net_sales", ["region"], None),
        ("Store mix", "gold.mart_store_performance", "pie", "net_sales", ["store_type"], None),
        ("Store operating detail", "gold.mart_store_performance", "table", "net_sales", ["store_name", "region", "store_type"], "order_date"),
    ]),
    ("03 | Inventory & Availability", "Stockouts, days of supply, and inventory value.", [
        ("Inventory value", "silver.fct_inventory_snapshot", "big_number_total", "inventory_value", ["inventory_status"], None),
        ("Stockout snapshots", "silver.fct_inventory_snapshot", "big_number_total", "stockout_flag", ["inventory_status"], None),
        ("Inventory value by status", "silver.fct_inventory_snapshot", "pie", "inventory_value", ["inventory_status"], None),
        ("Inventory by store", "silver.fct_inventory_snapshot", "echarts_bar", "inventory_value", ["store_id"], None),
        ("Days of supply distribution", "silver.fct_inventory_snapshot", "echarts_bar", "days_of_supply", ["inventory_status"], None),
        ("On hand trend", "silver.fct_inventory_snapshot", "echarts_timeseries_line", "on_hand_units", ["inventory_status"], "snapshot_date"),
        ("Committed units trend", "silver.fct_inventory_snapshot", "echarts_timeseries_line", "committed_units", ["store_id"], "snapshot_date"),
        ("Transit units by product", "silver.fct_inventory_snapshot", "echarts_bar", "in_transit_units", ["product_id"], None),
        ("Inventory exception table", "silver.fct_inventory_snapshot", "table", "inventory_value", ["snapshot_date", "store_id", "product_id", "inventory_status"], "snapshot_date"),
        ("Inventory status headline", "silver.fct_inventory_snapshot", "big_number_total", "on_hand_units", ["inventory_status"], None),
    ]),
    ("04 | Supply Chain Control Tower", "Supplier fill, on-time performance, lead time, and purchase orders.", [
        ("Supplier fill rate", "gold.mart_supply_chain", "echarts_bar", "fill_rate", ["supplier_region"], None),
        ("PO value trend", "gold.mart_supply_chain", "echarts_timeseries_line", "open_po_value", ["supplier_region"], "event_date"),
        ("Units ordered by supplier", "gold.mart_supply_chain", "echarts_bar", "units_ordered", ["supplier_name"], None),
        ("Units received trend", "gold.mart_supply_chain", "echarts_timeseries_bar", "units_received", ["supplier_region"], "event_date"),
        ("On-time rate", "gold.mart_supply_chain", "big_number_total", "on_time_rate", ["supplier_region"], None),
        ("Lead time by region", "gold.mart_supply_chain", "echarts_bar", "lead_time_days", ["supplier_region"], None),
        ("Supplier mix", "gold.mart_supply_chain", "pie", "open_po_value", ["supplier_region"], None),
        ("Purchase orders trend", "gold.mart_supply_chain", "echarts_timeseries_line", "purchase_orders", ["supplier_region"], "event_date"),
        ("Supply chain headline", "gold.mart_supply_chain", "big_number_total", "units_received", ["supplier_region"], None),
        ("Supplier exception detail", "gold.mart_supply_chain", "table", "open_po_value", ["event_date", "supplier_name", "supplier_region"], "event_date"),
    ]),
    ("05 | Merchandising & Product", "Product demand, mix, promotion, and margin.", [
        ("Net sales by department", "silver.fct_sales_order_line", "echarts_bar", "net_sales", ["product_id"], None),
        ("Units by fulfillment status", "silver.fct_sales_order_line", "pie", "quantity", ["fulfillment_status"], None),
        ("Product margin trend", "silver.fct_sales_order_line", "echarts_timeseries_line", "gross_margin", ["channel"], "order_date"),
        ("Discount dollars", "silver.fct_sales_order_line", "big_number_total", "discount_amount", ["channel"], None),
        ("Gross sales trend", "silver.fct_sales_order_line", "echarts_timeseries_bar", "gross_sales", ["channel"], "order_date"),
        ("Net sales by channel", "silver.fct_sales_order_line", "echarts_bar", "net_sales", ["channel"], None),
        ("Returns by channel", "silver.fct_sales_order_line", "echarts_bar", "return_flag", ["channel"], None),
        ("Average unit value", "silver.fct_sales_order_line", "big_number_total", "net_sales", ["channel"], None),
        ("Sales-line detail", "silver.fct_sales_order_line", "table", "net_sales", ["order_date", "order_id", "product_id", "channel"], "order_date"),
        ("Order hour pattern", "silver.fct_sales_order_line", "echarts_bar", "quantity", ["order_hour"], None),
    ]),
    ("06 | Customer Value & Loyalty", "Customer value, loyalty mix, recency, and modeled risk.", [
        ("Observed customer revenue", "gold.mart_customer_value", "big_number_total", "net_sales", ["loyalty_tier"], None),
        ("Revenue by loyalty tier", "gold.mart_customer_value", "echarts_bar", "net_sales", ["loyalty_tier"], None),
        ("Customer value mix", "gold.mart_customer_value", "pie", "net_sales", ["loyalty_tier"], None),
        ("Orders by acquisition channel", "gold.mart_customer_value", "echarts_bar", "orders", ["acquisition_channel"], None),
        ("Average order value by tier", "gold.mart_customer_value", "echarts_bar", "average_order_value", ["loyalty_tier"], None),
        ("Predicted LTV by region", "gold.mart_customer_value", "echarts_bar", "predicted_ltv", ["home_region"], None),
        ("Customer recency", "gold.mart_customer_value", "echarts_bar", "recency_days", ["churn_risk"], None),
        ("Gross margin by tier", "gold.mart_customer_value", "echarts_bar", "gross_margin", ["loyalty_tier"], None),
        ("Customer value detail", "gold.mart_customer_value", "table", "net_sales", ["customer_id", "loyalty_tier", "churn_risk"], None),
        ("Customer count", "gold.mart_customer_value", "big_number_total", "customer_id", ["loyalty_tier"], None),
    ]),
    ("07 | Marketing Efficiency", "Campaign spend, funnel response, and attributed economics.", [
        ("Spend trend", "gold.mart_marketing_efficiency", "echarts_timeseries_line", "spend", ["channel"], "event_date"),
        ("Attributed revenue", "gold.mart_marketing_efficiency", "big_number_total", "revenue", ["channel"], None),
        ("ROAS by channel", "gold.mart_marketing_efficiency", "echarts_bar", "roas", ["channel"], None),
        ("CAC by audience", "gold.mart_marketing_efficiency", "echarts_bar", "cac", ["audience"], None),
        ("Clicks and sessions", "gold.mart_marketing_efficiency", "echarts_timeseries_bar", "clicks", ["channel"], "event_date"),
        ("Orders trend", "gold.mart_marketing_efficiency", "echarts_timeseries_line", "orders", ["channel"], "event_date"),
        ("Marketing mix", "gold.mart_marketing_efficiency", "pie", "spend", ["channel"], None),
        ("Attributed margin", "gold.mart_marketing_efficiency", "echarts_bar", "attributed_margin", ["channel"], None),
        ("Campaign detail", "gold.mart_marketing_efficiency", "table", "revenue", ["campaign_id", "channel", "audience"], "event_date"),
        ("CTR headline", "gold.mart_marketing_efficiency", "big_number_total", "ctr", ["channel"], None),
    ]),
    ("08 | Digital Commerce Funnel", "Sessions, product engagement, checkout, conversion, and revenue.", [
        ("Sessions trend", "gold.mart_digital_funnel", "echarts_timeseries_line", "sessions", ["platform"], "event_date"),
        ("Revenue trend", "gold.mart_digital_funnel", "echarts_timeseries_line", "revenue", ["platform"], "event_date"),
        ("Conversion rate", "gold.mart_digital_funnel", "big_number_total", "conversion_rate", ["platform"], None),
        ("Conversion by platform", "gold.mart_digital_funnel", "echarts_bar", "conversion_rate", ["platform"], None),
        ("Checkout abandonment", "gold.mart_digital_funnel", "echarts_bar", "cart_abandonment_rate", ["traffic_source"], None),
        ("Product views", "gold.mart_digital_funnel", "echarts_timeseries_bar", "product_views", ["platform"], "event_date"),
        ("Funnel mix", "gold.mart_digital_funnel", "pie", "sessions", ["traffic_source"], None),
        ("Orders by source", "gold.mart_digital_funnel", "echarts_bar", "orders", ["traffic_source"], None),
        ("Digital funnel detail", "gold.mart_digital_funnel", "table", "revenue", ["event_date", "platform", "traffic_source"], "event_date"),
        ("Add-to-cart headline", "gold.mart_digital_funnel", "big_number_total", "add_to_cart", ["platform"], None),
    ]),
    ("09 | Finance & Margin Bridge", "Revenue, COGS, operating expense, cash, and plan.", [
        ("Revenue trend", "gold.mart_finance_daily", "echarts_timeseries_line", "revenue", [], "event_date"),
        ("Gross profit trend", "gold.mart_finance_daily", "echarts_timeseries_line", "gross_profit", [], "event_date"),
        ("Gross margin rate", "gold.mart_finance_daily", "big_number_total", "gross_margin_pct", [], None),
        ("Contribution margin", "gold.mart_finance_daily", "big_number_total", "contribution_margin", [], None),
        ("Revenue vs budget", "gold.mart_finance_daily", "echarts_timeseries_bar", "budget_revenue", [], "event_date"),
        ("COGS trend", "gold.mart_finance_daily", "echarts_timeseries_line", "cogs", [], "event_date"),
        ("Operating expense", "gold.mart_finance_daily", "echarts_timeseries_line", "operating_expense", [], "event_date"),
        ("Cash collections", "gold.mart_finance_daily", "echarts_timeseries_line", "cash_collections", [], "event_date"),
        ("Finance detail", "gold.mart_finance_daily", "table", "revenue", ["event_date", "revenue", "gross_profit", "contribution_margin"], "event_date"),
        ("Payment fees", "gold.mart_finance_daily", "big_number_total", "payment_fees", [], None),
    ]),
    ("10 | Customer Support Operations", "Service demand, backlog, response, resolution, and satisfaction.", [
        ("Tickets created", "gold.mart_support_ops", "echarts_timeseries_line", "tickets_created", ["queue"], "event_date"),
        ("Tickets resolved", "gold.mart_support_ops", "echarts_timeseries_line", "tickets_resolved", ["queue"], "event_date"),
        ("Backlog trend", "gold.mart_support_ops", "echarts_timeseries_bar", "backlog", ["queue"], "event_date"),
        ("First response time", "gold.mart_support_ops", "big_number_total", "first_response_minutes", ["channel"], None),
        ("CSAT by queue", "gold.mart_support_ops", "echarts_bar", "csat", ["queue"], None),
        ("Resolution hours", "gold.mart_support_ops", "echarts_bar", "resolution_hours", ["queue"], None),
        ("Ticket mix", "gold.mart_support_ops", "pie", "tickets_created", ["channel"], None),
        ("Escalation rate", "gold.mart_support_ops", "echarts_bar", "escalation_rate", ["queue"], None),
        ("Support detail", "gold.mart_support_ops", "table", "tickets_created", ["event_date", "channel", "queue"], "event_date"),
        ("Ticket volume headline", "gold.mart_support_ops", "big_number_total", "tickets_created", ["queue"], None),
    ]),
    ("11 | Data Quality & Trust", "Freshness, grain, reconciliation, and incident triage.", [
        ("Failed checks", "gold.data_quality_checks", "big_number_total", "failed_rows", ["domain"], None),
        ("Checks by status", "gold.data_quality_checks", "pie", "total_rows", ["status"], None),
        ("Failures by domain", "gold.data_quality_checks", "echarts_bar", "failed_rows", ["domain"], None),
        ("Freshness lag trend", "gold.data_quality_checks", "echarts_timeseries_line", "freshness_lag_minutes", ["domain"], "check_date"),
        ("Warning and failure rate", "gold.data_quality_checks", "echarts_bar", "failed_rows", ["severity"], None),
        ("Checks over time", "gold.data_quality_checks", "echarts_timeseries_bar", "total_rows", ["status"], "check_date"),
        ("Quality detail", "gold.data_quality_checks", "table", "failed_rows", ["check_date", "domain", "table_name", "status"], "check_date"),
        ("Critical issue count", "gold.data_quality_checks", "big_number_total", "failed_rows", ["severity"], None),
        ("Owner workload", "gold.data_quality_checks", "echarts_bar", "failed_rows", ["owner"], None),
        ("Quality check mix", "gold.data_quality_checks", "pie", "total_rows", ["check_name"], None),
    ]),
    ("12 | Fulfillment & Workforce", "Delivery reliability, labor capacity, and service economics.", [
        ("Delivery late rate", "gold.mart_delivery_performance", "echarts_timeseries_line", "late_rate", ["carrier"], "promised_date"),
        ("Shipments by carrier", "gold.mart_delivery_performance", "echarts_bar", "shipments", ["carrier"], None),
        ("Average delivery days", "gold.mart_delivery_performance", "big_number_total", "average_delivery_days", ["service_level"], None),
        ("Shipping cost", "gold.mart_delivery_performance", "echarts_bar", "shipping_cost", ["carrier"], None),
        ("Damage rate", "gold.mart_delivery_performance", "echarts_bar", "damage_rate", ["carrier"], None),
        ("Worked hours trend", "gold.mart_workforce_productivity", "echarts_timeseries_line", "worked_hours", ["role"], "shift_date"),
        ("Labor cost by role", "gold.mart_workforce_productivity", "echarts_bar", "labor_cost", ["role"], None),
        ("Sales assisted per hour", "gold.mart_workforce_productivity", "echarts_bar", "sales_assisted_per_hour", ["role"], None),
        ("Workforce detail", "gold.mart_workforce_productivity", "table", "worked_hours", ["shift_date", "store_id", "role"], "shift_date"),
        ("Absence rate", "gold.mart_workforce_productivity", "big_number_total", "absence_rate", ["role"], None),
    ]),
]


CATALOG = [
    ("gold.mart_executive_daily", "net_sales", ["channel", "region"], "order_date"),
    ("gold.mart_store_performance", "net_sales", ["region", "store_type"], "order_date"),
    ("gold.mart_customer_value", "net_sales", ["loyalty_tier", "home_region"], None),
    ("gold.mart_marketing_efficiency", "revenue", ["channel", "audience"], "event_date"),
    ("gold.mart_supply_chain", "units_received", ["supplier_region", "supplier_name"], "event_date"),
    ("gold.mart_finance_daily", "revenue", [], "event_date"),
    ("gold.mart_support_ops", "tickets_created", ["channel", "queue"], "event_date"),
    ("gold.mart_digital_funnel", "sessions", ["platform", "traffic_source"], "event_date"),
    ("gold.mart_delivery_performance", "shipments", ["carrier", "service_level"], "promised_date"),
    ("gold.mart_workforce_productivity", "worked_hours", ["role", "store_id"], "shift_date"),
    ("gold.data_quality_checks", "failed_rows", ["domain", "status"], "check_date"),
    ("silver.fct_inventory_snapshot", "inventory_value", ["inventory_status", "store_id"], "snapshot_date"),
    ("silver.fct_sales_order_line", "net_sales", ["channel", "fulfillment_status"], "order_date"),
]


def main() -> None:
    print(f"Connecting to {BASE} ...")
    login()
    database_id = get_database()
    dataset_ids = get_datasets(database_id)
    print(f"Northstar Lakehouse database id={database_id}; registered {len(dataset_ids)} datasets")

    dashboards = {item.get("dashboard_title"): item for item in list_items("/api/v1/dashboard/", 1000)}
    charts = {item.get("slice_name"): item for item in list_items("/api/v1/chart/", 3000)}
    total_charts = 0
    total_dashboards = 0

    for title, description, specs in CURATED:
        dashboard = create_or_get_dashboard(title, description, dashboards)
        dashboard_charts = []
        for chart_title, dataset_key, viz_type, metric_col, dimensions, time_col in specs:
            record = create_or_get_chart(
                f"NS | {title} | {chart_title}",
                f"Synthetic Northstar example. Grain is owned by {dataset_key}; inspect the agent notes before interpreting it.",
                dataset_ids[dataset_key], int(dashboard["id"]), viz_type, metric_col, dimensions, time_col, charts,
            )
            dashboard_charts.append(record)
            total_charts += 1
        save_dashboard(dashboard, dashboard_charts)
        total_dashboards += 1
        print(f"curated dashboard ready: {title} ({len(dashboard_charts)} charts)")

    for pack in range(1, 37):
        title = f"13 | Catalog Pack {pack:02d}"
        dashboard = create_or_get_dashboard(
            title,
            "Generated long-tail chart catalog for analyst exploration. These examples are intentionally less curated.",
            dashboards,
        )
        dashboard_charts = []
        for slot in range(1, 31):
            dataset_key, metric_col, dimensions, time_col = CATALOG[(pack * 7 + slot) % len(CATALOG)]
            kinds = ["echarts_timeseries_line", "echarts_timeseries_bar", "echarts_bar", "pie", "table", "big_number_total"]
            viz_type = kinds[(pack + slot) % len(kinds)]
            chart_title = f"NS | {title} | Example {slot:02d} | {dataset_key.split('.')[-1]} | {metric_col}"
            record = create_or_get_chart(
                chart_title,
                f"Generated synthetic catalog example {pack:02d}-{slot:02d}; long-tail chart, not a certified KPI.",
                dataset_ids[dataset_key], int(dashboard["id"]), viz_type, metric_col, dimensions, time_col, charts,
            )
            dashboard_charts.append(record)
            total_charts += 1
            if total_charts % 100 == 0:
                print(f"seed progress: {total_charts} charts")
        save_dashboard(dashboard, dashboard_charts)
        total_dashboards += 1
        print(f"catalog dashboard ready: {title}")

    print(json.dumps({
        "database_id": database_id,
        "datasets": len(dataset_ids),
        "dashboards": total_dashboards,
        "charts_created_or_reused": total_charts,
        "curated_dashboards": len(CURATED),
        "catalog_dashboards": 36,
    }, indent=2))


if __name__ == "__main__":
    main()
