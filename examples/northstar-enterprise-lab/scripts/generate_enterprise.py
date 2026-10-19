#!/usr/bin/env python3
"""Generate the deterministic Northstar synthetic lakehouse and Superset seed inputs."""

from __future__ import annotations

import csv
import json
import os
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "warehouse" / "init"
SEED = int(os.environ.get("NORTHSTAR_SEED", "90219"))
RNG = random.Random(SEED)
START_DATE = date(2024, 1, 1)
END_DATE = date(2026, 9, 19)
DATES = [START_DATE + timedelta(days=i) for i in range((END_DATE - START_DATE).days + 1)]

REGIONS = ["Atlantic", "Central", "Great Lakes", "Mountain", "Pacific", "Prairies"]
STORE_TYPES = ["Flagship", "Neighborhood", "Outlet", "Campus"]
CHANNELS = ["Store", "Online", "Mobile", "Marketplace"]
DEPARTMENTS = ["Outerwear", "Footwear", "Camping", "Climbing", "Run", "Travel", "Everyday"]
CATEGORIES = {
    "Outerwear": ["Jackets", "Fleece", "Rainwear"],
    "Footwear": ["Hiking", "Trail Run", "Casual"],
    "Camping": ["Tents", "Sleep", "Camp Kitchen"],
    "Climbing": ["Rope", "Hardware", "Apparel"],
    "Run": ["Shoes", "Hydration", "Accessories"],
    "Travel": ["Packs", "Luggage", "Organizers"],
    "Everyday": ["Tops", "Bottoms", "Accessories"],
}


def write_csv(name: str, columns: list[str], rows: list[list[object]]) -> int:
    path = INIT / f"{name}.csv"
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        writer.writerows(rows)
    return len(rows)


def money(value: float) -> float:
    return round(value, 2)


def iso(d: date) -> str:
    return d.isoformat()


