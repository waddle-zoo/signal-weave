from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

import scripts.preset_bootstrap_check as bootstrap
from evaluations.preset_hosted_trial import WorkspaceTransport, _load_fixture
from signalweave.hosted import HostedDataPolicy
from signalweave.models import ResourceSnapshot
from signalweave.preset_adapter import PresetAdapter, PresetCloudClient


def _wire_environment(monkeypatch, adapter):
    monkeypatch.setattr(
        bootstrap,
        "validate_preset_environment",
        lambda: {"tenant_id": "northstar", "principal_mode": "static"},
    )
    monkeypatch.setattr(
        bootstrap, "build_preset_adapter_from_environment", lambda: adapter
    )


def _healthy_snapshot():
    return SimpleNamespace(
        metadata={
            "data_quality": {
                "status": "healthy",
                "chart_count": 2,
                "charts_with_observations": 2,
                "chart_errors": [],
                "semantic_issues": [],
            }
        },
        error=None,
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
async def test_bootstrap_reports_redacted_permission_failure(monkeypatch, tmp_path):
    request = httpx.Request("GET", "https://workspace.preset.test/api/v1/dashboard/")
    response = httpx.Response(
        403,
        json={"message": "token-secret-must-not-appear"},
        request=request,
    )

    class Client:
        requests_made = 1

        async def list_dashboards_page(self, *, page, page_size, query=None):
            raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy()
    adapter.name = "preset__preset-env"
    _wire_environment(monkeypatch, adapter)

    output = tmp_path / "bootstrap-failure.json"
    report = await bootstrap.run(
        adapter_name="preset__preset-env",
        page_size=20,
        output=output,
    )

    assert report["passed"] is False
    assert report["checks"]["provider_transport_used"] is True
    assert report["checks"]["provider_request_failed"] is True
    assert report["failure"] == {
        "category": "authentication_or_permission",
        "status_code": 403,
        "error_type": "HTTPStatusError",
        "remediation": (
            "Verify that the Preset API is enabled for the workspace, the token "
            "has access to the selected workspace and read-only assets, and the "
            "configured token mode matches the credential files."
        ),
    }
    assert report["jev_requests"] == 0
    assert "token-secret-must-not-appear" not in output.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_bootstrap_reports_transport_failure_without_stack_trace(monkeypatch):
    class Client:
        requests_made = 0

        async def list_dashboards_page(self, *, page, page_size, query=None):
            request = httpx.Request("GET", "https://workspace.preset.test/api/v1/dashboard/")
            raise httpx.ConnectTimeout("timed out", request=request)

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy()
    adapter.name = "preset__preset-env"
    _wire_environment(monkeypatch, adapter)

    report = await bootstrap.run(adapter_name="preset__preset-env", page_size=20)

    assert report["passed"] is False
    assert report["failure"]["category"] == "transport_error"
    assert report["failure"]["error_type"] == "ConnectTimeout"
    assert report["jev_requests"] == 0


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
async def test_bootstrap_preflight_rejects_non_jev_before_provider_access(monkeypatch):
    monkeypatch.setenv("TYPESAFE_MODE", "heuristic")

    class Client:
        requests_made = 0

        async def list_dashboards_page(self, *, page, page_size, query=None):
            raise AssertionError("invalid Jev mode must stop before provider access")

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy()
    adapter.name = "preset__preset-env"
    _wire_environment(monkeypatch, adapter)

    with pytest.raises(RuntimeError, match="TYPESAFE_MODE=jev"):
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
async def test_bootstrap_query_selects_one_dashboard_and_runs_readiness(monkeypatch):
    calls: list[tuple[int, str | None]] = []

    class Client:
        requests_made = 0

        async def list_dashboards_page(self, *, page, page_size, query=None):
            self.requests_made += 1
            calls.append((page, query))
            if page == 0:
                return ([{"id": 7, "dashboard_title": "Growth command center"}], 1)
            return ([], 1)

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy()
    adapter.name = "preset__preset-env"

    async def inspect(source):
        assert source.resource == "dashboard:7"
        return _healthy_snapshot()

    adapter.inspect = inspect
    _wire_environment(monkeypatch, adapter)

    report = await bootstrap.run(
        adapter_name="preset__preset-env",
        page_size=20,
        dashboard_query="growth command",
    )

    assert report["passed"] is True
    assert report["selection"] == {
        "query": "growth command",
        "matched_dashboards": [{"id": 7, "title": "Growth command center"}],
        "max_pages": 5,
        "truncated": False,
        "selected_dashboard_id": "7",
        "passed": True,
    }
    assert report["dashboard_probe"]["dashboard_id"] == "7"
    assert calls == [(0, "growth command")]


@pytest.mark.asyncio
async def test_bootstrap_query_rejects_ambiguous_dashboard_without_readiness(monkeypatch):
    inspected = False

    class Client:
        requests_made = 0

        async def list_dashboards_page(self, *, page, page_size, query=None):
            self.requests_made += 1
            return (
                [
                    {"id": 7, "dashboard_title": "Growth command center"},
                    {"id": 8, "dashboard_title": "Growth command center — EMEA"},
                ],
                2,
            )

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy()
    adapter.name = "preset__preset-env"

    async def inspect(source):
        nonlocal inspected
        inspected = True
        return _healthy_snapshot()

    adapter.inspect = inspect
    _wire_environment(monkeypatch, adapter)

    report = await bootstrap.run(
        adapter_name="preset__preset-env",
        page_size=20,
        dashboard_query="growth command",
    )

    assert report["passed"] is False
    assert report["checks"]["dashboard_selection"] is False
    assert report["selection"]["selected_dashboard_id"] is None
    assert report["dashboard_probe"] is None
    assert inspected is False


@pytest.mark.asyncio
async def test_bootstrap_query_rejects_truncated_matches(monkeypatch):
    class Client:
        requests_made = 0

        async def list_dashboards_page(self, *, page, page_size, query=None):
            self.requests_made += 1
            return ([{"id": page + 1, "dashboard_title": f"Growth {page}"}], 3)

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy()
    adapter.name = "preset__preset-env"
    _wire_environment(monkeypatch, adapter)

    report = await bootstrap.run(
        adapter_name="preset__preset-env",
        page_size=1,
        dashboard_query="growth",
        max_pages=2,
    )

    assert report["passed"] is False
    assert report["catalog"]["truncated"] is True
    assert report["selection"]["passed"] is False


@pytest.mark.asyncio
async def test_bootstrap_query_crosses_real_preset_client_and_preserves_failure(monkeypatch):
    workspace = _load_fixture()[0]
    transport = WorkspaceTransport(workspace)
    client = PresetCloudClient(
        f"https://{workspace['id']}.preset.test",
        api_token_name="synthetic-name",
        api_token_secret="synthetic-secret",
        api_base_url="https://api.app.preset.test",
        transport=httpx.MockTransport(transport),
    )
    adapter = PresetAdapter(
        client,
        tenant_id=workspace["tenant_id"],
        policy=HostedDataPolicy(max_result_rows=100),
        adapter_name="preset__preset-env",
    )
    _wire_environment(monkeypatch, adapter)

    report = await bootstrap.run(
        adapter_name="preset__preset-env",
        page_size=20,
        dashboard_query="Northstar executive pulse",
    )

    # The fixture intentionally contains one unsupported chart, so readiness
    # must fail even though provider-side selection and transport succeeded.
    assert report["passed"] is False
    assert report["selection"]["passed"] is True
    assert report["selection"]["selected_dashboard_id"] == workspace["dashboard_id"]
    assert report["dashboard_probe"]["quality_status"] == "partial"
    assert report["jev_requests"] == 0
    assert any(
        request["path"] == "/api/v1/dashboard/"
        and "Northstar executive pulse" in request["params"].get("q", "")
        for request in transport.requests
    )


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
async def test_explicit_dashboard_anchor_bypasses_catalog_permission(monkeypatch):
    class Chart:
        id = "101"
        error = None
        semantic_status = "extracted"
        observations = [object()]

    class Snapshot:
        charts = [Chart()]

    class Client:
        requests_made = 0

        async def list_dashboards_page(self, **kwargs):
            raise AssertionError("explicit dashboard anchors must not list the catalog")

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

    assert report["passed"] is True
    assert report["catalog"] == {
        "page_size": 20,
        "max_pages": 1,
        "query": None,
        "returned_dashboards": 0,
        "provider_count": None,
        "has_dashboard": False,
        "truncated": False,
        "requested": False,
        "explicit_anchor": True,
    }
    assert report["checks"]["explicit_anchor_bypassed_catalog"] is True
    assert report["checks"]["workspace_has_dashboard"] is True
    assert report["provider_requests"]["catalog_requests"] == 0
    assert report["provider_requests"]["for_bootstrap"] == 1


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
