"""Offline coverage for the published-analysis stdio source example."""

import hashlib
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from signalweave.engine import InsightEngine
from signalweave.mcp_source import build_mcp_sources
from signalweave.models import InsightCard, SourceRef
from signalweave.sources import SourceRegistry

READER = Path(__file__).resolve().parents[1] / "examples/analysis_publication/reader.py"
PUBLICATION = {
    "source_key": "product-growth-publication",
    "adapter": "analysis_publication",
    "resource": "report:product-growth",
    "title": "Product growth report",
    "contract": {"tenant_id": "local", "authorized": True},
    "source_captured_at": "2026-10-14T23:00:00Z",
    "metadata": {
        "publication_schema_version": 1,
        "publication_id": "product-growth-weekly",
        "revision": 1,
        "publication_authority": "delegated analyst",
        "source_scope": "Paid accounts, all regions, run wh-8421",
        "published_at": "2026-10-15T00:00:00Z",
    },
    "evidence": [{
        "source_key": "product-growth-publication",
        "subject_id": "finding:activation",
        "subject_label": "Activation finding",
        "statement": "Observed activation was lower in the captured period.",
        "values": {"change": -0.08, "claim_kind": "observation"},
        "origin": "source",
        "provenance": ["warehouse-run:wh-8421"],
    }, {
        "source_key": "product-growth-publication",
        "subject_id": "hypothesis:onboarding",
        "subject_label": "Analyst hypothesis",
        "statement": "A recent onboarding change may explain part of the movement.",
        "values": {"claim_kind": "hypothesis", "confidence": "unassessed"},
        "origin": "source",
        "provenance": ["analysis-notebook:rev-18"],
    }],
}
SOURCE = SourceRef(
    key="card-growth-report",
    adapter="analysis_publication",
    resource="report:product-growth",
    label="Product growth report",
)


def _registry(tmp_path: Path, publication_file: Path) -> SourceRegistry:
    manifest = {
        "version": 1,
        "connections": [{
            "name": "analysis_publication",
            "tenant_id": "local",
            "read_only": True,
            "transport": {
                "type": "stdio",
                "command": [sys.executable, str(READER), str(publication_file)],
            },
            "resources": [{
                "descriptor": {
                    "adapter": "analysis_publication",
                    "resource": "report:product-growth",
                    "kind": "analytical_report",
                    "title": "Reviewed product-growth publication",
                    "contract": {
                        "tenant_id": "local",
                        "domain": "product",
                        "scope": "Owner-approved product-growth publication",
                        "freshness_sla_hours": 24,
                        "authorized": True,
                    },
                },
                "source_key": "product-growth-publication",
                "tool": "get_published_analysis",
                "arguments": {},
            }],
        }],
    }
    manifest_path = tmp_path / "sources.json"
    manifest_path.write_text(json.dumps(manifest))
    return SourceRegistry(build_mcp_sources(str(manifest_path)), authorized_tenants={"local"})


async def _fetch(registry: SourceRegistry):
    return await registry.inspect(SOURCE)


def test_example_manifest_uses_existing_bridge_schema():
    path = READER.with_name("manifest.example.json")
    adapter, = build_mcp_sources(str(path))
    assert adapter.name == "analysis_publication"


async def test_stdio_bridge_fetch_update_fetch_preserves_revision_and_capture(tmp_path):
    publication_file = tmp_path / "current.json"
    publication_file.write_text(json.dumps(PUBLICATION))
    registry = _registry(tmp_path, publication_file)

    first = await _fetch(registry)
    assert first.error is None
    assert first.metadata["publication_id"] == "product-growth-weekly"
    assert first.metadata["revision"] == 1
    assert first.source_captured_at.isoformat() == "2026-10-14T23:00:00+00:00"
    assert first.evidence[0].values == {"change": -0.08, "claim_kind": "observation"}
    assert first.evidence[1].values == {"claim_kind": "hypothesis", "confidence": "unassessed"}
    assert first.evidence[1].subject_label == "Analyst hypothesis"
    assert first.evidence[-1].values == {
        "claim_kind": "publication_record", "publication_id": "product-growth-weekly", "revision": 1,
        "publication_sha256": hashlib.sha256(publication_file.read_bytes()).hexdigest(),
    }

    card = InsightCard(
        id="growth-watch", title="Growth", what_to_watch="Activation movement",
        why_watch="Keep the owner-defined watch policy.", sources=[SOURCE],
        max_source_age_hours=24,
    )
    now = datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc)
    stale_errors = InsightEngine._source_errors(card, [first], now=now)
    assert any("Source snapshot is" in item["message"] for item in stale_errors)

    revised = deepcopy(PUBLICATION)
    revised["source_captured_at"] = "2026-10-15T23:55:00Z"
    revised["metadata"].update(revision=2, published_at="2026-10-16T00:00:00Z")
    revised["evidence"][0]["values"]["change"] = -0.03
    publication_file.write_text(json.dumps(revised))
    second = await _fetch(registry)
    assert second.error is None
    assert second.metadata["revision"] == 2
    assert second.source_captured_at.isoformat() == "2026-10-15T23:55:00+00:00"
    assert second.evidence[0].values["change"] == -0.03
    assert second.evidence[-1].values["revision"] == 2
    assert second.evidence[-1].values["publication_sha256"] != first.evidence[-1].values["publication_sha256"]
    assert not InsightEngine._source_errors(card, [second], now=now)


