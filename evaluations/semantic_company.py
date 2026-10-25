"""Synthetic SQLite semantic-metric source for evaluation fixtures only."""

from __future__ import annotations

import hashlib
import random
import sqlite3
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from signalweave.models import (
    Evidence,
    Observation,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceComparisonContract,
    SourceRef,
)

_CONVERSION_SCALE = Decimal(1_000_000_000_000)
_CURRENT = "2026-09"
_PREVIOUS = "2026-08"
_POLICY = (
    "Notify Finance when canonical monthly net revenue falls more than 10% versus a comparable "
    "month; ignore smaller movement; investigate materially incomplete coverage or conflicting "
    "definitions. No sending is permitted by this fixture."
)
_PROFILES = {
    "retail": dict(company_name="Juniper Outfitters", domain="commerce", currency="USD", owner="Retail Controller", low=1200, high=30000, metric_id="retail.net_revenue", definition="Posted merchandise sales less refunds and sales tax; excludes shipping and gift cards.", population="Eligible merchandise; excludes shipping, gift cards, and tax.", time_semantics="Completed calendar transaction month; September versus August 2026.", category="merchandise", status="posted", currencies=(("USD", 1_000_000), ("CAD", 740_000), ("EUR", 1_080_000))),
    "saas": dict(company_name="Lattice Harbor Software", domain="subscriptions", currency="USD", owner="Subscription Revenue Accounting", low=5000, high=200000, metric_id="saas.net_revenue", definition="Recognized subscription revenue less refunds and credits; excludes usage, setup fees, and tax.", population="Eligible subscriptions recognized in service month; excludes usage, setup fees, and tax.", time_semantics="Completed calendar service month; September versus August 2026.", category="subscription", status="posted", currencies=(("USD", 1_000_000), ("EUR", 1_080_000))),
    "marketplace": dict(company_name="Tern Market", domain="marketplace_finance", currency="EUR", owner="Marketplace Finance", low=1500, high=60000, metric_id="marketplace.net_revenue", definition="Settled platform commissions less reversals and tax on fees; excludes GMV and seller proceeds.", population="Eligible settled platform fees; excludes seller GMV, proceeds, and tax.", time_semantics="Completed calendar settlement month; September versus August 2026.", category="platform_fee", status="settled", currencies=(("EUR", 1_000_000), ("GBP", 1_170_000), ("USD", 920_000))),
}
_RESOURCES = ("metric:net-revenue", "metric:gross-revenue", "metric:gmv", "metric:arr", "metric:revenue-draft", "metric:revenue-deprecated")


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _scaled(value: int, factor: float) -> int:
    return int(value * factor)


