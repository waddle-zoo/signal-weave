from __future__ import annotations

import pytest

import scripts.preset_bootstrap_check as bootstrap
from signalweave.hosted import HostedDataPolicy
from signalweave.models import ResourceSnapshot
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
        requests_made = 0

        async def list_dashboards_page(self, *, page, page_size, query=None):
            self.requests_made += 1
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
    assert report["checks"]["provider_transport_used"] is True
    assert report["provider_requests"]["for_bootstrap"] == 1
    assert calls == [(0, 20)]


@pytest.mark.asyncio
async def test_bootstrap_preflight_auto_detects_custom_sole_preset_adapter(monkeypatch):
    class Client:
        requests_made = 0

        async def list_dashboards_page(self, *, page, page_size, query=None):
            self.requests_made += 1
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
async def test_bootstrap_preflight_rejects_client_without_provider_telemetry(monkeypatch):
    class Client:
        async def list_dashboards_page(self, *, page, page_size, query=None):
            return ([{"id": 7, "dashboard_title": "Growth"}], 1)

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy()
    adapter.name = "preset__preset-env"
    _wire_environment(monkeypatch, adapter)

    with pytest.raises(RuntimeError, match="provider request telemetry"):
        await bootstrap.run(adapter_name="preset__preset-env", page_size=20)


@pytest.mark.asyncio
async def test_bootstrap_preflight_fails_empty_workspace(monkeypatch):
    class Client:
        requests_made = 0

        async def list_dashboards_page(self, *, page, page_size, query=None):
            self.requests_made += 1
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
        id = "101"
        error = None
        semantic_status = "extracted"
        observations = [object()]

    class Snapshot:
        charts = [Chart()]

    class Client:
        requests_made = 0

        async def list_dashboards_page(self, *, page, page_size, query=None):
            self.requests_made += 1
            return ([{"id": 7, "dashboard_title": "Growth"}], 1)

        async def dashboard_snapshot(self, dashboard_id, *, include_data, chart_ids):
            self.requests_made += 1
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
async def test_provider_smoke_rejects_provider_returning_a_different_chart(monkeypatch):
    class Chart:
        id = "999"
        error = None
        semantic_status = "extracted"
        observations = [object()]

    class Snapshot:
        charts = [Chart()]

    class Client:
        requests_made = 0

        async def list_dashboards_page(self, *, page, page_size, query=None):
            self.requests_made += 1
            return ([{"id": 7, "dashboard_title": "Growth"}], 1)

        async def dashboard_snapshot(self, dashboard_id, *, include_data, chart_ids):
            self.requests_made += 1
            assert str(dashboard_id) == "7"
            assert include_data is True
            assert chart_ids == ["101"]
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
    assert report["chart_probe"] == {
        "dashboard_id": "7",
        "chart_id": "101",
        "returned_chart_id": "999",
        "error": (
            "the provider returned a different chart than requested; "
            "the chart-scope probe cannot be trusted"
        ),
        "passed": False,
    }


@pytest.mark.asyncio
async def test_provider_smoke_does_not_bypass_metadata_only_policy(monkeypatch):
    calls = 0

    class Client:
        requests_made = 0

        async def list_dashboards_page(self, *, page, page_size, query=None):
            self.requests_made += 1
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
        requests_made = 0

        async def list_dashboards_page(self, *, page, page_size, query=None):
            self.requests_made += 1
            return ([{"id": 7, "dashboard_title": "Growth"}], 1)

        async def dashboard_snapshot(self, *args, **kwargs):
            self.requests_made += 1
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


@pytest.mark.asyncio
async def test_provider_smoke_explains_missing_saved_query_context(monkeypatch):
    class Chart:
        id = "101"
        error = "Data unavailable: Chart has no query context saved. Please save the chart again."
        semantic_status = "unsupported"
        observations = []

    class Snapshot:
        charts = [Chart()]

    class Client:
        requests_made = 0

        async def list_dashboards_page(self, *, page, page_size, query=None):
            self.requests_made += 1
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
    assert "Re-save the chart" in report["chart_probe"]["remediation"]
    assert "unscoped fallback" in report["chart_probe"]["remediation"]


@pytest.mark.asyncio
async def test_dashboard_readiness_reports_all_chart_remediations(monkeypatch):
    class Client:
        requests_made = 0

        async def list_dashboards_page(self, *, page, page_size, query=None):
            self.requests_made += 1
            return ([{"id": 7, "dashboard_title": "Growth"}], 1)

    async def inspect(source):
        assert source.resource == "dashboard:7"
        return ResourceSnapshot(
            source_key=source.key,
            adapter="preset__preset-env",
            resource=source.resource,
            title="Growth",
            metadata={
                "data_quality": {
                    "status": "partial",
                    "chart_count": 3,
                    "charts_with_observations": 2,
                    "chart_errors": [
                        "Legacy chart: Chart has no query context saved. Please save the chart again."
                    ],
                    "semantic_issues": [],
                }
            },
        )

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy()
    adapter.name = "preset__preset-env"
    adapter.inspect = inspect
    _wire_environment(monkeypatch, adapter)

    report = await bootstrap.run(
        adapter_name="preset__preset-env",
        page_size=20,
        dashboard_id="7",
    )

    assert report["passed"] is False
    assert report["chart_probe"] is None
    assert report["dashboard_probe"]["chart_count"] == 3
    assert report["dashboard_probe"]["charts_with_observations"] == 2
    assert report["dashboard_probe"]["remediations"]
    assert report["checks"]["dashboard_readiness_probe"] is False
    assert report["not_proven"][0] == "business usefulness beyond the dashboard readiness probe"
