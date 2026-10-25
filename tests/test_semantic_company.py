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
    assert observation.change_pct == pytest.approx(
        float((expected["current"] - expected["previous"]) / expected["previous"] * 100),
        rel=0, abs=1e-10,
    )  # preserve decision inputs; only the human presentation rounds the rate
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


@pytest.mark.parametrize("profile", ["retail", "saas", "marketplace"])
@pytest.mark.asyncio
async def test_source_publication_supersedes_ledger_snapshot_and_persists(tmp_path, profile):
    company = SemanticCompany(tmp_path, profile)
    source_ref = source(company)
    definition_before = next(item for item in company.descriptors()
                             if item["resource"] == company.canonical_resource)

    company.set_condition("decline")
    previous = await company.inspect(source_ref)
    previous_id = previous.metadata["data_snapshot_id"]
    assert previous.observations[0].current < previous.observations[0].previous * 0.9

    publication = company.publish_measurement_refresh()

    # Reopening the newly created fixture proves the source publication is durable.
    reopened = SemanticCompany(tmp_path, profile)
    arm_snapshots = []
    for arm in ("ordinary_context", "signalweave"):
        arm_snapshot = await reopened.inspect(source(reopened, key=arm))
        arm_snapshots.append(arm_snapshot)
        assert arm_snapshot.metadata["measurement_publication"] == publication
        assert any(item.values == publication for item in arm_snapshot.evidence)
    refreshed = arm_snapshots[-1]
    expected = reopened.expected()
    refreshed_id = refreshed.metadata["data_snapshot_id"]
    definition_after = next(item for item in reopened.descriptors()
                            if item["resource"] == reopened.canonical_resource)

    assert previous_id.startswith("ledger-v1-sha256:")
    assert refreshed_id.startswith("ledger-v1-sha256:")
    assert previous_id != refreshed_id
    assert publication["supersedes_data_snapshot_id"] == previous_id
    assert publication["data_snapshot_id"] == refreshed_id
    assert publication["metric_definition_revision"] == "r3"
    assert definition_before == definition_after
    assert refreshed.metadata["metric_revision"] == previous.metadata["metric_revision"] == "r3"
    assert refreshed.metadata["query_sha256"] == previous.metadata["query_sha256"]
    assert previous_id not in {previous.metadata["metric_revision"], previous.metadata["query_sha256"]}
    assert refreshed_id not in {refreshed.metadata["metric_revision"], refreshed.metadata["query_sha256"]}

    observation = refreshed.observations[0]
    assert observation.current == pytest.approx(float(expected["current"]), rel=0, abs=0.005)
    assert observation.previous == pytest.approx(float(expected["previous"]), rel=0, abs=0.005)
    assert observation.change_pct == pytest.approx(float(expected["change_pct"]), rel=0, abs=0.005)
    measurement = refreshed.evidence[0]
    assert "SUM(" in measurement.values["query_sql"]
    assert measurement.values["data_snapshot_id"] == refreshed_id

    assert refreshed.metadata["measurement_publication"] == publication
    publication_evidence = next(item for item in refreshed.evidence
                                if item.subject_id == "measurement-publication")
    assert publication_evidence.values == publication
    assert publication["supersedes_data_snapshot_id"] == previous_id
    assert reopened.profile["owner"] == publication["source_owner"]
    assert publication["source_owner"] in publication["owner_signoff"]
    assert "scaling from 0.82 to 1.00" in publication["correction"]
    assert "no business cause is asserted" in publication["correction"]
    reader_evidence = json.dumps([item.model_dump(mode="json") for item in refreshed.evidence]).lower()
    assert not any(label in reader_evidence for label in (
        "expected", "gold", "quiet", "decline", "notify", "ignore", "investigate", "insufficient_data"
    ))

    gross = await reopened.inspect(source(reopened, "metric:gross-revenue", key="gross-reader"))
    assert gross.metadata["data_snapshot_id"] == refreshed_id
    assert gross.metadata["source_identity"]["semantic_metric_id"] != publication["metric_id"]
    assert "measurement_publication" not in gross.metadata
    assert all(item.subject_id != "measurement-publication" for item in gross.evidence)

    reopened.set_condition("gap")
    gap = await reopened.inspect(source(reopened))
    assert gap.metadata["data_snapshot_id"] != refreshed_id
    assert "measurement_publication" not in gap.metadata
    assert all(item.subject_id != "measurement-publication" for item in gap.evidence)

    reopened.set_condition("quiet")
    restored = await reopened.inspect(source(reopened))
    assert restored.metadata["data_snapshot_id"] == refreshed_id == publication["data_snapshot_id"]
    assert restored.metadata["measurement_publication"] == publication
    assert any(item.values == publication for item in restored.evidence)
    publication_evidence = next(item for item in restored.evidence if item.values == publication)
    assert publication["publication_id"] in publication_evidence.provenance
    assert not any(ref.startswith("measurement-publication:measurement-publication:")
                   for ref in publication_evidence.provenance)


