from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .engine import InsightEngine
from .models import PrincipalContext, ResourceDescriptor
from .sources import SourceAdapter, SourceRegistry
from .store import (
    CertificationReportStore,
    DecisionReceiptStore,
    InsightCardStore,
    JsonCertificationReportStore,
    JsonDecisionReceiptStore,
    JsonInsightCardStore,
    JsonMetricQueryCardStore,
    MetricQueryCardStore,
    SQLiteCertificationReportStore,
    SQLiteDecisionReceiptStore,
    SQLiteInsightCardStore,
    SQLiteMetricQueryCardStore,
)
from .superset_adapter import SupersetAdapter
from .superset_client import SupersetClient
from .trino_adapter import HttpxTrinoExecutor, TrinoQueryAdapter
from .typesafe_adapter import JevJudger, load_api_key


@dataclass
class Runtime:
    card_store: InsightCardStore
    sources: SourceRegistry
    engine: InsightEngine
    metric_query_store: MetricQueryCardStore | None = None
    decision_receipts: DecisionReceiptStore | None = None
    certification_reports: CertificationReportStore | None = None
    principal: PrincipalContext | None = None


def build_runtime(
    mode: str | None = None,
    *,
    adapters: Iterable[SourceAdapter] = (),
) -> Runtime:
    """Build the Jev runtime around the source adapters a deployment installs.

    Superset is the first shipped adapter, not a runtime requirement. Embedded
    deployments can pass adapters for Looker, Hex, a data catalog, or an
    internal artifact gateway here. The environment-driven CLI still registers
    Superset and Trino when their connector settings are present.
    """
    mode = (mode or os.getenv("TYPESAFE_MODE", "jev")).lower()
    if mode == "jev":
        key = load_api_key()
        if not key:
            raise RuntimeError(
                "TYPESAFE_MODE=jev requires TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE"
            )
        judger = JevJudger(api_key=key)
    else:
        raise ValueError("SignalWeave production runtime only supports TYPESAFE_MODE=jev")
    configured_adapters = list(adapters)
    url = os.getenv("SUPERSET_URL")
    configured_names = {adapter.name for adapter in configured_adapters}
    if url and "superset" not in configured_names:
        configured_adapters.append(
            SupersetAdapter(
                SupersetClient(
                    base_url=url,
                    username=os.getenv("SUPERSET_USERNAME"),
                    password=os.getenv("SUPERSET_PASSWORD"),
                )
            )
        )
    tenant_id = os.getenv("SIGNALWEAVE_TENANT_ID")
    principal_id = os.getenv("SIGNALWEAVE_PRINCIPAL_ID")
    if bool(tenant_id) != bool(principal_id):
        raise RuntimeError(
            "SIGNALWEAVE_TENANT_ID and SIGNALWEAVE_PRINCIPAL_ID must be configured together"
        )
    registry = SourceRegistry(
        configured_adapters,
        authorized_tenants=[tenant_id] if tenant_id else None,
    )
    trino_url = os.getenv("TRINO_URL")
    trino_catalog_file = os.getenv("TRINO_CATALOG_FILE")
    if trino_url and trino_catalog_file:
        payload = json.loads(Path(trino_catalog_file).read_text())
        if not isinstance(payload, list):
            raise ValueError("TRINO_CATALOG_FILE must contain a JSON list of resource descriptors")
        trino_resources = [ResourceDescriptor.model_validate(item) for item in payload]
        registry.register(
            TrinoQueryAdapter(
                trino_resources,
                HttpxTrinoExecutor(
                    trino_url,
                    user=os.getenv("TRINO_USER", "signal-weave"),
                    catalog=os.getenv("TRINO_CATALOG"),
                    schema=os.getenv("TRINO_SCHEMA"),
                    max_rows=int(os.getenv("TRINO_MAX_ROWS", "1000")),
                ),
            )
        )
    if not registry.adapter_names():
        raise RuntimeError(
            "SignalWeave production runtime requires at least one source adapter; "
            "configure SUPERSET_URL, a Trino catalog, or pass adapters to build_runtime"
        )
    store_backend = os.getenv("SIGNALWEAVE_STORE_BACKEND", "sqlite").lower()
    if store_backend == "sqlite":
        store_path = os.getenv("SIGNALWEAVE_STORE_PATH", "data/signalweave.db")
        card_store = SQLiteInsightCardStore(store_path)
        decision_receipts: DecisionReceiptStore = SQLiteDecisionReceiptStore(store_path)
        certification_reports: CertificationReportStore = SQLiteCertificationReportStore(store_path)
        metric_query_store: MetricQueryCardStore = SQLiteMetricQueryCardStore(store_path)
    elif store_backend == "json":
        card_store = JsonInsightCardStore(
            os.getenv("INSIGHT_CARD_STORE", "data/insight-cards.json")
        )
        decision_receipts = JsonDecisionReceiptStore(
            os.getenv("DECISION_RECEIPT_STORE", "data/decision-receipts.json")
        )
        certification_reports = JsonCertificationReportStore(
            os.getenv("CERTIFICATION_REPORT_STORE", "data/certification-reports.json")
        )
        metric_query_store = JsonMetricQueryCardStore(
            os.getenv("METRIC_QUERY_CARD_STORE", "data/metric-query-cards.json")
        )
    else:
        raise ValueError("SIGNALWEAVE_STORE_BACKEND must be sqlite or json")
    return Runtime(
        card_store=card_store,
        sources=registry,
        engine=InsightEngine(judger=judger, registry=registry),
        metric_query_store=metric_query_store,
        decision_receipts=decision_receipts,
        certification_reports=certification_reports,
        principal=(
            PrincipalContext(principal_id=principal_id, tenant_id=tenant_id)
            if principal_id and tenant_id
            else None
        ),
    )