class SemanticCompany:
    """A bounded, source-owned semantic catalog backed by seeded SQLite rows."""

    name = "company"
    canonical_resource = "metric:net-revenue"
    current_period = "2026-09"
    previous_period = "2026-08"
    business_policy = _POLICY

    def __init__(self, root: Path, company: str, seed: int = 20261025, audit: Any = None):
        if company not in _PROFILES:
            raise ValueError(f"company must be one of {', '.join(_PROFILES)}")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.company = company
        self.profile = _PROFILES[company]
        self.seed = int(seed)
        self.audit = audit
        self.tenant_id = f"semantic-{company}"
        self.metric_id = self.profile["metric_id"]
        self.unit = self.profile["currency"]
        self.database = self.root / f"{company}-{self.seed}.sqlite3"
        self._initialize()

    def _specs(self) -> list[dict[str, str]]:
        p = self.profile
        common = dict(owner=p["owner"], grain="month", currency=p["currency"], time_semantics=p["time_semantics"])
        rows = [
            (_RESOURCES[0], p["metric_id"], p["definition"], p["population"], "r3", "active",
             "net_amount_cents", f"revenue_class='{p['category']}' AND status='{p['status']}' AND eligible=1"),
            (_RESOURCES[1], f"{self.company}.gross_revenue", "Gross ledger billings including charged tax, before refund, credit, and eligibility adjustments.", "Posted or settled transaction billings across the ledger.", "r2", "active", "gross_cents", "status IN ('posted','settled')"),
            (_RESOURCES[2], f"{self.company}.gmv", self._gmv_definition(), "Posted or settled transaction face value before refunds.", "r5", "active", "gmv_cents", "status IN ('posted','settled')"),
            (_RESOURCES[3], f"{self.company}.arr_run_rate", self._arr_definition(), "Eligible recurring or run-rate basis in the completed month.", "r4", "active", "arr_cents", "eligible=1 AND status IN ('posted','settled')"),
            (_RESOURCES[4], f"{self.company}.revenue_draft", "Draft proposal: gross billings less refunds and tax, with credits added back.", "Eligible posted or settled billings under an unapproved proposal.", "r0", "draft", "draft_net_cents", "eligible=1 AND status IN ('posted','settled')"),
            (_RESOURCES[5], f"{self.company}.revenue_legacy", "Retired chart convention: gross billings less refunds, with tax left in the amount.", "Posted or settled transaction billings under a retired convention.", "r1", "deprecated", "deprecated_net_cents", "status IN ('posted','settled')"),
        ]
        keys = ("resource", "metric_id", "definition", "population", "revision", "status", "measure", "where")
        specs = [{**common, **dict(zip(keys, values, strict=True))} for values in rows]
        if self.company == "marketplace":
            specs[2].update(population="Settled seller-order merchandise consideration; excludes fee and adjustment records and buyer tax.",
                            where="revenue_class='seller_order' AND status='settled'")
        return specs

    def _gmv_definition(self) -> str:
        return {"retail": "Basket checkout billings including charged tax, before refunds.", "saas": "Contract invoice face value including charged tax, before recognition.", "marketplace": "Settled buyer merchandise consideration before refunds and excluding buyer tax; platform-fee tax is not GMV."}[self.company]

    def _arr_definition(self) -> str:
        return {"retail": "Gross merchandise run rate multiplied by twelve.", "saas": "Subscription recognition multiplied by twelve.", "marketplace": "Gross platform commissions multiplied by twelve before reversals and tax."}[self.company]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        specs = self._specs()
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS fixture_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            stored = dict(db.execute("SELECT key,value FROM fixture_meta"))
            if stored:
                if stored != {"company": self.company, "seed": str(self.seed)}:
                    raise ValueError("SQLite fixture identity does not match requested company and seed")
                return
            db.execute("CREATE TABLE transactions (id INTEGER PRIMARY KEY, period TEXT, revenue_class TEXT, status TEXT, eligible INTEGER, available INTEGER, currency TEXT, fx_micros INTEGER, activity_bp INTEGER, gross_cents INTEGER, refund_cents INTEGER, tax_cents INTEGER, credit_cents INTEGER, recognized_cents INTEGER, platform_fee_cents INTEGER, fee_refund_cents INTEGER, gmv_cents INTEGER)")
            db.execute("CREATE TABLE semantic_metrics (resource TEXT PRIMARY KEY, metric_id TEXT, title TEXT, definition TEXT, owner TEXT, grain TEXT, currency TEXT, population TEXT, time_semantics TEXT, revision TEXT, status TEXT, measure TEXT, filter_sql TEXT)")
            db.execute("CREATE TABLE period_coverage (period TEXT PRIMARY KEY, required_rows INTEGER, available_rows INTEGER)")
            db.execute("CREATE TABLE definition_conflicts (metric_id TEXT, owner TEXT, revision TEXT, definition TEXT, population TEXT, time_semantics TEXT)")
            net = {"retail": "gross_cents-refund_cents-tax_cents", "saas": "recognized_cents-refund_cents-credit_cents", "marketplace": "platform_fee_cents-fee_refund_cents-tax_cents"}[self.company]
            annual = {"retail": "gross_cents", "saas": "recognized_cents", "marketplace": "platform_fee_cents"}[self.company]
            db.execute(f"CREATE VIEW semantic_transactions AS SELECT t.*, {net} AS net_amount_cents, {annual}*12 AS arr_cents, gross_cents-refund_cents-tax_cents+credit_cents AS draft_net_cents, gross_cents-refund_cents AS deprecated_net_cents FROM transactions AS t")
            db.executemany("INSERT INTO semantic_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                (s["resource"], s["metric_id"], "Revenue", s["definition"], s["owner"], s["grain"], s["currency"],
                 s["population"], s["time_semantics"], s["revision"], s["status"], s["measure"], s["where"]) for s in specs])
            self._seed_rows(db)
            db.executemany("INSERT INTO fixture_meta VALUES (?,?)", [("company", self.company), ("seed", str(self.seed))])

    def _seed_rows(self, db: sqlite3.Connection) -> None:
        rng = random.Random(self.seed + list(_PROFILES).index(self.company) * 7919)
        p = self.profile
        currency_rows = p["currencies"]
        classes = {
            "retail": ("merchandise", "merchandise", "merchandise", "shipping", "gift_card"),
            "saas": ("subscription", "subscription", "subscription", "usage", "setup"),
            "marketplace": ("platform_fee", "platform_fee", "platform_fee", "seller_order", "seller_adjustment"),
        }[self.company]
        rows = []
        for _ in range(48):
            category = rng.choice(classes)
            status = rng.choice(("posted", "posted", "posted", "pending"))
            if self.company == "marketplace" and status == "posted":
                status = "settled"
            eligible = int(rng.random() > 0.08)
            currency, fx_micros = rng.choice(currency_rows)
            gross = rng.randint(p["low"], p["high"])
            refund = int(gross * rng.uniform(0, 0.10))
            recognized = int(gross * rng.uniform(0.84, 0.99))
            credit = int(recognized * rng.uniform(0, 0.05))
            fee = int(gross * rng.uniform(0.07, 0.18))
            fee_refund = int(fee * rng.uniform(0, 0.10))
            tax_base = fee if self.company == "marketplace" else gross
            tax = int(tax_base * rng.uniform(0.04, 0.13))
            for period, trend in ((_PREVIOUS, 1.0), (_CURRENT, 1.02)):
                rows.append((period, category, status, eligible, 1, currency, fx_micros, 10_000,
                             _scaled(gross, trend), _scaled(refund, trend), _scaled(tax, trend),
                             _scaled(credit, trend), _scaled(recognized, trend), _scaled(fee, trend),
                             _scaled(fee_refund, trend), _scaled(gross, trend)))
        db.executemany("INSERT INTO transactions(period,revenue_class,status,eligible,available,currency,fx_micros,activity_bp,gross_cents,refund_cents,tax_cents,credit_cents,recognized_cents,platform_fee_cents,fee_refund_cents,gmv_cents) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        db.executemany("INSERT INTO period_coverage VALUES (?,?,?)", [(_PREVIOUS, 48, 48), (_CURRENT, 48, 48)])

    def set_condition(self, name: str) -> None:
        """Select one source state: quiet, decline, gap, or definition_conflict."""
        if name not in {"quiet", "decline", "gap", "definition_conflict"}:
            raise ValueError("condition must be quiet, decline, gap, or definition_conflict")
        with self._connect() as db:
            db.execute("UPDATE transactions SET activity_bp=10000,available=1")
            db.execute("DELETE FROM definition_conflicts")
            db.execute("UPDATE period_coverage SET available_rows=required_rows")
            if name == "decline":
                db.execute("UPDATE transactions SET activity_bp=8200 WHERE period=?", (_CURRENT,))
            elif name == "gap":
                db.execute("UPDATE transactions SET available=0 WHERE period=? AND id IN (SELECT id FROM transactions WHERE period=? ORDER BY id DESC LIMIT 12)", (_CURRENT, _CURRENT))
                db.execute("UPDATE period_coverage SET available_rows=36 WHERE period=?", (_CURRENT,))
            elif name == "definition_conflict":
                db.execute("INSERT INTO definition_conflicts VALUES (?,?,?,?,?,?)", (self.metric_id, "Consolidation Accounting", "r4", "Invoice billings less issued credits, with tax included and adjustments assigned to invoice month.", "Posted invoice billings across subscriptions and usage, including tax.", "Invoice issue month rather than service or settlement month."))

    def _definition_rows(self) -> list[sqlite3.Row]:
        with self._connect() as db:
            return list(db.execute("SELECT * FROM semantic_metrics ORDER BY resource"))

    def _conflict(self) -> sqlite3.Row | None:
        with self._connect() as db:
            return db.execute("SELECT * FROM definition_conflicts WHERE metric_id=?", (self.metric_id,)).fetchone()

    def _contract(self, row: sqlite3.Row, coverage: str = "complete", detail: str = "") -> ResourceContract:
        conflict = self._conflict() if row["resource"] == self.canonical_resource else None
        scope = f"Owner: {row['owner']}; currency: {row['currency']}; time: {row['time_semantics']}; revision: {row['revision']} ({row['status']}). Synthetic SQLite semantic fixture; not a live dbt/Cube connector."
        lineage = [f"semantic-metric:{row['metric_id']}:{row['revision']}", "sqlite-view:semantic_transactions"]
        if conflict:
            scope += f" Conflicting source definition: {conflict['owner']} revision {conflict['revision']}."
            lineage.append(f"semantic-metric-conflict:{conflict['revision']}")
        comp = SourceComparisonContract(
            key="net-revenue-calendar-month" if row["resource"] == self.canonical_resource else f"{row['metric_id']}-calendar-month",
            metric=row["metric_id"], definition=row["definition"], population=row["population"], unit=row["currency"],
            comparison_window="previous_period", coverage=coverage, comparable=coverage == "complete", detail=detail,
            query_refs=[f"semantic-metric:{row['metric_id']}:{row['revision']}"],
        )
        return ResourceContract(tenant_id=self.tenant_id, domain=self.profile["domain"], scope=scope,
            # The MCP reader executes the complete source-owned export (filters,
            # FX and minor-unit conversion). Raw ledger columns are not valid
            # MetricQueryPlan definitions and must not be advertised as such.
            metric_names=[row["metric_id"]], comparison_contracts=[comp],
            available_comparison_windows=["previous_period"], required_comparison_keys=[comp.key],
            population=row["population"], grain=row["grain"], lineage=lineage,
            roles=["primary_metric" if row["resource"] == self.canonical_resource else "metric_context"], authorized=True)

    def descriptors(self) -> list[dict[str, Any]]:
        """Return ResourceDescriptor JSON with no measurements or evaluation labels."""
        return [ResourceDescriptor(
            adapter=self.name, resource=r["resource"], kind="semantic_metric", title=r["title"],
            description=f"{r['definition']} Synthetic SQLite fixture; not a live dbt/Cube connector.",
            metadata={"semantic_metric_id": r["metric_id"], "semantic_revision": r["revision"], "semantic_owner": r["owner"],
                      "reporting_currency": r["currency"], "time_semantics": r["time_semantics"], "semantic_status": r["status"]},
            contract=self._contract(r),
        ).model_dump(mode="json") for r in self._definition_rows()]

    def notes(self) -> list[dict[str, Any]]:
        row = next(r for r in self._definition_rows() if r["resource"] == self.canonical_resource)
        refs = [f"{self.name}|{self.canonical_resource}"]
        notes = [{"id": "semantic-metric-definition", "title": "Revenue definition", "body": row["definition"], "status": row["status"], "source_refs": refs, "provenance": [f"sqlite:semantic_metrics:{row['metric_id']}:{row['revision']}"]},
                 {"id": "finance-monitoring-policy", "title": "Finance monitoring policy", "body": self.business_policy, "status": "active", "source_refs": refs, "provenance": ["sqlite:source-owned-business-policy:v1"]}]
        conflict = self._conflict()
        if conflict:
            notes.append({"id": "competing-semantic-definition", "title": "Consolidation definition", "body": conflict["definition"],
                          "status": "active", "source_refs": refs, "provenance": [f"sqlite:definition_conflicts:{conflict['revision']}"]})
        return notes

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        if source.adapter != self.name:
            raise ValueError("source adapter does not match this company fixture")
        row = next((item for item in self._definition_rows() if item["resource"] == source.resource), None)
        if row is None:
            raise ValueError("unknown semantic metric resource")
        query = f"SELECT period,SUM({row['measure']}*fx_micros*activity_bp/{_CONVERSION_SCALE}.0) AS amount FROM semantic_transactions WHERE period IN (?,?) AND available=1 AND ({row['filter_sql']}) GROUP BY period ORDER BY period"
        with self._connect() as db:
            values = {item["period"]: item["amount"] for item in db.execute(query, (_CURRENT, _PREVIOUS))}
            coverage = {item["period"]: dict(item) for item in db.execute(
                "SELECT period,required_rows,available_rows FROM period_coverage WHERE period IN (?,?)", (_CURRENT, _PREVIOUS))}
        current, previous = _money(values.get(_CURRENT, 0)), _money(values.get(_PREVIOUS, 0))
        delta = _money(current - previous)
        change = _money(delta / previous * 100) if previous else None
        partial = any(item["available_rows"] < item["required_rows"] for item in coverage.values())
        state = "partial" if partial else "complete"
        detail = "; ".join(
            f"{period}: {entry['available_rows']} of {entry['required_rows']} ledger records available"
            for period, entry in sorted(coverage.items()) if entry["available_rows"] < entry["required_rows"]
        )
        contract = self._contract(row, state, detail)
        now = datetime.now(timezone.utc)
        sql_hash = hashlib.sha256(query.encode()).hexdigest()
        provenance = [f"sqlite:{self.tenant_id}:semantic_transactions", f"sql-sha256:{sql_hash}", f"semantic-metric:{row['metric_id']}:{row['revision']}"]
        observation = Observation(source_key=source.key, subject_id=row["metric_id"], subject_label="Revenue", subject_type="metric",
            metric=row["metric_id"], unit=row["currency"], current=float(current), baseline=float(previous), previous=float(previous),
            change_pct=float(change) if change is not None else None, comparison_baselines={"previous_period": float(previous)},
            dimensions={"period": _CURRENT, "baseline_period": _PREVIOUS},
            attributes={"semantic_revision": row["revision"], "semantic_owner": row["owner"], "reporting_currency": row["currency"],
                "population": row["population"], "grain": row["grain"], "time_semantics": row["time_semantics"],
                "historical_measurements": True, "archival_mode_required": True})
        evidence = [Evidence(source_key=source.key, subject_id=row["metric_id"], subject_label="Revenue",
            statement=f"Source aggregate for {_CURRENT}: {current} {row['currency']}; {_PREVIOUS}: {previous} {row['currency']}." + (f" Coverage: {detail}." if detail else ""),
            values={"current_period": _CURRENT, "current": float(current), "previous_period": _PREVIOUS, "previous": float(previous),
                    "delta": float(delta), "change_pct": float(change) if change is not None else None, "unit": row["currency"],
                    "semantic_metric_id": row["metric_id"], "metric_revision": row["revision"], "query_sql": query, "query_sha256": sql_hash}, provenance=provenance)]
        availability = "; ".join(
            f"{period}: {item['available_rows']} of {item['required_rows']} ledger records available"
            for period, item in sorted(coverage.items())
        )
        evidence.append(Evidence(source_key=source.key, subject_id="period-coverage", subject_label="Export availability",
                                 statement=availability + ". These counts precede metric-population filters; they are not contributing-record counts.",
                                 values={"period_coverage": coverage, "basis": "ledger availability before metric filters"}, provenance=provenance))
        conflict = self._conflict() if row["resource"] == self.canonical_resource else None
        if conflict:
            evidence.append(Evidence(source_key=source.key, subject_id=row["metric_id"], subject_label="Revenue definition record",
                statement=f"A source definition from {conflict['owner']} is recorded at revision {conflict['revision']}.",
                values={k: conflict[k] for k in ("owner", "revision", "definition", "population", "time_semantics")}, provenance=provenance))
        return ResourceSnapshot(source_key=source.key, adapter=source.adapter, resource=source.resource, title=row["title"],
            description=f"Synthetic SQLite semantic metric for {self.profile['company_name']}; historical months, not a live dbt/Cube connector.",
            observations=[observation], evidence=evidence,
            metadata={"source_identity": {"tenant_id": self.tenant_id, "adapter": source.adapter, "resource": source.resource,
                "semantic_metric_id": row["metric_id"]}, "source_sql": query, "metric_revision": row["revision"],
                "query_sha256": sql_hash, "retrieved_at_utc": now.isoformat(),
                "measurement_periods": {"current": "2026-09-01/2026-09-30", "previous": "2026-08-01/2026-08-31"},
                "measurement_coverage": coverage, "historical_measurements": True,
                "archival_mode_required": True, "live_connector": False},
            captured_at=now, source_captured_at=now, contract=contract)

    def expected(self, resource: str | None = None) -> dict[str, Decimal | str | None]:
        """Independent Python/Decimal oracle; no SQL aggregate or inspect reuse."""
        resource = resource or self.canonical_resource
        definitions = {r["resource"]: r for r in self._definition_rows()}
        if resource not in definitions:
            raise ValueError("unknown semantic metric resource")
        metric_id = definitions[resource]["metric_id"]
        p = self.profile
        totals = {_CURRENT: Decimal(0), _PREVIOUS: Decimal(0)}
        with self._connect() as db:
            rows = db.execute(
                "SELECT period,revenue_class,status,eligible,available,fx_micros,activity_bp,gross_cents,refund_cents,tax_cents,credit_cents,recognized_cents,platform_fee_cents,fee_refund_cents FROM transactions WHERE period IN (?,?)", (_CURRENT, _PREVIOUS))
            for row in rows:
                settled = row["status"] in {"posted", "settled"}
                canonical = resource == self.canonical_resource
                if not row["available"] or (canonical and (
                    row["revenue_class"] != p["category"] or row["status"] != p["status"] or not row["eligible"]
                )) or (resource in _RESOURCES[1:3] + (_RESOURCES[5],) and not settled) or (
                    resource in _RESOURCES[3:5] and (not row["eligible"] or not settled)
                ):
                    continue
                if resource == _RESOURCES[2] and self.company == "marketplace" and row["revenue_class"] != "seller_order":
                    continue
                amounts = {
                    self.canonical_resource: {
                        "retail": row["gross_cents"] - row["refund_cents"] - row["tax_cents"],
                        "saas": row["recognized_cents"] - row["refund_cents"] - row["credit_cents"],
                        "marketplace": row["platform_fee_cents"] - row["fee_refund_cents"] - row["tax_cents"],
                    }[self.company],
                    _RESOURCES[1]: row["gross_cents"], _RESOURCES[2]: row["gross_cents"],
                    _RESOURCES[3]: {"retail": row["gross_cents"], "saas": row["recognized_cents"], "marketplace": row["platform_fee_cents"]}[self.company] * 12,
                    _RESOURCES[4]: row["gross_cents"] - row["refund_cents"] - row["tax_cents"] + row["credit_cents"],
                    _RESOURCES[5]: row["gross_cents"] - row["refund_cents"],
                }
                amount = amounts[resource]
                # Independent dimensional conversion, not the SQL denominator:
                # minor units -> currency units -> reporting FX -> activity ratio.
                converted = (Decimal(amount) / Decimal(100)
                             * (Decimal(row["fx_micros"]) / Decimal(1_000_000))
                             * (Decimal(row["activity_bp"]) / Decimal(10_000)))
                totals[row["period"]] += converted
        current, previous = _money(totals[_CURRENT]), _money(totals[_PREVIOUS])
        delta = _money(current - previous)
        change = _money(delta / previous * 100) if previous else None
        return {"resource": resource, "metric_id": metric_id, "current": current, "previous": previous,
                "delta": delta, "change_pct": change, "current_period": _CURRENT, "previous_period": _PREVIOUS, "unit": self.unit}
