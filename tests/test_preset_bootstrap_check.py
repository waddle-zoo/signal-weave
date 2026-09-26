from __future__ import annotations

from types import SimpleNamespace

import pytest

import scripts.preset_bootstrap_check as bootstrap
from signalweave.hosted import HostedDataPolicy
from signalweave.preset_adapter import PresetAdapter


@pytest.mark.asyncio
async def test_bootstrap_preflight_reads_one_catalog_page_without_jev(monkeypatch, tmp_path):
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
    runtime = SimpleNamespace(
        principal=SimpleNamespace(tenant_id="northstar"),
        sources=SimpleNamespace(
            _get=lambda name: adapter if name == adapter.name else None,
        ),
        engine=SimpleNamespace(
            judger=SimpleNamespace(name="jev-latest", metrics=SimpleNamespace(requests=0))
        ),
    )
    monkeypatch.setattr(bootstrap, "build_runtime", lambda: runtime)

    report = await bootstrap.run(
        adapter_name="preset__preset-env",
        page_size=20,
        output=tmp_path / "bootstrap.json",
    )

    assert report["passed"] is True
    assert report["jev_requests"] == 0
    assert calls == [(0, 20)]


@pytest.mark.asyncio
async def test_bootstrap_preflight_fails_empty_workspace(monkeypatch):
    class Client:
        async def list_dashboards_page(self, *, page, page_size, query=None):
            return ([], 0)

    adapter = PresetAdapter.__new__(PresetAdapter)
    adapter.client = Client()
    adapter.policy = HostedDataPolicy()
    adapter.name = "preset__preset-env"
    runtime = SimpleNamespace(
        principal=SimpleNamespace(tenant_id="northstar"),
        sources=SimpleNamespace(_get=lambda name: adapter),
        engine=SimpleNamespace(
            judger=SimpleNamespace(name="jev-latest", metrics=SimpleNamespace(requests=0))
        ),
    )
    monkeypatch.setattr(bootstrap, "build_runtime", lambda: runtime)

    report = await bootstrap.run(adapter_name="preset__preset-env", page_size=20)

    assert report["passed"] is False
    assert report["catalog"]["provider_count"] == 0
