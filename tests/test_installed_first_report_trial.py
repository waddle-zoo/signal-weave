import asyncio
import json
import os
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from evaluations.installed_first_report_trial import (
    ROUTE_INTENT,
    _fixture_payload,
    _live_company,
    _manifest,
    _normal_public,
    _routes,
    _scan_exact_secrets,
    run_trial,
)
from evaluations.recurring_runtime_transfer_cases import cases


def test_public_fixture_has_all_lattice_sources_and_no_oracle():
    company = next(item for item in cases() if item["id"] == "lattice-energy")
    public, snapshots = _normal_public(company, company["periods"][2])
    assert len(public["descriptors"]) == len(public["sources"]) == 2
    assert {item["adapter"] for item in public["descriptors"]} == {"company_metrics"}
    assert {item["contract"]["tenant_id"] for item in public["descriptors"]} == {"local"}
    assert {item["adapter"] for item in snapshots} == {"company_metrics"}
    assert {item["contract"]["tenant_id"] for item in snapshots} == {"local"}
    assert all(item["metadata"]["replayed_historical_data"] for item in snapshots)
    assert all(item["source_captured_at"] == item["captured_at"] for item in snapshots)
    assert all(item["metadata"]["historical_source_captured_at"] != item["captured_at"] for item in snapshots)
    assert all("oracle" not in json.dumps(item).lower() for item in snapshots)


def test_manifest_identity_permissions_and_explicit_route_intent(tmp_path):
    company = cases()[0]
    public, _ = _normal_public(company, company["periods"][2])
    manifest = _manifest(company, public, tmp_path / "fixture.py", tmp_path / "snapshot.json")
    assert manifest["connections"][0]["name"] == "company_metrics"
    assert manifest["connections"][0]["tenant_id"] == "local"
    assert all(item["descriptor"]["adapter"] == "company_metrics" for item in manifest["connections"][0]["resources"])
    assert all(item["descriptor"]["contract"]["tenant_id"] == "local" for item in manifest["connections"][0]["resources"])
    assert {item["arguments"]["resource"] for item in manifest["connections"][0]["resources"]} == {
        item["resource"] for item in public["descriptors"]
    }
    route_keys = {(item["outcome"], item["destination"]) for item in _routes(company["id"], company["destinations"])}
    assert route_keys == {("notify", "agent://fleet-operations"), ("insufficient_data", "agent://logistics-data")}
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest))
    manifest_file.chmod(0o600)
    assert stat.S_IMODE(manifest_file.stat().st_mode) == 0o600


def test_dry_run_freezes_source_fixture_and_oracle_hashes_without_model_or_fixture_execution(tmp_path, monkeypatch):
    monkeypatch.setattr("evaluations.installed_first_report_trial._live_company",
                        lambda *args, **kwargs: pytest.fail("dry run executed live harness"))
    result = run_trial(tmp_path / "trial")
    assert result == {"status": "dry_run", "intended_denominator": 3, "paid_attempts": 0}
    protocol = json.loads((tmp_path / "trial" / "frozen_protocol.json").read_text())
    assert protocol["max_jev_attempts_per_company"] == 2
    assert protocol["intended_denominator"] == 3
    assert all(item["source_freeze_sha256"] and item["fixture_sha256"] and item["oracle_sha256"] for item in protocol["frozen_inputs"])
    assert protocol["approval"]["seeded_approved_cards"] is False


def test_p03_is_actionable_for_each_company_and_route_policy_is_not_oracle_derived():
    for company in cases():
        assert company["periods"][2]["oracle"]["outcome"] in {"notify", "investigate"}
        assert ROUTE_INTENT[company["id"]]
    assert "recipients" not in json.dumps(ROUTE_INTENT)


def test_source_duplicates_and_swapped_bindings_rejected():
    company = cases()[-1]
    company["sources"].append(dict(company["sources"][0]))
    with pytest.raises(ValueError, match="not unique"):
        _normal_public(company, company["periods"][2])
    company = cases()[-1]
    left, right = company["periods"][2]["resources"]
    left["source_key"], right["source_key"] = right["source_key"], left["source_key"]
    with pytest.raises(ValueError, match="bindings"):
        _normal_public(company, company["periods"][2])


def test_key_scan_rejects_key_without_trailing_newline(tmp_path):
    key = tmp_path / "key"
    key.write_text("sensitive-fixture-value\n")
    with pytest.raises(RuntimeError, match="key material"):
        _scan_exact_secrets('{"oops": "sensitive-fixture-value"}', key)
    assert _scan_exact_secrets('{"fine": true}', key)["matches"] == 0


def test_offline_setup_and_source_registry_inspect_fixture_mcp(tmp_path):
    pytest.importorskip("httpx")
    from signalweave.local_setup import setup_local
    from signalweave.mcp_source import build_mcp_sources
    from signalweave.models import SourceRef
    from signalweave.sources import SourceRegistry

    company = next(item for item in cases() if item["id"] == "lattice-energy")
    public, _ = _normal_public(company, company["periods"][2])
    fixture = tmp_path / "snapshot.json"
    fixture.write_text(json.dumps(_fixture_payload(company, company["periods"][2])))
    home = tmp_path / "private-home"
    home.mkdir(mode=0o700)
    key = tmp_path / "input.key"
    key.write_text("offline-test-key\n")
    key.chmod(0o600)
    manifest = home / "manifest.json"
    manifest.write_text(json.dumps(_manifest(company, public, Path(__file__).parents[1] / "evaluations" / "fixture_snapshot_mcp.py", fixture)))
    manifest.chmod(0o600)
    setup_local(home, key_file=key, source="mcp", manifest=manifest, tenant="local",
                principal=company["id"], agent="codex", non_interactive=True)
    if binary := os.environ.get("SIGNALWEAVE_TEST_BINARY"):
        result = subprocess.run([
            str(Path(binary).resolve()), "setup", "--home", str(home), "--non-interactive",
            "--key-file", str(key), "--source", "mcp", "--manifest", str(manifest),
            "--tenant", "local", "--principal", company["id"], "--agent", "codex",
        ], capture_output=True, text=True, timeout=90,
            env={k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR") if k in os.environ})
        assert result.returncode == 0, result.stderr
    assert (home / "typesafe.key").read_text() == "offline-test-key\n"
    assert stat.S_IMODE((home / "typesafe.key").stat().st_mode) == 0o600
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600
    adapter, = build_mcp_sources(str(manifest))
    registry = SourceRegistry([adapter], authorized_tenants={"local"})
    async def inspect_all():
        for source in public["sources"]:
            snapshot = await registry.inspect(SourceRef.model_validate(source))
            assert snapshot.error is None
            assert snapshot.adapter == "company_metrics"
            assert snapshot.contract.tenant_id == "local"
            assert snapshot.source_captured_at is not None

    asyncio.run(inspect_all())


@pytest.mark.skipif(not os.environ.get("SIGNALWEAVE_TEST_BINARY"), reason="requires native binary")
def test_native_first_report_preflight_without_inference(tmp_path):
    key = tmp_path / "key"
    key.write_text("offline-fixture-key")
    company = cases()[0]
    attempts = {"paid": 0, "companies": {company["id"]: 0}}
    result = asyncio.run(_live_company(
        Path(os.environ["SIGNALWEAVE_TEST_BINARY"]).resolve(), key, company,
        Path(__file__).parents[1] / "evaluations" / "fixture_snapshot_mcp.py",
        datetime.now(timezone.utc).isoformat(), attempts, [], tmp_path / "events.jsonl",
        preflight_only=True,
    ))
    assert result["preflight_passed"]
    assert attempts["paid"] == 0
