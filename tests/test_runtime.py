import pytest

from signalweave.models import ResourceSnapshot
from signalweave.runtime import build_runtime
from signalweave.store import (
    SQLiteDecisionReceiptStore,
    SQLiteInsightCardStore,
    SQLiteMetricQueryCardStore,
)


def test_runtime_requires_jev_credentials_by_default(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)

    with pytest.raises(RuntimeError, match="requires TYPESAFE_API_KEY"):
        build_runtime()


def test_runtime_rejects_non_jev_mode():
    with pytest.raises(ValueError, match="only supports TYPESAFE_MODE=jev"):
        build_runtime(mode="other")


def test_runtime_requires_a_source_adapter_after_jev_credentials(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)

    with pytest.raises(RuntimeError, match="at least one source adapter"):
        build_runtime()


def test_runtime_requires_principal_with_tenant_scope(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_TENANT_ID", "acme")
    monkeypatch.delenv("SIGNALWEAVE_PRINCIPAL_ID", raising=False)

    with pytest.raises(RuntimeError, match="must be configured together"):
        build_runtime(adapters=[])


def test_runtime_accepts_an_embedded_non_superset_adapter(monkeypatch, tmp_path):
    class InternalArtifacts:
        name = "internal-analytics"

        async def list_resources(self):
            return []

        async def inspect(self, source):
            return ResourceSnapshot(
                source_key=source.key,
                adapter=self.name,
                resource=source.resource,
                title=source.label,
            )

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    runtime = build_runtime(adapters=[InternalArtifacts()])

    assert runtime.sources.adapter_names() == ["internal-analytics"]


def test_runtime_defaults_all_card_and_receipt_stores_to_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("SUPERSET_URL", "http://superset")
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    runtime = build_runtime()

    assert isinstance(runtime.card_store, SQLiteInsightCardStore)
    assert isinstance(runtime.metric_query_store, SQLiteMetricQueryCardStore)
    assert isinstance(runtime.decision_receipts, SQLiteDecisionReceiptStore)
