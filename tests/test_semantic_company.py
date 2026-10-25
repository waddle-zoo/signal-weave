import json
from decimal import Decimal

import pytest

from evaluations.semantic_company import SemanticCompany
from signalweave.models import ResourceDescriptor, ResourceSnapshot, SourceRef


def source(company, resource="metric:net-revenue", key="requested-source-key"):
    return SourceRef(key=key, adapter=company.name, resource=resource, label="Revenue")


@pytest.mark.parametrize("profile", ["retail", "saas", "marketplace"])
@pytest.mark.asyncio
async def test_sql_snapshot_matches_independent_decimal_ledger_calculation(tmp_path, profile):
    company = SemanticCompany(tmp_path, profile)
    request = source(company)
    snapshot = await company.inspect(request)
    expected = company.expected()
    assert isinstance(snapshot, ResourceSnapshot)
    assert (snapshot.source_key, snapshot.adapter, snapshot.resource) == (
        request.key, request.adapter, request.resource
    )
    observation = snapshot.observations[0]
    assert observation.current == pytest.approx(float(expected["current"]), rel=0, abs=0.005)
    assert observation.previous == pytest.approx(float(expected["previous"]), rel=0, abs=0.005)
    assert observation.change_pct == pytest.approx(float(expected["change_pct"]), rel=0, abs=0.005)
    evidence = snapshot.evidence[0]
    assert evidence.values["delta"] == pytest.approx(float(expected["delta"]), rel=0, abs=0.005)
    assert "SUM(" in evidence.values["query_sql"]
    assert evidence.values["metric_revision"] == "r3"
    assert snapshot.metadata["source_identity"] == {
        "tenant_id": company.tenant_id,
        "adapter": request.adapter,
        "resource": request.resource,
        "semantic_metric_id": company.metric_id,
    }
    assert snapshot.metadata["measurement_periods"] == {
        "current": "2026-09-01/2026-09-30",
        "previous": "2026-08-01/2026-08-31",
    }
    assert snapshot.metadata["archival_mode_required"] is True
    assert snapshot.source_captured_at is not None
    assert "not a live dbt/Cube connector" in snapshot.description
    serialized = json.dumps(snapshot.model_dump(mode="json")).lower()
    assert not any(token in serialized for token in ("expected", "gold", "quiet", "decline"))


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["retail", "saas", "marketplace"])
async def test_catalog_has_same_title_decoys_with_distinct_semantics_and_typed_contracts(tmp_path, profile):
    company = SemanticCompany(tmp_path, profile)
    descriptors = [ResourceDescriptor.model_validate(item) for item in company.descriptors()]
    assert {item.resource for item in descriptors} == {
        "metric:net-revenue", "metric:gross-revenue", "metric:gmv", "metric:arr",
        "metric:revenue-draft", "metric:revenue-deprecated",
    }
    assert {item.title for item in descriptors} == {"Revenue"}
    assert len({item.description for item in descriptors}) == len(descriptors)
    canonical = next(item for item in descriptors if item.resource == company.canonical_resource)
    contract = canonical.contract
    assert contract.tenant_id == company.tenant_id
    assert contract.metric_names == [company.metric_id]
    definition = contract.comparison_contracts[0]
    assert definition.metric == company.metric_id
    assert contract.grain == "month"
    assert company.profile["owner"] in contract.scope
    assert definition.unit == company.unit
    assert contract.metric_definitions == []  # fixed exports, not raw query-compiler bindings
    assert contract.population and "calendar" in contract.scope
    assert "not a live dbt/Cube connector" in contract.scope
    assert next(item for item in descriptors if item.resource.endswith("draft")).metadata["semantic_status"] == "draft"
    assert next(item for item in descriptors if item.resource.endswith("deprecated")).metadata["semantic_status"] == "deprecated"
    serialized = json.dumps(company.descriptors()).lower()
    assert not any(token in serialized for token in ("expected", "gold", "decline", "quiet"))
    gold_by_resource = {}
    for descriptor in descriptors:
        gold = company.expected(descriptor.resource)
        snapshot = await company.inspect(source(company, descriptor.resource))
        assert snapshot.observations[0].unit == gold["unit"] == company.unit
        assert snapshot.observations[0].current == pytest.approx(float(gold["current"]), rel=0, abs=0.005)
        assert snapshot.observations[0].previous == pytest.approx(float(gold["previous"]), rel=0, abs=0.005)
        gold_by_resource[descriptor.resource] = gold["current"]
    assert gold_by_resource["metric:gross-revenue"] != gold_by_resource[company.canonical_resource]


