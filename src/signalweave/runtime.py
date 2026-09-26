from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .context import ContextProvider
from .engine import InsightEngine
from .hosted import (
    HostedAuthMode,
    HostedConnection,
    HostedCredentialVault,
    HostedDataMode,
    HostedDataPolicy,
    HostedProvider,
    InMemoryCredentialVault,
    build_hosted_adapters,
)
from .models import PrincipalContext, ResourceDescriptor
from .sources import SourceAdapter, SourceRegistry
from .store import (
    CertificationReportStore,
    DecisionFeedbackStore,
    DecisionReceiptStore,
    InsightCardStore,
    JsonCertificationReportStore,
    JsonDecisionFeedbackStore,
    JsonDecisionReceiptStore,
    JsonInsightCardStore,
    JsonMetricQueryCardStore,
    MetricQueryCardStore,
    SQLiteCertificationReportStore,
    SQLiteDecisionFeedbackStore,
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
    decision_feedback: DecisionFeedbackStore | None = None
    certification_reports: CertificationReportStore | None = None
    context_provider: ContextProvider | None = None
    principal: PrincipalContext | None = None


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean value")


def _env_secret(name: str) -> str | None:
    """Read a deployment secret from one value or one mounted secret file."""

    value = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if value and file_name:
        raise RuntimeError(f"set only one of {name} or {name}_FILE")
    if file_name:
        try:
            value = Path(file_name).read_text(encoding="utf-8").strip()
        except OSError as error:
            raise RuntimeError(f"could not read {name}_FILE: {file_name}") from error
    return value or None


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, str(default)).strip()
    try:
        return int(value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error


def _preset_from_environment() -> tuple[HostedConnection, HostedCredentialVault] | None:
    """Build one tenant-bound Preset connection from deployment secrets.

    This is deliberately an environment bootstrap, not a connection-control
    plane. Secrets are read into an in-memory vault and never persisted in the
    card or connection stores. Shared deployments should use the explicit
    ``hosted_connections``/vault arguments backed by their own secret manager.
    """
    base_url = os.getenv("PRESET_URL", "").strip()
    if not base_url:
        return None
    access_token = _env_secret("PRESET_ACCESS_TOKEN")
    token_name = _env_secret("PRESET_API_TOKEN_NAME")
    token_secret = _env_secret("PRESET_API_TOKEN_SECRET")
    if not access_token and not (token_name and token_secret):
        raise RuntimeError(
            "PRESET_URL requires PRESET_ACCESS_TOKEN or both "
            "PRESET_API_TOKEN_NAME and PRESET_API_TOKEN_SECRET"
        )
    try:
        mode = HostedDataMode(os.getenv("PRESET_DATA_MODE", "cached_results").strip())
    except ValueError as error:
        choices = ", ".join(item.value for item in HostedDataMode)
        raise RuntimeError(f"PRESET_DATA_MODE must be one of: {choices}") from error
    policy = HostedDataPolicy(
        mode=mode,
        allow_live_queries=_env_flag("PRESET_ALLOW_LIVE_QUERIES"),
        allow_refresh=_env_flag("PRESET_ALLOW_REFRESH"),
        retain_raw_results=_env_flag("PRESET_RETAIN_RAW_RESULTS"),
        max_result_rows=_env_int("PRESET_MAX_RESULT_ROWS", 500),
        max_snapshot_bytes=_env_int("PRESET_MAX_SNAPSHOT_BYTES", 1_000_000),
        retention_hours=_env_int("PRESET_RETENTION_HOURS", 24),
    )
    tenant_id = os.getenv("PRESET_TENANT_ID", os.getenv("SIGNALWEAVE_TENANT_ID", "default"))
    connection = HostedConnection(
        id=os.getenv("PRESET_CONNECTION_ID", "preset-env"),
        tenant_id=tenant_id,
        provider=HostedProvider.PRESET,
        base_url=base_url,
        external_workspace=os.getenv("PRESET_WORKSPACE", "preset-workspace"),
        credential_ref="env://preset",
        auth_mode=(HostedAuthMode.BEARER if access_token else HostedAuthMode.API_TOKEN),
        policy=policy,
    )
    credentials = (
        {"access_token": access_token}
        if access_token
        else {"name": token_name, "secret": token_secret}
    )
    api_base_url = os.getenv("PRESET_API_BASE_URL", "").strip()
    if api_base_url:
        credentials["api_base_url"] = api_base_url
    return connection, InMemoryCredentialVault({"env://preset": credentials})


def build_runtime(
    mode: str | None = None,
    *,
    adapters: Iterable[SourceAdapter] = (),
    context_provider: ContextProvider | None = None,
    hosted_connections: Iterable[HostedConnection] = (),
    credential_vault: HostedCredentialVault | None = None,
    http_transport: Any | None = None,
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
    hosted_connections = list(hosted_connections)
    preset_environment = _preset_from_environment()
    if preset_environment is not None:
        if hosted_connections or credential_vault is not None:
            raise RuntimeError(
                "PRESET_URL environment bootstrap cannot be combined with explicit "
                "hosted_connections or credential_vault"
            )
        preset_connection, preset_vault = preset_environment
        hosted_connections = [preset_connection]
        credential_vault = preset_vault
    if hosted_connections:
        if credential_vault is None:
            raise RuntimeError(
                "hosted_connections require a credential_vault; raw source credentials "
                "must not be passed through the runtime configuration"
            )
        configured_adapters.extend(
            build_hosted_adapters(
                hosted_connections,
                credential_vault,
                transport=http_transport,
            )
        )
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
    hosted_tenants = {connection.tenant_id for connection in hosted_connections}
    default_authorized_tenants: list[str] | None
    if tenant_id:
        default_authorized_tenants = [tenant_id]
    elif len(hosted_tenants) == 1:
        default_authorized_tenants = sorted(hosted_tenants)
    elif len(hosted_tenants) > 1:
        # A shared process must never expose every hosted tenant through an
        # unscoped direct call. Request-scoped MCP principals can provide the
        # explicit tenant later; deployment code must do the same.
        default_authorized_tenants = []
    else:
        default_authorized_tenants = None
    registry = SourceRegistry(
        configured_adapters,
        authorized_tenants=default_authorized_tenants,
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
        decision_feedback: DecisionFeedbackStore = SQLiteDecisionFeedbackStore(store_path)
        certification_reports: CertificationReportStore = SQLiteCertificationReportStore(store_path)
        metric_query_store: MetricQueryCardStore = SQLiteMetricQueryCardStore(store_path)
    elif store_backend == "json":
        card_store = JsonInsightCardStore(
            os.getenv("INSIGHT_CARD_STORE", "data/insight-cards.json")
        )
        decision_receipts = JsonDecisionReceiptStore(
            os.getenv("DECISION_RECEIPT_STORE", "data/decision-receipts.json")
        )
        decision_feedback = JsonDecisionFeedbackStore(
            os.getenv("DECISION_FEEDBACK_STORE", "data/decision-feedback.json")
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
        engine=InsightEngine(
            judger=judger,
            registry=registry,
            context_provider=context_provider,
        ),
        metric_query_store=metric_query_store,
        decision_receipts=decision_receipts,
        decision_feedback=decision_feedback,
        certification_reports=certification_reports,
        context_provider=context_provider,
        principal=(
            PrincipalContext(principal_id=principal_id, tenant_id=tenant_id)
            if principal_id and tenant_id
            else None
        ),
    )
