import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import signalweave.cli as cli
from signalweave.local_health import live_source_report
from signalweave.local_setup import initialize, set_credential, setup_local
from signalweave.local_status import local_status
from signalweave.local_ui import create_local_ui


def _private(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.fixture
def local_home(tmp_path, monkeypatch):
    monkeypatch.setattr("signalweave.local_setup.getpass.getpass", lambda _: "test-typesafe-key")
    return initialize(tmp_path / ".signalweave")


def test_human_can_rotate_credentials_without_exposing_them(local_home):
    destination = set_credential(local_home, "typesafe", value="rotated-typesafe-key")
    assert destination.read_text() == "rotated-typesafe-key\n"
    assert "rotated-typesafe-key" not in (local_home / "config.toml").read_text()
    assert local_status(local_home)["credentials"]["TYPESAFE_API_KEY"] == "configured"


def test_setup_update_replaces_a_source_secret_transactionally(local_home, tmp_path):
    first = _private(tmp_path / "first-password", "first-password")
    second = _private(tmp_path / "second-password", "second-password")
    setup_local(
        local_home,
        source="superset",
        url="http://localhost:8088",
        username="admin",
        secret_file=first,
        non_interactive=True,
        agent="codex",
    )
    setup_local(
        local_home,
        source="superset",
        url="http://localhost:8088",
        username="admin",
        secret_file=second,
        non_interactive=True,
        agent="codex",
        update=True,
    )
    assert (local_home / "superset-password.key").read_text() == "second-password\n"


def test_human_can_add_a_trino_catalog_connection(local_home, tmp_path):
    catalog = _private(
        tmp_path / "trino-catalog.json",
        json.dumps([{
            "adapter": "trino",
            "resource": "analytics.orders",
            "kind": "table",
            "title": "Orders",
        }]),
    )
    setup_local(
        local_home,
        source="trino",
        url="https://trino.example.com",
        catalog_file=catalog,
        trino_user="analyst",
        trino_catalog="lakehouse",
        trino_schema="analytics",
        trino_max_rows=250,
        non_interactive=True,
        agent="codex",
    )
    report = local_status(local_home)
    trino = next(item for item in report["connections"] if item["type"] == "trino")
    assert trino["status"] == "configured"
    assert trino["detail"] == "catalog configured"


def test_status_and_ui_are_secret_free_and_show_next_steps(local_home):
    report = local_status(local_home)
    assert report["status"] == "onboarding_only"
    assert report["next_steps"]
    assert "test-typesafe-key" not in json.dumps(report)

    async def exercise():
        transport = httpx.ASGITransport(app=create_local_ui(local_home))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            page = await client.get("/")
            status = await client.get("/api/status")
            health = await client.get("/healthz")
        return page, status, health

    page, status, health = asyncio.run(exercise())
    assert page.status_code == 200
    assert "Is SignalWeave ready?" in page.text
    assert status.status_code == 200
    assert status.json()["status"] == "onboarding_only"
    assert "test-typesafe-key" not in status.text
    assert health.json() == {"status": "ok"}


def test_ui_can_run_a_live_source_check_without_calling_jev(local_home, monkeypatch):
    async def fake_live_health_report():
        return {"healthy": True, "messages": ["superset: reachable and searchable; catalog items visible: 4."]}

    monkeypatch.setattr("signalweave.local_ui.live_health_report", fake_live_health_report)

    async def exercise():
        transport = httpx.ASGITransport(app=create_local_ui(local_home))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/status?live=true")
        return response

    response = asyncio.run(exercise())
    assert response.status_code == 200
    assert response.json()["live_health"]["healthy"] is True
    assert "catalog items visible: 4" in response.text


@pytest.mark.asyncio
async def test_live_source_check_is_bounded_and_does_not_call_jev(monkeypatch):
    class Sources:
        def adapter_names(self):
            return ["superset", "trino"]

        async def search_resources(self, query, *, adapter_name, limit):
            return SimpleNamespace(total_count=3)

    monkeypatch.setattr(
        "signalweave.local_health.build_runtime",
        lambda: SimpleNamespace(sources=Sources()),
    )
    healthy, messages = await live_source_report(timeout_seconds=1)
    assert healthy
    assert messages == [
        "superset: reachable and searchable; catalog items visible: 3.",
        "trino: reachable and searchable; catalog items visible: 3.",
    ]


def test_cli_status_and_credential_list_are_human_readable(local_home, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["signalweave", "status", "--home", str(local_home)])
    cli.main()
    output = capsys.readouterr().out
    assert "SignalWeave: onboarding only" in output
    assert "Credentials (values hidden)" in output
    assert "test-typesafe-key" not in output

    monkeypatch.setattr(
        sys,
        "argv",
        ["signalweave", "credentials", "list", "--home", str(local_home), "--json"],
    )
    cli.main()
    assert json.loads(capsys.readouterr().out)["TYPESAFE_API_KEY"] == "configured"