@pytest.mark.parametrize("profile", ["retail", "saas", "marketplace"])
@pytest.mark.asyncio
async def test_ordinary_conditions_do_not_create_approved_publication_evidence(tmp_path, profile):
    company = SemanticCompany(tmp_path, profile)
    company.set_condition("decline")
    declined = await company.inspect(source(company))
    company.set_condition("quiet")
    quiet = await company.inspect(source(company))

    assert declined.metadata["data_snapshot_id"] != quiet.metadata["data_snapshot_id"]
    for snapshot in (declined, quiet):
        assert "measurement_publication" not in snapshot.metadata
        assert all(item.subject_id != "measurement-publication" for item in snapshot.evidence)


@pytest.mark.asyncio
async def test_marketplace_gross_is_platform_commissions_not_buyer_gmv(tmp_path):
    company = SemanticCompany(tmp_path, "marketplace")
    with company._connect() as db:
        db.execute("UPDATE transactions SET available=0")
        for period in ("2026-08", "2026-09"):
            ids = [row[0] for row in db.execute("SELECT id FROM transactions WHERE period=? ORDER BY id LIMIT 2", (period,))]
            for row_id, category in zip(ids, ("seller_order", "platform_fee"), strict=True):
                db.execute("UPDATE transactions SET available=1,eligible=0,status='settled',revenue_class=?, "
                           "platform_fee_cents=1200,fee_refund_cents=200,tax_cents=100,fx_micros=1000000,activity_bp=10000,gmv_cents=10000 WHERE id=?",
                           (category, row_id))
        db.execute("UPDATE period_coverage SET required_rows=2,available_rows=2")
    # Gross platform fees retain tax/reversals and do not filter eligibility.
    # The seller-order row's fee-like field is not an additional commission.
    assert company.expected("metric:gross-revenue")["current"] == Decimal("12.00")
    snapshot = await company.inspect(source(company, "metric:gross-revenue"))
    assert snapshot.observations[0].current == 12.00


@pytest.mark.parametrize("profile,expected,excluded", [
    ("retail", "Merchandise and shipping", "subscriptions"),
    ("saas", "Invoice billings", "seller proceeds"),
    ("marketplace", "Platform commissions", "subscription revenue"),
])
def test_competing_definition_uses_the_companys_business_domain(tmp_path, profile, expected, excluded):
    company = SemanticCompany(tmp_path, profile)
    company.set_condition("definition_conflict")
    note = next(item for item in company.notes() if item["id"] == "competing-semantic-definition")
    assert expected in note["body"]
    assert excluded not in note["body"]


def test_owner_policy_separates_business_alert_from_data_review(tmp_path):
    company = SemanticCompany(tmp_path, "retail")
    policy = next(item for item in company.notes() if item["id"] == "finance-monitoring-policy")["body"]
    assert "greater than 10%" in policy
    assert "Ignore smaller movement only when coverage is complete and meaning is consistent" in policy
    assert "investigate or insufficient_data" in policy
    assert "data/definition review, never as a business alert" in policy
    assert "Never issue a business all-clear" in policy
    assert "External sending is prohibited" in policy
    assert "simulated local Finance inbox" in policy
    assert "only when the owner explicitly requests it" in policy
    assert "trial exposes the local submission tool" in policy
    assert "ordinary setup and reader runs have neither send tools nor authorization" in policy
    assert policy.count("agent://") == 2


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
    assert "External sending is prohibited" in policy["body"]


@pytest.mark.asyncio
async def test_source_rejects_foreign_adapter_and_unlisted_resources(tmp_path):
    company = SemanticCompany(tmp_path, "saas")
    with pytest.raises(ValueError, match="adapter"):
        await company.inspect(SourceRef(key="x", adapter="superset", resource=company.canonical_resource, label="x"))
    with pytest.raises(ValueError, match="unknown"):
        await company.inspect(source(company, "table:transactions"))