def build_dimensions() -> tuple[dict[str, list[str]], dict[str, int], dict[str, list[list[object]]]]:
    columns: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    rows: dict[str, list[list[object]]] = {}

    columns["dim_date"] = [
        "date_key", "calendar_date", "year", "quarter", "month", "month_name",
        "week_of_year", "fiscal_year", "fiscal_period", "is_weekend", "is_holiday",
    ]
    date_rows = []
    for d in DATES:
        fiscal_year = d.year if d.month >= 2 else d.year - 1
        fiscal_period = ((d.month - 2) % 12) + 1
        date_rows.append([
            int(d.strftime("%Y%m%d")), iso(d), d.year, f"Q{((d.month - 1) // 3) + 1}",
            d.month, d.strftime("%B"), d.isocalendar().week, fiscal_year, fiscal_period,
            d.weekday() >= 5, (d.month == 12 and d.day >= 15) or (d.month == 11 and d.day >= 20),
        ])
    rows["dim_date"] = date_rows
    counts["dim_date"] = len(date_rows)

    columns["dim_store"] = [
        "store_id", "store_name", "region", "market", "store_type", "opened_date",
        "square_feet", "latitude", "longitude", "annual_sales_target",
    ]
    stores = []
    markets = ["Toronto", "Vancouver", "Chicago", "Denver", "Seattle", "Montreal", "Calgary", "Boston"]
    for i in range(1, 55):
        region = REGIONS[(i - 1) % len(REGIONS)]
        market = markets[(i * 3) % len(markets)]
        store_type = STORE_TYPES[(i + 1) % len(STORE_TYPES)]
        opened = date(2014 + (i % 8), 2 + (i % 9), 1 + (i % 24))
        stores.append([
            f"ST{i:03d}", f"{market} {store_type} {i:02d}", region, market, store_type,
            iso(opened), 9000 + (i % 7) * 1800, round(35 + RNG.random() * 15, 5),
            round(-118 + RNG.random() * 55, 5), money(2_200_000 + RNG.random() * 2_100_000),
        ])
    rows["dim_store"] = stores
    counts["dim_store"] = len(stores)

    columns["dim_product"] = [
        "product_id", "sku", "product_name", "department", "category", "subcategory",
        "brand", "supplier_id", "unit_price", "unit_cost", "lifecycle_status", "launch_date",
    ]
    products = []
    for i in range(1, 361):
        department = DEPARTMENTS[(i - 1) % len(DEPARTMENTS)]
        category = CATEGORIES[department][(i // 3) % len(CATEGORIES[department])]
        brands = ["Northstar", "Summit Lab", "Alpine Works", "Fieldcraft", "Daybreak"]
        price = 22 + RNG.random() * 380
        cost = price * (0.32 + RNG.random() * 0.24)
        products.append([
            f"PRD{i:04d}", f"SKU-{i:05d}", f"{brands[i % len(brands)]} {category} {i:03d}",
            department, category, f"{category} Core", brands[i % len(brands)], f"SUP{(i % 80) + 1:03d}",
            money(price), money(cost), "Core" if i % 11 else "Seasonal",
            iso(date(2023 + (i % 4), 1 + (i % 12), 1 + (i % 24))),
        ])
    rows["dim_product"] = products
    counts["dim_product"] = len(products)

    columns["dim_customer"] = [
        "customer_id", "signup_date", "home_region", "loyalty_tier", "acquisition_channel",
        "age_band", "email_opt_in", "predicted_ltv", "churn_risk", "preferred_channel",
    ]
    customers = []
    tiers = ["Base", "Trail", "Summit", "Peak"]
    acquisition = ["Organic", "Paid Search", "Social", "Affiliate", "Store", "Referral"]
    for i in range(1, 25001):
        signup = START_DATE - timedelta(days=RNG.randint(0, 1300))
        tier = RNG.choices(tiers, weights=[58, 25, 12, 5])[0]
        base_ltv = {"Base": 120, "Trail": 280, "Summit": 640, "Peak": 1320}[tier]
        customers.append([
            f"CUS{i:07d}", iso(signup), RNG.choice(REGIONS), tier, RNG.choice(acquisition),
            RNG.choice(["18-24", "25-34", "35-44", "45-54", "55+"]), RNG.random() > 0.18,
            money(base_ltv * (0.65 + RNG.random() * 0.9)),
            RNG.choice(["Low", "Low", "Medium", "High"]), RNG.choice(["Store", "Online", "Mobile"]),
        ])
    rows["dim_customer"] = customers
    counts["dim_customer"] = len(customers)

    columns["dim_supplier"] = [
        "supplier_id", "supplier_name", "supplier_region", "supplier_type", "incoterm", "payment_terms_days",
    ]
    suppliers = []
    for i in range(1, 81):
        suppliers.append([
            f"SUP{i:03d}", f"{RNG.choice(['Atlas', 'Cedar', 'Harbor', 'Pioneer', 'Summit', 'Tundra'])} Supply {i:02d}",
            RNG.choice(REGIONS + ["East Asia", "Europe"]), RNG.choice(["Strategic", "Core", "Long-tail"]),
            RNG.choice(["FOB", "DDP", "EXW"]), RNG.choice([30, 45, 60, 90]),
        ])
    rows["dim_supplier"] = suppliers
    counts["dim_supplier"] = len(suppliers)

    columns["dim_campaign"] = [
        "campaign_id", "campaign_name", "channel", "audience", "objective", "start_date", "end_date", "owner",
    ]
    campaigns = []
    for i in range(1, 121):
        start = START_DATE + timedelta(days=RNG.randint(0, max(1, len(DATES) - 45)))
        end = min(END_DATE, start + timedelta(days=RNG.randint(7, 45)))
        campaigns.append([
            f"CMP{i:04d}", f"{RNG.choice(['Trail Ready', 'Winter Layering', 'Member Week', 'Weekend Escape', 'New Season'])} {i:03d}",
            RNG.choice(["Paid Search", "Social", "Affiliate", "Email", "Display"]),
            RNG.choice(["Prospect", "Loyalty", "Lapsed", "High Intent"]), RNG.choice(["Acquire", "Retain", "Reactivate"]),
            iso(start), iso(end), RNG.choice(["Growth", "CRM", "Brand", "Merchandising"]),
        ])
    rows["dim_campaign"] = campaigns
    counts["dim_campaign"] = len(campaigns)
    return columns, counts, rows


def build_facts(dim_rows: dict[str, list[list[object]]]) -> tuple[dict[str, list[str]], dict[str, int], dict[str, list[list[object]]]]:
    columns: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    rows: dict[str, list[list[object]]] = {}

    stores = dim_rows["dim_store"]
    products = dim_rows["dim_product"]
    customers = dim_rows["dim_customer"]
    suppliers = dim_rows["dim_supplier"]
    campaigns = dim_rows["dim_campaign"]

    columns["fct_sales_order_line"] = [
        "order_id", "line_id", "order_date", "customer_id", "product_id", "store_id", "channel",
        "quantity", "gross_sales", "discount_amount", "net_sales", "cost_amount", "gross_margin",
        "fulfillment_status", "return_flag", "promo_code", "payment_method", "shipping_zone", "order_hour",
    ]
    sales = []
    for order_num in range(1, 140001):
        d = RNG.choice(DATES)
        customer = RNG.choice(customers)
        channel = RNG.choices(CHANNELS, weights=[43, 36, 14, 7])[0]
        store = RNG.choice(stores) if channel == "Store" else None
        lines = RNG.choices([1, 2, 3, 4, 5], weights=[40, 31, 18, 8, 3])[0]
        demand_factor = 1.25 if d.month in (11, 12) else (1.08 if d.weekday() >= 5 else 0.96)
        for line_num in range(1, lines + 1):
            product = RNG.choice(products)
            quantity = RNG.choices([1, 2, 3, 4], weights=[76, 18, 5, 1])[0]
            gross = float(product[8]) * quantity * demand_factor
            discount = gross * RNG.choice([0, 0, 0.05, 0.10, 0.15, 0.20])
            net = gross - discount
            cost = float(product[9]) * quantity
            sales.append([
                f"ORD-{order_num:07d}", f"ORD-{order_num:07d}-{line_num:02d}", iso(d), customer[0], product[0],
                store[0] if store else None, channel, quantity, money(gross), money(discount), money(net),
                money(cost), money(net - cost), RNG.choice(["Delivered", "Delivered", "Delivered", "Processing", "Cancelled"]),
                RNG.random() < 0.045, RNG.choice([None, None, "TRAIL10", "MEMBER15", "WINTER20"]),
                RNG.choice(["Card", "Card", "Wallet", "Gift Card"]), RNG.choice(["Local", "Regional", "National"]),
                RNG.randint(7, 22),
            ])
    rows["fct_sales_order_line"] = sales
    counts["fct_sales_order_line"] = len(sales)

    columns["fct_inventory_snapshot"] = [
        "snapshot_date", "store_id", "product_id", "on_hand_units", "committed_units", "in_transit_units",
        "replenishment_point", "stockout_flag", "inventory_value", "days_of_supply", "inventory_status",
    ]
    inventory = []
    snapshot_dates = DATES[::60]
    for d in snapshot_dates:
        for store in stores:
            for product in RNG.sample(products, 55):
                seasonal = 1.35 if d.month in (10, 11, 12) and product[3] in ("Outerwear", "Camping") else 1.0
                on_hand = max(0, int(RNG.gauss(38 * seasonal, 24)))
                committed = max(0, int(RNG.gauss(9, 7)))
                in_transit = max(0, int(RNG.gauss(15, 12)))
                available = on_hand - committed
                stockout = available <= 0
                dos = 0 if stockout else round(available / (3.5 + RNG.random() * 6), 1)
                inventory.append([
                    iso(d), store[0], product[0], on_hand, committed, in_transit, max(6, int(18 + RNG.random() * 28)),
                    stockout, money(on_hand * float(product[9])), dos,
                    "Stockout" if stockout else ("Overstock" if dos > 45 else "Healthy"),
                ])
    rows["fct_inventory_snapshot"] = inventory
    counts["fct_inventory_snapshot"] = len(inventory)

    columns["fct_purchase_order_line"] = [
        "po_id", "po_line_id", "order_date", "expected_date", "received_date", "supplier_id", "product_id",
        "store_id", "units_ordered", "units_received", "unit_cost", "po_value", "on_time_flag", "fill_rate",
    ]
    purchases = []
    for i in range(1, 45001):
        order_d = RNG.choice(DATES[:-90])
        expected = order_d + timedelta(days=RNG.randint(8, 45))
        received = expected + timedelta(days=RNG.choice([-5, -2, 0, 0, 1, 3, 8, 15]))
        received = min(END_DATE, max(order_d, received))
        ordered = RNG.randint(20, 700)
        received_units = max(0, int(ordered * RNG.uniform(0.74, 1.05)))
        product = RNG.choice(products)
        purchases.append([
            f"PO-{i:07d}", f"PO-{i:07d}-{RNG.randint(1, 4):02d}", iso(order_d), iso(expected), iso(received),
            RNG.choice(suppliers)[0], product[0], RNG.choice(stores)[0], ordered, received_units,
            product[9], money(ordered * float(product[9])), received <= expected,
            round(received_units / ordered, 4),
        ])
    rows["fct_purchase_order_line"] = purchases
    counts["fct_purchase_order_line"] = len(purchases)

    columns["fct_web_session"] = [
        "session_id", "event_date", "customer_id", "platform", "traffic_source", "sessions", "product_views",
        "add_to_cart", "checkout_started", "orders", "revenue", "device_type", "market",
    ]
    sessions = []
    for i in range(1, 220001):
        d = RNG.choice(DATES)
        platform = RNG.choice(["Web", "Mobile Web", "App"])
        session_count = RNG.choices([1, 2, 3], weights=[88, 10, 2])[0]
        views = max(1, int(RNG.gauss(4.8, 4.0)))
        atc = 1 if RNG.random() < min(0.65, 0.07 + views * 0.025) else 0
        checkout = 1 if atc and RNG.random() < 0.46 else 0
        orders = 1 if checkout and RNG.random() < 0.54 else 0
        sessions.append([
            f"SES-{i:08d}", iso(d), RNG.choice(customers)[0] if RNG.random() > 0.22 else None, platform,
            RNG.choice(["Organic", "Paid Search", "Social", "Email", "Direct", "Affiliate"]), session_count,
            views, atc, checkout, orders, money(orders * RNG.uniform(42, 260)),
            RNG.choice(["Mobile", "Desktop", "Tablet"]), RNG.choice(["Canada", "United States"]),
        ])
    rows["fct_web_session"] = sessions
    counts["fct_web_session"] = len(sessions)

    columns["fct_marketing_daily"] = [
        "event_date", "campaign_id", "channel", "audience", "spend", "impressions", "clicks", "sessions",
        "orders", "revenue", "attributed_margin", "ctr", "cpc", "roas", "cac",
    ]
    marketing = []
    for d in DATES[::2]:
        for campaign in RNG.sample(campaigns, min(36, len(campaigns))):
            if not (campaign[5] <= iso(d) <= campaign[6]):
                continue
            spend = RNG.uniform(600, 18000)
            impressions = int(spend * RNG.uniform(55, 220))
            clicks = max(1, int(impressions * RNG.uniform(0.008, 0.045)))
            sess = int(clicks * RNG.uniform(0.55, 0.92))
            orders = int(sess * RNG.uniform(0.02, 0.14))
            revenue = orders * RNG.uniform(55, 220)
            marketing.append([
                iso(d), campaign[0], campaign[2], campaign[3], money(spend), impressions, clicks, sess, orders,
                money(revenue), money(revenue * RNG.uniform(0.36, 0.62)), round(clicks / impressions, 5),
                money(spend / clicks), round(revenue / spend, 3), money(spend / max(1, orders)),
            ])
    rows["fct_marketing_daily"] = marketing
    counts["fct_marketing_daily"] = len(marketing)

    columns["fct_support_ticket"] = [
        "ticket_id", "event_date", "customer_id", "channel", "queue", "issue_type", "priority", "tickets_created",
        "tickets_resolved", "backlog", "first_response_minutes", "resolution_hours", "csat", "escalation_flag",
    ]
    tickets = []
    for i in range(1, 30001):
        d = RNG.choice(DATES)
        resolved = 1 if RNG.random() > 0.12 else 0
        queue = RNG.choice(["Order Status", "Returns", "Product Advice", "Membership", "Payment"])
        tickets.append([
            f"TCK-{i:07d}", iso(d), RNG.choice(customers)[0], RNG.choice(["Chat", "Email", "Phone", "Social"]),
            queue, RNG.choice(["Delivery", "Return", "Sizing", "Payment", "Account"]), RNG.choice(["Low", "Normal", "High"]),
            1, resolved, max(0, int(RNG.gauss(38, 18))), round(RNG.uniform(8, 620), 1),
            round(RNG.uniform(0.3, 48), 2), round(min(5, max(1, RNG.gauss(4.1, 0.7))), 2), RNG.random() < 0.07,
        ])
    rows["fct_support_ticket"] = tickets
    counts["fct_support_ticket"] = len(tickets)

    columns["fct_delivery"] = [
        "shipment_id", "order_id", "ship_date", "promised_date", "delivered_date", "carrier", "service_level",
        "shipping_cost", "delivery_days", "late_flag", "damage_flag", "destination_region",
    ]
    deliveries = []
    for i in range(1, 70001):
        ship = RNG.choice(DATES[:-15])
        promised = ship + timedelta(days=RNG.choice([2, 3, 4, 5, 7]))
        delivered = promised + timedelta(days=RNG.choice([-1, 0, 0, 0, 1, 2, 4]))
        deliveries.append([
            f"SHP-{i:07d}", f"ORD-{RNG.randint(1, 140000):07d}", iso(ship), iso(promised), iso(min(END_DATE, delivered)),
            RNG.choice(["Northstar Parcel", "Maple Post", "Summit Freight", "Pioneer Express"]),
            RNG.choice(["Ground", "Two Day", "Next Day"]), money(RNG.uniform(5, 34)),
            max(1, (delivered - ship).days), delivered > promised, RNG.random() < 0.008, RNG.choice(REGIONS),
        ])
    rows["fct_delivery"] = deliveries
    counts["fct_delivery"] = len(deliveries)

    columns["fct_employee_shift"] = [
        "shift_date", "store_id", "employee_id", "role", "scheduled_hours", "worked_hours", "sales_assisted",
        "labor_cost", "absence_flag",
    ]
    shifts = []
    for _i in range(1, 100001):
        d = RNG.choice(DATES)
        scheduled = round(RNG.choice([4, 6, 8, 8, 8, 10]), 1)
        worked = max(0, round(scheduled * RNG.uniform(0.72, 1.08), 1))
        shifts.append([
            iso(d), RNG.choice(stores)[0], f"EMP-{RNG.randint(1, 2600):05d}",
            RNG.choice(["Associate", "Supervisor", "Manager", "Fulfillment"]),
            scheduled, worked, RNG.randint(0, 28), money(worked * RNG.uniform(16, 34)), worked == 0,
        ])
    rows["fct_employee_shift"] = shifts
    counts["fct_employee_shift"] = len(shifts)

    columns["fct_finance_daily"] = [
        "event_date", "revenue", "cogs", "gross_profit", "gross_margin_pct", "operating_expense", "contribution_margin",
        "budget_revenue", "budget_gross_profit", "cash_collections", "payment_fees",
    ]
    finance = []
    for d in DATES:
        seasonal = 1.28 if d.month in (11, 12) else (1.1 if d.month in (5, 6) else 0.93)
        revenue = 185000 * seasonal * (0.83 + RNG.random() * 0.32)
        cogs = revenue * RNG.uniform(0.44, 0.58)
        op_ex = revenue * RNG.uniform(0.17, 0.24)
        fees = revenue * RNG.uniform(0.014, 0.028)
        budget = revenue * RNG.uniform(0.93, 1.07)
        budget_gp = budget * 0.49
        finance.append([
            iso(d), money(revenue), money(cogs), money(revenue - cogs), round((revenue - cogs) / revenue, 4),
            money(op_ex), money(revenue - cogs - op_ex - fees), money(budget), money(budget_gp),
            money(revenue * RNG.uniform(0.83, 1.04)), money(fees),
        ])
    rows["fct_finance_daily"] = finance
    counts["fct_finance_daily"] = len(finance)

    columns["data_quality_checks"] = [
        "check_date", "domain", "table_name", "check_name", "status", "failed_rows", "total_rows",
        "freshness_lag_minutes", "owner", "severity", "details",
    ]
    checks = []
    domains = ["Sales", "Inventory", "Marketing", "Customer", "Finance", "Digital", "Support"]
    check_names = ["Freshness SLA", "Null key rate", "Duplicate grain", "Referential integrity", "Source reconciliation"]
    table_map = {
        "Sales": "silver.fct_sales_order_line", "Inventory": "silver.fct_inventory_snapshot",
        "Marketing": "silver.fct_marketing_daily", "Customer": "silver.dim_customer",
        "Finance": "silver.fct_finance_daily", "Digital": "silver.fct_web_session",
        "Support": "silver.fct_support_ticket",
    }
    for d in DATES[::7]:
        for domain in domains:
            name = RNG.choice(check_names)
            status = RNG.choices(["PASS", "WARN", "FAIL"], weights=[77, 18, 5])[0]
            total = RNG.randint(10000, 420000)
            failed = 0 if status == "PASS" else RNG.randint(1, max(2, total // 40))
            checks.append([
                iso(d), domain, table_map[domain], name, status, failed, total,
                RNG.randint(4, 38) if status != "FAIL" else RNG.randint(42, 390),
                RNG.choice(["Data Platform", "Domain Analytics", "Finance Systems", "CRM Ops"]),
                "P1" if status == "FAIL" else ("P2" if status == "WARN" else "P3"),
                "Synthetic check result for the local lab",
            ])
    rows["data_quality_checks"] = checks
    counts["data_quality_checks"] = len(checks)
    return columns, counts, rows


def write_sql(columns: dict[str, list[str]]) -> None:
    table_types: dict[str, list[str]] = {
        "dim_date": ["integer", "date", "integer", "text", "integer", "text", "integer", "integer", "integer", "boolean", "boolean"],
        "dim_store": ["text", "text", "text", "text", "text", "date", "integer", "numeric(10,5)", "numeric(10,5)", "numeric(18,2)"],
        "dim_product": ["text", "text", "text", "text", "text", "text", "text", "text", "numeric(12,2)", "numeric(12,2)", "text", "date"],
        "dim_customer": ["text", "date", "text", "text", "text", "text", "boolean", "numeric(12,2)", "text", "text"],
        "dim_supplier": ["text", "text", "text", "text", "text", "integer"],
        "dim_campaign": ["text", "text", "text", "text", "text", "date", "date", "text"],
        "fct_sales_order_line": ["text", "text", "date", "text", "text", "text", "text", "integer", "numeric(18,2)", "numeric(18,2)", "numeric(18,2)", "numeric(18,2)", "numeric(18,2)", "text", "boolean", "text", "text", "text", "integer"],
        "fct_inventory_snapshot": ["date", "text", "text", "integer", "integer", "integer", "integer", "boolean", "numeric(18,2)", "numeric(12,2)", "text"],
        "fct_purchase_order_line": ["text", "text", "date", "date", "date", "text", "text", "text", "integer", "integer", "numeric(12,2)", "numeric(18,2)", "boolean", "numeric(8,4)"],
        "fct_web_session": ["text", "date", "text", "text", "text", "integer", "integer", "integer", "integer", "integer", "numeric(18,2)", "text", "text"],
        "fct_marketing_daily": ["date", "text", "text", "text", "numeric(18,2)", "integer", "integer", "integer", "integer", "numeric(18,2)", "numeric(18,2)", "numeric(10,5)", "numeric(12,2)", "numeric(10,3)", "numeric(12,2)"],
        "fct_support_ticket": ["text", "date", "text", "text", "text", "text", "text", "integer", "integer", "integer", "numeric(12,2)", "numeric(12,2)", "numeric(8,2)", "boolean"],
        "fct_delivery": ["text", "text", "date", "date", "date", "text", "text", "numeric(12,2)", "integer", "boolean", "boolean", "text"],
        "fct_employee_shift": ["date", "text", "text", "text", "numeric(8,2)", "numeric(8,2)", "integer", "numeric(12,2)", "boolean"],
        "fct_finance_daily": ["date", "numeric(18,2)", "numeric(18,2)", "numeric(18,2)", "numeric(8,4)", "numeric(18,2)", "numeric(18,2)", "numeric(18,2)", "numeric(18,2)", "numeric(18,2)", "numeric(18,2)"],
        "data_quality_checks": ["date", "text", "text", "text", "text", "integer", "integer", "integer", "text", "text", "text"],
    }
    sql = "create schema if not exists silver;\ncreate schema if not exists gold;\n\n"
    for name, cols in columns.items():
        types = table_types[name]
        sql += f"drop table if exists silver.{name} cascade;\ncreate table silver.{name} (\n"
        sql += ",\n".join(f"  {col} {types[i]}" for i, col in enumerate(cols))
        sql += f"\n);\ncopy silver.{name} ({', '.join(cols)}) from '/docker-entrypoint-initdb.d/{name}.csv' with (format csv, header true, null '');\n"
    sql += r"""
create or replace view gold.mart_executive_daily as
select s.order_date, s.channel, coalesce(st.region, 'Digital') as region,
  sum(s.net_sales) as net_sales, count(distinct s.order_id) as orders, sum(s.quantity) as units,
  sum(s.gross_margin) as gross_margin,
  sum(case when s.return_flag then 1 else 0 end)::numeric / nullif(count(*), 0) as return_rate,
  count(distinct s.customer_id) as active_customers,
  sum(s.net_sales) / nullif(count(distinct s.order_id), 0) as average_order_value,
  case when s.channel in ('Online', 'Mobile', 'Marketplace') then 1 else 0 end as digital_flag
from silver.fct_sales_order_line s
left join silver.dim_store st on st.store_id = s.store_id
group by 1, 2, 3, 11;

create or replace view gold.mart_store_performance as
select s.order_date, st.store_id, st.store_name, st.region, st.market, st.store_type,
  sum(s.net_sales) as net_sales, count(distinct s.order_id) as orders, sum(s.quantity) as units,
  sum(s.gross_margin) as gross_margin,
  sum(s.gross_margin) / nullif(sum(s.net_sales), 0) as margin_pct,
  coalesce(sh.labor_hours, 0) as labor_hours,
  sum(s.net_sales) / nullif(sh.labor_hours, 0) as sales_per_labor_hour,
  sum(case when s.return_flag then 1 else 0 end)::numeric / nullif(count(*), 0) as return_rate
from silver.fct_sales_order_line s
join silver.dim_store st on st.store_id = s.store_id
left join (select shift_date, store_id, sum(worked_hours) as labor_hours from silver.fct_employee_shift group by 1, 2) sh
  on sh.shift_date = s.order_date and sh.store_id = s.store_id
group by 1, 2, 3, 4, 5, 6, sh.labor_hours;

create or replace view gold.mart_customer_value as
select c.customer_id, c.signup_date, c.home_region, c.loyalty_tier, c.acquisition_channel, c.age_band,
  c.predicted_ltv, c.churn_risk, count(distinct s.order_id) as orders, sum(s.net_sales) as net_sales,
  sum(s.gross_margin) as gross_margin, sum(s.net_sales) / nullif(count(distinct s.order_id), 0) as average_order_value,
  sum(case when s.return_flag then 1 else 0 end) as return_lines, max(s.order_date) as last_order_date,
  (current_date - max(s.order_date)) as recency_days
from silver.dim_customer c
left join silver.fct_sales_order_line s on s.customer_id = c.customer_id
group by 1, 2, 3, 4, 5, 6, 7, 8;

create or replace view gold.mart_marketing_efficiency as
select event_date, campaign_id, channel, audience, spend, impressions, clicks, sessions, orders,
  revenue, attributed_margin, ctr, cpc, roas, cac
from silver.fct_marketing_daily;

create or replace view gold.mart_supply_chain as
select p.order_date as event_date, p.supplier_id, sup.supplier_name, sup.supplier_region,
  count(distinct p.po_id) as purchase_orders, sum(p.units_ordered) as units_ordered,
  sum(p.units_received) as units_received, sum(p.units_received)::numeric / nullif(sum(p.units_ordered), 0) as fill_rate,
  avg(p.received_date - p.order_date) as lead_time_days,
  avg(case when p.on_time_flag then 1 else 0 end) as on_time_rate, sum(p.po_value) as open_po_value
from silver.fct_purchase_order_line p
join silver.dim_supplier sup on sup.supplier_id = p.supplier_id
group by 1, 2, 3, 4;

create or replace view gold.mart_finance_daily as select * from silver.fct_finance_daily;

create or replace view gold.mart_support_ops as
select event_date, channel, queue, sum(tickets_created) as tickets_created, sum(tickets_resolved) as tickets_resolved,
  sum(backlog) as backlog, avg(first_response_minutes) as first_response_minutes,
  avg(resolution_hours) as resolution_hours, avg(csat) as csat,
  avg(case when escalation_flag then 1 else 0 end) as escalation_rate
from silver.fct_support_ticket group by 1, 2, 3;

create or replace view gold.mart_digital_funnel as
select event_date, platform, traffic_source, sum(sessions) as sessions, sum(product_views) as product_views,
  sum(add_to_cart) as add_to_cart, sum(checkout_started) as checkout_started, sum(orders) as orders,
  sum(orders)::numeric / nullif(sum(sessions), 0) as conversion_rate,
  1 - sum(orders)::numeric / nullif(sum(checkout_started), 0) as cart_abandonment_rate,
  sum(revenue) as revenue
from silver.fct_web_session group by 1, 2, 3;

create or replace view gold.mart_delivery_performance as
select promised_date, carrier, service_level, destination_region, count(*) as shipments,
  avg(delivery_days) as average_delivery_days, avg(case when late_flag then 1 else 0 end) as late_rate,
  avg(case when damage_flag then 1 else 0 end) as damage_rate, sum(shipping_cost) as shipping_cost
from silver.fct_delivery group by 1, 2, 3, 4;

create or replace view gold.mart_workforce_productivity as
select shift_date, store_id, role, sum(scheduled_hours) as scheduled_hours, sum(worked_hours) as worked_hours,
  sum(sales_assisted) as sales_assisted, sum(labor_cost) as labor_cost,
  sum(sales_assisted) / nullif(sum(worked_hours), 0) as sales_assisted_per_hour,
  avg(case when absence_flag then 1 else 0 end) as absence_rate
from silver.fct_employee_shift group by 1, 2, 3;

create or replace view gold.data_quality_checks as select * from silver.data_quality_checks;
"""
    (INIT / "00_schema_and_load.sql").write_text(sql)


def main() -> None:
    INIT.mkdir(parents=True, exist_ok=True)
    columns, dim_counts, dim_rows = build_dimensions()
    fact_columns, fact_counts, fact_rows = build_facts(dim_rows)
    all_columns = {**columns, **fact_columns}
    all_rows = {**dim_rows, **fact_rows}
    counts = {**dim_counts, **fact_counts}
    for name in all_columns:
        write_csv(name, all_columns[name], all_rows[name])
    write_sql(all_columns)
    manifest = {
        "enterprise": "Northstar Outfitters Co.",
        "synthetic": True,
        "seed": SEED,
        "date_start": iso(START_DATE),
        "date_end": iso(END_DATE),
        "table_row_counts": counts,
        "total_rows": sum(counts.values()),
        "generated_at": "deterministic-local-build",
    }
    (ROOT / "docs" / "generated_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"total_rows": manifest["total_rows"], "tables": counts}, indent=2))


if __name__ == "__main__":
    main()
