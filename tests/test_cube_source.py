from types import SimpleNamespace

import httpx
import pytest

from evaluations.cube_source import CubeCompany
from signalweave.models import SourceRef


def fixture():
    meta = {"resource": "metric:net-revenue", "metric_id": "commerce.net", "definition": "Net excluding tax",
            "owner": "Controller", "population": "Posted eligible orders", "currency": "USD", "grain": "month",
            "time_semantics": "Completed UTC months", "revision": "r7", "status": "active"}
    cube = {"name": "Sales", "measures": [{"name": "Sales.amount", "description": "Net excluding tax", "meta": meta}]}
    rows = [{"Sales.month.month": period + "-01T00:00:00.000", "Sales.amount": amount,
             "Sales.available_records": "2", "Sales.ledger_records": "2", "Sales.expected_records": "2"}
            for period, amount in (("2026-08", "100.00"), ("2026-09", "88.80"))]
    return {"cubes": [cube]}, {"data": rows, "lastRefreshTime": "2026-10-25T12:00:00.000Z"}


@pytest.mark.asyncio
async def test_normalization_queries_actual_http_and_does_not_call_oracle():
    catalog, result = fixture()
    requested = []

    def handler(request):
        requested.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"meta": catalog, "sql": {"sql": ["source-generated SQL", []]}, "load": result}[requested[-1]])

    oracle = SimpleNamespace(company="retail", profile={"domain": "commerce"})
    async with httpx.AsyncClient(base_url="http://test/", transport=httpx.MockTransport(handler)) as client:
        source = CubeCompany(client, oracle)
        snapshot = await source.inspect(SourceRef(key="chosen", adapter="company", resource="metric:net-revenue", label="Revenue"))
    assert requested == ["meta", "sql", "load"]
    assert snapshot.observations[0].current == 88.8
    assert snapshot.observations[0].metric == "commerce.net"
    assert "r7" in snapshot.contract.scope
    assert snapshot.source_captured_at.isoformat() == "2026-10-25T12:00:00+00:00"
    assert snapshot.contract.comparison_contracts[0].coverage == "complete"
    assert "cube_response" not in snapshot.metadata
    assert "cube_compiled_sql" not in snapshot.evidence[0].values
    assert snapshot.evidence[0].values["ledger_coverage"]["2026-09"]["expected"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing-period", "duplicate-period", "null-amount", "fractional-count", "upstream-error"])
async def test_invalid_source_results_do_not_become_zero_or_all_clear(case):
    catalog, result = fixture()
    if case == "missing-period":
        result["data"].pop()
    elif case == "duplicate-period":
        result["data"].append(result["data"][0])
    elif case == "null-amount":
        result["data"][0]["Sales.amount"] = None
    elif case == "fractional-count":
        result["data"][0]["Sales.expected_records"] = "2.9"
    else:
        result = {"error": "upstream query rejected"}
    def handler(request):
        return httpx.Response(200, json=catalog if request.url.path == "/meta" else
                              {"sql": ["SQL", []]} if request.url.path == "/sql" else result)
    async with httpx.AsyncClient(base_url="http://test/", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            await CubeCompany(client, SimpleNamespace(company="retail", profile={"domain": "commerce"})).inspect(
                SourceRef(key="chosen", adapter="company", resource="metric:net-revenue", label="Revenue"))


@pytest.mark.asyncio
async def test_missing_rows_are_checked_against_independent_expected_count():
    catalog, result = fixture()
    result["data"][1].update({"Sales.available_records": "1", "Sales.ledger_records": "1"})
    def handler(request):
        return httpx.Response(200, json=catalog if request.url.path == "/meta" else
                              {"sql": ["SQL", []]} if request.url.path == "/sql" else result)
    async with httpx.AsyncClient(base_url="http://test/", transport=httpx.MockTransport(handler)) as client:
        snapshot = await CubeCompany(client, SimpleNamespace(company="retail", profile={"domain": "commerce"})).inspect(
            SourceRef(key="chosen", adapter="company", resource="metric:net-revenue", label="Revenue"))
    assert snapshot.contract.comparison_contracts[0].coverage == "partial"
    assert snapshot.contract.comparison_contracts[0].comparable is False
