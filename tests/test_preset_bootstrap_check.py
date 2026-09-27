from __future__ import annotations

import pytest

import scripts.preset_bootstrap_check as bootstrap
from signalweave.hosted import HostedDataPolicy
from signalweave.preset_adapter import PresetAdapter


def _wire_environment(monkeypatch, adapter):
    monkeypatch.setattr(
        bootstrap,
        "validate_preset_environment",
        lambda: {"tenant_id": "northstar", "principal_mode": "static"},
    )
    monkeypatch.setattr(
        bootstrap, "build_preset_adapter_from_environment", lambda: adapter
    )


@pytest.mark.asyncio
async def test_bootstrap_preflight_reads_one_catalog_page_without_jev(monkeypatch, tmp_path):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    calls: list[tuple[int, int]] = []

    class Client:
        async def list_dashboards_page(self, *, page, page_size, query=None):
            calls.append((page, page_size))
            assert query is None
            return ([{"id": 7, "dashboard_title": "Growth"}], 1)

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy()
    adapter.name = "preset__preset-env"
    _wire_environment(monkeypatch, adapter)

    report = await bootstrap.run(
        adapter_name="preset__preset-env",
        page_size=20,
        output=tmp_path / "bootstrap.json",
    )

    assert report["passed"] is True
    assert report["jev_requests"] == 0
    assert calls == [(0, 20)]


@pytest.mark.asyncio
async def test_bootstrap_preflight_auto_detects_custom_sole_preset_adapter(monkeypatch):
    class Client:
        async def list_dashboards_page(self, *, page, page_size, query=None):
            return ([{"id": 7, "dashboard_title": "Growth"}], 1)

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy()
    adapter.name = "preset__customer-workspace"
    _wire_environment(monkeypatch, adapter)

    report = await bootstrap.run(adapter_name=None, page_size=20)

    assert report["passed"] is True
    assert report["adapter"] == "preset__customer-workspace"


@pytest.mark.asyncio
async def test_bootstrap_preflight_fails_empty_workspace(monkeypatch):
    class Client:
        async def list_dashboards_page(self, *, page, page_size, query=None):
            return ([], 0)

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy()
    adapter.name = "preset__preset-env"
    _wire_environment(monkeypatch, adapter)

    report = await bootstrap.run(adapter_name="preset__preset-env", page_size=20)

    assert report["passed"] is False
    assert report["catalog"]["provider_count"] == 0


@pytest.mark.asyncio
async def test_provider_smoke_probes_one_dashboard_chart_without_jev(monkeypatch):
    calls: list[tuple[str, bool, list[str]]] = []

    class Chart:
        error = None
        semantic_status = "extracted"
        observations = [object()]

    class Snapshot:
        charts = [Chart()]

    class Client:
        async def list_dashboards_page(self, *, page, page_size, query=None):
            return ([{"id": 7, "dashboard_title": "Growth"}], 1)

        async def dashboard_snapshot(self, dashboard_id, *, include_data, chart_ids):
            calls.append((str(dashboard_id), include_data, chart_ids))
            return Snapshot()

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy()
    adapter.name = "preset__preset-env"
    _wire_environment(monkeypatch, adapter)

    report = await bootstrap.run(
        adapter_name="preset__preset-env",
        page_size=20,
        dashboard_id="7",
        chart_id="101",
    )

    assert report["passed"] is True
    assert report["chart_probe"]["passed"] is True
    assert report["checks"]["jev_calls_made"] is True
    assert calls == [("7", True, ["101"])]


@pytest.mark.asyncio
async def test_provider_smoke_does_not_bypass_metadata_only_policy(monkeypatch):
    calls = 0

    class Client:
        async def list_dashboards_page(self, *, page, page_size, query=None):
            return ([{"id": 7, "dashboard_title": "Growth"}], 1)

        async def dashboard_snapshot(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            raise AssertionError("metadata-only probe must not read chart data")

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy(mode="metadata_only")
    adapter.name = "preset__preset-env"
    _wire_environment(monkeypatch, adapter)

    report = await bootstrap.run(
        adapter_name="preset__preset-env",
        page_size=20,
        dashboard_id="7",
        chart_id="101",
    )

    assert report["passed"] is False
    assert report["chart_probe"]["passed"] is False
    assert "metadata_only" in report["chart_probe"]["error"]
    assert calls == 0


@pytest.mark.asyncio
async def test_provider_smoke_reports_missing_chart_instead_of_index_error(monkeypatch):
    class Snapshot:
        charts = []

    class Client:
        async def list_dashboards_page(self, *, page, page_size, query=None):
            return ([{"id": 7, "dashboard_title": "Growth"}], 1)

        async def dashboard_snapshot(self, *args, **kwargs):
            return Snapshot()

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy()
    adapter.name = "preset__preset-env"
    _wire_environment(monkeypatch, adapter)

    report = await bootstrap.run(
        adapter_name="preset__preset-env",
        page_size=20,
        dashboard_id="7",
        chart_id="101",
    )

    assert report["passed"] is False
    assert report["chart_probe"]["error"] == "the dashboard returned no matching chart"