@pytest.mark.parametrize("change", [
    lambda item: item["metadata"].pop("publication_schema_version"),
    lambda item: item["metadata"].pop("publication_id"),
    lambda item: item["metadata"].update(revision=0),
    lambda item: item.pop("source_captured_at"),
    lambda item: item.update(source_captured_at="2026-10-15T23:00:00"),
    lambda item: item["metadata"].update(published_at="2026-10-15T23:00:00"),
    lambda item: item["metadata"].update(published_at="2000-01-01T00:00:00Z"),
    lambda item: item["metadata"].update(published_at="2099-01-01T00:00:00Z"),
])
async def test_stdio_reader_rejects_missing_or_unversioned_publication_fields(tmp_path, change):
    item = deepcopy(PUBLICATION)
    change(item)
    path = tmp_path / "current.json"
    path.write_text(json.dumps(item))
    snapshot = await _fetch(_registry(tmp_path, path))
    assert snapshot.error == "MCP read tool reported an error"


@pytest.mark.parametrize("field,value", [
    ("adapter", "other"),
    ("resource", "report:other"),
    ("source_key", "other"),
    ("contract", {"tenant_id": "another-tenant", "authorized": True}),
    ("contract", {"tenant_id": "local", "authorized": False}),
    ("evidence", [{"source_key": "other", "statement": "misbound"}]),
])
async def test_existing_bridge_rejects_publication_identity_and_tenant_mismatch(
    tmp_path, field, value,
):
    item = deepcopy(PUBLICATION)
    item[field] = value
    path = tmp_path / "current.json"
    path.write_text(json.dumps(item))
    snapshot = await _fetch(_registry(tmp_path, path))
    assert snapshot.error == "MCP snapshot identity contract mismatch"
    assert snapshot.contract.tenant_id == "local"
    assert snapshot.evidence == []


async def test_stdio_reader_enforces_bounded_regular_nonsymlink_file(tmp_path):
    path = tmp_path / "current.json"
    path.write_bytes(b" " * 900_001)
    oversized = await _fetch(_registry(tmp_path, path))
    assert oversized.error == "MCP read tool reported an error"

    target = tmp_path / "target.json"
    target.write_text(json.dumps(PUBLICATION))
    path.unlink()
    path.symlink_to(target)
    linked = await _fetch(_registry(tmp_path, path))
    assert linked.error == "MCP read tool reported an error"


async def test_stdio_reader_rejects_float_overflow_without_rewriting_it_as_missing(tmp_path):
    path = tmp_path / "current.json"
    path.write_text(json.dumps(PUBLICATION).replace('"change": -0.08', '"change": 1e999'))
    snapshot = await _fetch(_registry(tmp_path, path))
    assert snapshot.error == "MCP read tool reported an error"
    assert snapshot.evidence == []


def test_reader_rejects_detected_in_place_change_instead_of_returning_a_mixed_revision(tmp_path, monkeypatch):
    from examples.analysis_publication import reader

    path = tmp_path / "current.json"
    path.write_text(json.dumps(PUBLICATION))
    original = reader.os.fstat
    calls = 0

    def changed_metadata(descriptor):
        nonlocal calls
        calls += 1
        value = original(descriptor)
        return value if calls == 1 else SimpleNamespace(st_size=value.st_size, st_mtime_ns=value.st_mtime_ns + 1)

    monkeypatch.setattr(reader.os, "fstat", changed_metadata)
    with pytest.raises(ValueError, match="unavailable or invalid"):
        reader._read_publication(path)


async def test_large_publication_fits_example_bridge_without_a_duplicate_text_copy(tmp_path):
    item = deepcopy(PUBLICATION)
    text = "a" * 550_000
    item["evidence"][0]["statement"] = text
    path = tmp_path / "current.json"
    path.write_text(json.dumps(item))
    snapshot = await _fetch(_registry(tmp_path, path))
    assert snapshot.error is None
    assert snapshot.evidence[0].statement == text
    assert snapshot.evidence[-1].values["publication_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