@pytest.mark.asyncio
async def test_currency_scale_has_an_independent_hand_computable_control(tmp_path):
    company = SemanticCompany(tmp_path, "retail")
    with company._connect() as db:
        db.execute("UPDATE transactions SET available=0")
        for period, fx in (("2026-08", 1_000_000), ("2026-09", 740_000)):
            row_id = db.execute("SELECT id FROM transactions WHERE period=? ORDER BY id LIMIT 1", (period,)).fetchone()[0]
            db.execute("UPDATE transactions SET available=1, revenue_class='merchandise', status='posted', eligible=1, "
                       "gross_cents=12345, refund_cents=345, tax_cents=0, fx_micros=?, activity_bp=10000 WHERE id=?",
                       (fx, row_id))
        db.execute("UPDATE period_coverage SET required_rows=1,available_rows=1")
    # (12345 - 345) cents = 120 currency units. Reporting FX 0.74 -> 88.80.
    gold = company.expected()
    assert gold["current"] == Decimal("88.80")
    assert gold["previous"] == Decimal("120.00")
    snapshot = await company.inspect(source(company))
    assert snapshot.observations[0].current == 88.80
    assert snapshot.observations[0].previous == 120.00


@pytest.mark.asyncio
async def test_marketplace_gmv_excludes_platform_fee_tax_and_fee_ledger_records(tmp_path):
    company = SemanticCompany(tmp_path, "marketplace")
    with company._connect() as db:
        db.execute("UPDATE transactions SET available=0")
        for period in ("2026-08", "2026-09"):
            ids = [row[0] for row in db.execute("SELECT id FROM transactions WHERE period=? ORDER BY id LIMIT 2", (period,))]
            for row_id, category in zip(ids, ("seller_order", "platform_fee"), strict=True):
                db.execute("UPDATE transactions SET available=1,eligible=1,status='settled',revenue_class=?, "
                           "gross_cents=10000,tax_cents=9999,fx_micros=1000000,activity_bp=10000,gmv_cents=10000 WHERE id=?",
                           (category, row_id))
        db.execute("UPDATE period_coverage SET required_rows=2,available_rows=2")
    # One seller order worth EUR 100. Neither a fee row nor its tax is buyer GMV.
    assert company.expected("metric:gmv")["current"] == Decimal("100.00")
    snapshot = await company.inspect(source(company, "metric:gmv"))
    assert snapshot.observations[0].current == 100.00


def test_seed_company_and_condition_controls_change_source_facts(tmp_path):
    retail = SemanticCompany(tmp_path / "retail", "retail", seed=10)
    other_seed = SemanticCompany(tmp_path / "seed", "retail", seed=11)
    saas = SemanticCompany(tmp_path / "saas", "saas", seed=10)
    assert retail.tenant_id != saas.tenant_id
    assert retail.metric_id != saas.metric_id
    assert retail.expected()["current"] != saas.expected()["current"]
    assert retail.expected()["current"] != other_seed.expected()["current"]

    baseline = retail.expected()
    retail.set_condition("decline")
    declined = retail.expected()
    assert declined["change_pct"] < Decimal("-10")
    assert declined["current"] < baseline["current"]
    retail.set_condition("quiet")
    assert retail.expected() == baseline


@pytest.mark.asyncio
async def test_gap_and_definition_conflict_are_source_evidence_not_private_labels(tmp_path):
    company = SemanticCompany(tmp_path, "marketplace")
    request = source(company)
    company.set_condition("gap")
    gap = await company.inspect(request)
    assert gap.contract.comparison_contracts[0].coverage == "partial"
    assert gap.contract.comparison_contracts[0].comparable is False
    assert gap.metadata["measurement_coverage"]["2026-09"]["available_rows"] == 36
    assert any("36 of 48" in item.statement for item in gap.evidence)

    company.set_condition("definition_conflict")
    conflict = await company.inspect(request)
    assert any(item.values.get("owner") == "Consolidation Accounting" for item in conflict.evidence)
    assert "Conflicting source definition" in conflict.contract.scope
    notes = company.notes()
    assert {item["id"] for item in notes} == {
        "semantic-metric-definition", "finance-monitoring-policy", "competing-semantic-definition"
    }
    assert all(item["source_refs"] == ["company|metric:net-revenue"] for item in notes)
    policy = next(item for item in notes if item["id"] == "finance-monitoring-policy")
    assert "No sending is permitted" in policy["body"]


@pytest.mark.asyncio
async def test_source_rejects_foreign_adapter_and_unlisted_resources(tmp_path):
    company = SemanticCompany(tmp_path, "saas")
    with pytest.raises(ValueError, match="adapter"):
        await company.inspect(SourceRef(key="x", adapter="superset", resource=company.canonical_resource, label="x"))
    with pytest.raises(ValueError, match="unknown"):
        await company.inspect(source(company, "table:transactions"))
