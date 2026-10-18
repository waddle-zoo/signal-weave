"""Bounded SQL Lab HTTP contracts; no warehouse or model access in unit tests."""
from __future__ import annotations

import asyncio
import json
from datetime import timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest

from signalweave import superset_sql as transport
from signalweave.preset_adapter import PresetCloudClient
from signalweave.superset_client import SupersetClient
from signalweave.superset_sql import SQLQueryError, SQLQueryResult, execute_sql

CSRF, EXECUTE, RESULTS = ("/api/v1/security/csrf_token/", "/api/v1/sqllab/execute/", "/api/v1/sqllab/results/")
SQL = "WITH reviewed AS (SELECT 1 AS value) SELECT value FROM reviewed -- unchanged"


def payload(**updates):
    result = {"status": "success", "data": [{"value": None}],
              "columns": [{"column_name": "value", "name": "value"}],
              "query_id": 17, "query": {"id": "client-17", "serverId": 17,
                                         "rows": 1, "limit": 1001, "limitingFactor": "NOT_LIMITED"}}
    result.update(updates)
    return result


def client_for(response, *, requests=None):
    calls = requests if requests is not None else []

    def handler(request):
        calls.append(request)
        if request.url.path == CSRF:
            return httpx.Response(200, json={"result": "csrf-token"},
                                  headers={"Set-Cookie": "session=csrf-session; Path=/"})
        assert request.url.path == EXECUTE
        return response(request) if callable(response) else httpx.Response(200, json=response)

    return SupersetClient("https://source.invalid", transport=httpx.MockTransport(handler)), calls


async def test_sync_preserves_sql_nulls_aliases_precision_session_and_ids():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/api/v1/security/login":
            return httpx.Response(200, json={"access_token": "jwt-token"})
        assert request.headers["Authorization"] == "Bearer jwt-token"
        if request.url.path == CSRF:
            return httpx.Response(200, json={"result": "csrf-token"},
                                  headers={"Set-Cookie": "session=csrf-session; Path=/"})
        assert request.url.path == EXECUTE
        assert request.headers["X-CSRFToken"] == "csrf-token"
        assert request.headers["Cookie"] == "session=csrf-session"
        assert request.headers["Referer"] == "https://source.invalid/"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {"sql": SQL, "database_id": 2, "catalog": "catalog",
                                              "schema": "schema", "runAsync": False, "queryLimit": 4}
        return httpx.Response(200, content=b'{"status":"success","data":[{"Exact Alias":0.12345678901234567890123456789,"empty":"","null":null,"zero":0}],"columns":[{"column_name":"Exact Alias"},{"name":"empty"},"null","zero"],"query_id":17,"query":{"id":"client-17","rows":1,"limit":4,"limitingFactor":"NOT_LIMITED"}}')

    client = SupersetClient("https://source.invalid", username="user", password="secret",
                            transport=httpx.MockTransport(handler))
    result = await execute_sql(client, sql=SQL, database_id=2, catalog="catalog", schema="schema", max_rows=3)
    assert isinstance(result, SQLQueryResult)
    assert result.rows == [{"Exact Alias": Decimal("0.12345678901234567890123456789"), "empty": "", "null": None, "zero": 0}]
    assert result.columns == ["Exact Alias", "empty", "null", "zero"]
    assert (result.query_id, result.client_id, result.results_key) == ("17", "client-17", None)
    assert result.received_at.tzinfo == timezone.utc
    assert len(calls) == 3
    # Existing Superset authentication has its own accounting contract.
    assert client.request_path_counts[CSRF] == client.request_path_counts[EXECUTE] == 1


async def test_async_preserves_initial_identity_and_polls_only_result_key(monkeypatch):
    calls = []
    key = "opaque!')&key=elsewhere"
    sleep = AsyncMock()
    monkeypatch.setattr(transport.asyncio, "sleep", sleep)

    def handler(request):
        calls.append(request)
        if request.url.path == CSRF:
            return httpx.Response(200, json={"result": "csrf"}, headers={"Set-Cookie": "session=one; Path=/"})
        assert request.headers["Cookie"] == "session=one"
        if request.url.path == EXECUTE:
            return httpx.Response(202, json={"query_id": 17, "query": {"id": "client-17", "state": "running", "resultsKey": key}, "data": []})
        assert request.method == "GET" and request.url.path == RESULTS
        escaped = key.replace("!", "!!").replace("'", "!'")
        assert dict(request.url.params) == {"q": f"(key:'{escaped}')"}
        if sum(call.url.path == RESULTS for call in calls) == 1:
            return httpx.Response(200, json={"status": "running", "data": []})
        return httpx.Response(200, json={"status": "success", "data": [{"value": 0}], "columns": ["value"]})

    client = SupersetClient("https://source.invalid", transport=httpx.MockTransport(handler))
    result = await execute_sql(client, sql=SQL, database_id=2, max_polls=2)
    assert result.rows == [{"value": 0}]
    assert (result.query_id, result.client_id, result.results_key) == ("17", "client-17", key)
    assert client.requests_made == 4
    assert client.request_path_counts == {CSRF: 1, EXECUTE: 1, RESULTS: 2}
    sleep.assert_awaited_once_with(1)


async def test_null_top_level_ids_do_not_hide_received_query_metadata():
    client, _ = client_for(payload(query_id=None, client_id=None, results_key=None,
                                 query={"serverId": 17, "id": "client-17", "resultsKey": "key"}))
    result = await execute_sql(client, sql=SQL, database_id=2)
    assert (result.query_id, result.client_id, result.results_key) == ("17", "client-17", "key")


async def test_preset_token_exchange_is_reused_without_chart_request_retry_layer():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "api.app.preset.io":
            assert request.url.path == "/v1/auth/"
            return httpx.Response(200, json={"payload": {"access_token": "preset-jwt"}})
        assert request.headers["Authorization"] == "Bearer preset-jwt"
        return httpx.Response(200, json={"result": "csrf"} if request.url.path == CSRF else payload())

    client = PresetCloudClient("https://workspace.invalid", api_token_name="name", api_token_secret="secret",
                               transport=httpx.MockTransport(handler))
    client._request = AsyncMock(side_effect=AssertionError("Do not retry SQL through chart request layer"))
    result = await execute_sql(client, sql=SQL, database_id=2)
    assert result.rows == [{"value": None}]
    assert [call.url.path for call in calls] == ["/v1/auth/", CSRF, EXECUTE]
    assert client.requests_made == 3
    client._request.assert_not_awaited()


@pytest.mark.parametrize("preset", [False, True])
@pytest.mark.parametrize("rejected_path", [CSRF, EXECUTE])
async def test_expired_cached_jwt_refreshes_once_with_same_session_and_fresh_csrf(preset, rejected_path):
    calls, submissions = [], []
    csrf_count = 0
    rejected = False

    def handler(request):
        nonlocal csrf_count, rejected
        calls.append(request)
        if request.url.path in {"/api/v1/security/login", "/v1/auth/"}:
            token = {"access_token": "fresh-jwt"}
            return httpx.Response(200, json={"payload": token} if preset else token)
        if request.url.path == CSRF:
            csrf_count += 1
        else:
            assert request.url.path == EXECUTE
            submissions.append(request.content)
        if request.url.path == rejected_path and not rejected:
            rejected = True
            assert request.headers["Authorization"] == "Bearer expired-jwt"
            return httpx.Response(401, text=SQL + " secret-token",
                                  headers={"Set-Cookie": "session=retained; Path=/"})
        if request.url.path == CSRF:
            if rejected:
                assert request.headers["Authorization"] == "Bearer fresh-jwt"
                # The first run's refresh must not discard its session cookies.
                if csrf_count == 2:
                    assert request.headers["Cookie"] == "session=retained"
            return httpx.Response(200, json={"result": f"csrf-{csrf_count}"},
                                  headers={"Set-Cookie": "session=retained; Path=/"})
        assert request.headers["Authorization"] == "Bearer fresh-jwt"
        assert request.headers["X-CSRFToken"] == f"csrf-{csrf_count}"
        assert request.headers["Cookie"] == "session=retained"
        return httpx.Response(200, json=payload())

    backend = httpx.MockTransport(handler)
    client = (PresetCloudClient("https://workspace.invalid", api_token_name="name", api_token_secret="secret", transport=backend)
              if preset else SupersetClient("https://source.invalid", username="user", password="secret", transport=backend))
    client._token = "expired-jwt"
    auth = AsyncMock(wraps=client._auth_headers)
    client._auth_headers = auth
    for _ in range(2):
        result = await execute_sql(client, sql=SQL, database_id=2, catalog="catalog", schema="schema")
        assert result.rows == [{"value": None}] and result.query_id == "17"
    assert client._token == "fresh-jwt"
    assert sum(call.kwargs.get("force_refresh", False) for call in auth.await_args_list) == 1
    assert sum(request.url.path in {"/api/v1/security/login", "/v1/auth/"} for request in calls) == 1
    assert len(submissions) == (3 if rejected_path == EXECUTE else 2)
    assert all(body == submissions[0] for body in submissions)
    assert json.loads(submissions[0])["sql"] == SQL
    assert client.request_path_counts[CSRF] == 3
    assert client.request_path_counts[EXECUTE] == len(submissions)
    assert client.requests_made == 3 + len(submissions) + int(preset)


@pytest.mark.parametrize("rejected_path", [CSRF, EXECUTE])
async def test_preset_bearer_only_401_cannot_refresh_or_resubmit(rejected_path):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer expired-bearer"
        if request.url.path == rejected_path:
            return httpx.Response(401, text=SQL + " expired-bearer")
        assert request.url.path == CSRF
        return httpx.Response(200, json={"result": "csrf"})

    client = PresetCloudClient("https://workspace.invalid", access_token="expired-bearer",
                               transport=httpx.MockTransport(handler))
    with pytest.raises(SQLQueryError, match="authentication") as failure:
        await execute_sql(client, sql=SQL, database_id=2)
    assert SQL not in str(failure.value) and "expired-bearer" not in str(failure.value)
    assert [request.url.path for request in calls] == ([CSRF] if rejected_path == CSRF else [CSRF, EXECUTE])
    assert client.requests_made == len(calls)


@pytest.mark.parametrize("rejected_path", [CSRF, EXECUTE, "both"])
async def test_repeated_401_has_one_shared_refresh_budget(rejected_path):
    calls = []

    def handler(request):
        calls.append(request)
        rejected = (request.url.path == rejected_path or
                    (rejected_path == "both" and (len(calls) == 1 or request.url.path == EXECUTE)))
        return httpx.Response(401, text=SQL + " secret") if rejected else httpx.Response(200, json={"result": "csrf"})

    client = SupersetClient("https://source.invalid", transport=httpx.MockTransport(handler))
    client._auth_headers = AsyncMock(side_effect=[{"Authorization": "Bearer expired"}, {"Authorization": "Bearer refreshed"}])
    with pytest.raises(SQLQueryError, match="401"):
        await execute_sql(client, sql=SQL, database_id=2)
    expected = {CSRF: [CSRF, CSRF], EXECUTE: [CSRF, EXECUTE, CSRF, EXECUTE], "both": [CSRF, CSRF, EXECUTE]}
    assert [request.url.path for request in calls] == expected[rejected_path]
    assert client._auth_headers.await_count == 2
    client._auth_headers.assert_awaited_with(force_refresh=True)
    assert client.requests_made == len(calls)


@pytest.mark.parametrize("network_failure", [False, True])
async def test_post_failure_after_401_refresh_is_not_retried_again(network_failure):
    submissions = []

    def handler(request):
        if request.url.path == CSRF:
            return httpx.Response(200, json={"result": "csrf"})
        submissions.append(request.content)
        if len(submissions) == 1:
            return httpx.Response(401)
        if network_failure:
            raise httpx.ReadError(SQL + " secret", request=request)
        return httpx.Response(503, text=SQL + " secret")

    client = SupersetClient("https://source.invalid", transport=httpx.MockTransport(handler))
    client._auth_headers = AsyncMock(side_effect=[{"Authorization": "Bearer expired"}, {"Authorization": "Bearer refreshed"}])
    with pytest.raises(SQLQueryError):
        await execute_sql(client, sql=SQL, database_id=2)
    assert len(submissions) == 2 and submissions[0] == submissions[1]
    assert client._auth_headers.await_count == 2


@pytest.mark.parametrize("factor", ["NOT_LIMITED", "not_limited"])
async def test_explicit_nonlimited_enum_forms_are_accepted(factor):
    client, _ = client_for(payload(query={"limitingFactor": factor}))
    assert (await execute_sql(client, sql=SQL, database_id=2)).rows == [{"value": None}]


@pytest.mark.parametrize("factor", ["QUERY", "query", "display_limit", "unlimited", "not-limited", "not_limited "])
async def test_limited_and_unknown_enum_forms_remain_rejected(factor):
    client, _ = client_for(payload(query={"limitingFactor": factor}))
    with pytest.raises(SQLQueryError, match="limited result"):
        await execute_sql(client, sql=SQL, database_id=2)


@pytest.mark.parametrize("options", [
    {"sql": ""}, {"sql": " \n"}, {"sql": None}, {"database_id": True}, {"database_id": 0},
    {"database_id": "1"}, {"catalog": []}, {"schema": ""}, {"max_rows": False}, {"max_rows": 0},
    {"max_bytes": -1}, {"max_bytes": 1.5}, {"max_polls": 0}, {"max_polls": True},
    {"timeout_seconds": float("inf")}, {"timeout_seconds": float("nan")},
    {"timeout_seconds": 0}, {"timeout_seconds": True},
])
async def test_bad_arguments_do_not_authenticate_or_make_requests(options):
    client, calls = client_for(payload())
    client._auth_headers = AsyncMock(side_effect=AssertionError("No auth on invalid arguments"))
    with pytest.raises(SQLQueryError):
        await execute_sql(client, **{"sql": SQL, "database_id": 2, **options})
    assert calls == [] and client.requests_made == 0
    client._auth_headers.assert_not_awaited()


@pytest.mark.parametrize("csrf", [{}, {"result": None}, {"result": ""}, {"result": []}])
async def test_missing_csrf_never_submits_sql(csrf):
    calls = []
    client = SupersetClient("https://source.invalid", transport=httpx.MockTransport(
        lambda request: calls.append(request) or httpx.Response(200, json=csrf)))
    with pytest.raises(SQLQueryError, match="CSRF"):
        await execute_sql(client, sql=SQL, database_id=2)
    assert len(calls) == 1 and calls[0].url.path == CSRF


@pytest.mark.parametrize("status", [302, 400, 401, 403, 429, 500, 503])
async def test_http_failures_do_not_redirect_retry_or_leak_provider_body(status):
    client, calls = client_for(lambda request: httpx.Response(
        status, text=SQL + " secret-token", headers={"Location": "https://elsewhere.invalid/private"}))
    with pytest.raises(SQLQueryError) as failure:
        await execute_sql(client, sql=SQL, database_id=2)
    assert SQL not in str(failure.value) and "secret-token" not in str(failure.value)
    assert [call.url.path for call in calls] == [CSRF, EXECUTE]
    assert client.requests_made == 2


async def test_ambiguous_post_network_failure_is_never_retried():
    def fail(request):
        raise httpx.ReadError(SQL + " secret-token", request=request)

    client, calls = client_for(fail)
    with pytest.raises(SQLQueryError, match="transport") as failure:
        await execute_sql(client, sql=SQL, database_id=2)
    assert SQL not in str(failure.value) and "secret-token" not in str(failure.value)
    assert [call.method for call in calls] == ["GET", "POST"]


async def test_auth_failure_is_sanitized_before_csrf():
    client, calls = client_for(payload())
    client._auth_headers = AsyncMock(side_effect=RuntimeError(SQL + " secret-token"))
    with pytest.raises(SQLQueryError, match="authentication") as failure:
        await execute_sql(client, sql=SQL, database_id=2)
    assert SQL not in str(failure.value) and "secret-token" not in str(failure.value)
    assert calls == []


@pytest.mark.parametrize("bad", [
    payload(data=[{"value": None}, {"value": 0}]),
    payload(columns=["value", "value"]), payload(columns=[{"column_name": "value"}, {"name": "value"}]),
    payload(columns=[None]), payload(data=[[1]]), payload(data=[{"other": 1}]),
    payload(data=None), payload(columns=None), payload(query={"limitingFactor": "QUERY"}),
    payload(query={"rows": 2}), payload(query={"limit": 1}), payload(truncated=True),
    payload(displayLimitReached=True), payload(status="failed"),
    payload(status="timed_out"), payload(errors=[{"message": SQL + " secret-token"}]),
    payload(query={"errorMessage": SQL + " secret-token"}),
])
async def test_invalid_partial_limited_or_error_results_are_not_success(bad):
    client, calls = client_for(bad)
    with pytest.raises(SQLQueryError) as failure:
        await execute_sql(client, sql=SQL, database_id=2, max_rows=1)
    assert SQL not in str(failure.value) and "secret-token" not in str(failure.value)
    assert len(calls) == 2


@pytest.mark.parametrize("body", [b'[]', b'not json', b'{"data":[],"data":[]}',
                                  b'{"data":[{"value":NaN}],"columns":["value"]}'])
async def test_invalid_json_and_duplicate_keys_fail_closed(body):
    client, _ = client_for(lambda request: httpx.Response(200, content=body))
    with pytest.raises(SQLQueryError):
        await execute_sql(client, sql=SQL, database_id=2)


async def test_explicit_empty_success_is_distinct_from_pending_empty_data():
    client, _ = client_for(payload(data=[], query={}))
    result = await execute_sql(client, sql=SQL, database_id=2)
    assert result.rows == [] and result.columns == ["value"]
    client, calls = client_for({"status": "running", "data": [], "columns": ["value"]})
    with pytest.raises(SQLQueryError, match="unfinished"):
        await execute_sql(client, sql=SQL, database_id=2)
    assert len(calls) == 2


async def test_max_polls_fails_not_empty_success(monkeypatch):
    monkeypatch.setattr(transport.asyncio, "sleep", AsyncMock())
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"result": "csrf"} if request.url.path == CSRF
                              else {"status": "running", "results_key": "key", "data": []})

    client = SupersetClient("https://source.invalid", transport=httpx.MockTransport(handler))
    with pytest.raises(SQLQueryError, match="unfinished"):
        await execute_sql(client, sql=SQL, database_id=2, max_polls=2)
    assert [call.url.path for call in calls] == [CSRF, EXECUTE, RESULTS, RESULTS]


async def test_identity_change_during_polling_fails():
    def handler(request):
        if request.url.path == CSRF:
            return httpx.Response(200, json={"result": "csrf"})
        if request.url.path == EXECUTE:
            return httpx.Response(202, json={"status": "running", "query_id": 17, "results_key": "key"})
        return httpx.Response(200, json=payload(query_id=18))

    client = SupersetClient("https://source.invalid", transport=httpx.MockTransport(handler))
    with pytest.raises(SQLQueryError, match="identity changed"):
        await execute_sql(client, sql=SQL, database_id=2)


async def test_total_deadline_covers_query_response_without_post_retry():
    calls = []

    async def handler(request):
        calls.append(request)
        if request.url.path == CSRF:
            return httpx.Response(200, json={"result": "csrf"})
        await asyncio.sleep(10)
        raise AssertionError("Deadline should cancel the wait")

    client = SupersetClient("https://source.invalid", transport=httpx.MockTransport(handler))
    with pytest.raises(SQLQueryError, match="deadline"):
        await execute_sql(client, sql=SQL, database_id=2, timeout_seconds=0.02)
    assert [call.url.path for call in calls] == [CSRF, EXECUTE]


async def test_stream_size_limit_stops_reading_and_closes_response():
    class Stream(httpx.AsyncByteStream):
        consumed = 0
        closed = False

        async def __aiter__(self):
            for _ in range(10):
                self.consumed += 1
                yield b" " * 20

        async def aclose(self):
            self.closed = True

    stream = Stream()
    client, _ = client_for(lambda request: httpx.Response(200, stream=stream))
    with pytest.raises(SQLQueryError, match="byte limit"):
        await execute_sql(client, sql=SQL, database_id=2, max_bytes=64)
    assert stream.consumed < 10 and stream.closed


@pytest.mark.parametrize("limit", ["rows", "bytes"])
async def test_preset_bearer_auth_and_existing_stricter_limits_are_respected(limit):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer preset-token"
        if request.url.path == CSRF:
            return httpx.Response(200, json={"result": "csrf"})
        assert json.loads(request.content)["queryLimit"] == 2
        return httpx.Response(200, json=payload(data=[{"value": 1}, {"value": 2}]))

    client = PresetCloudClient("https://workspace.invalid", access_token="preset-token",
                               max_result_rows=1, max_snapshot_bytes=64 if limit == "bytes" else 10000,
                               transport=httpx.MockTransport(handler))
    with pytest.raises(SQLQueryError, match="byte limit" if limit == "bytes" else "row limit"):
        await execute_sql(client, sql=SQL, database_id=2, max_rows=1000, max_bytes=100000)
    assert client.requests_made == 2


async def test_new_session_disables_ambient_proxies_and_redirects(monkeypatch):
    original = httpx.AsyncClient
    options = []

    def session(*args, **kwargs):
        options.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(transport.httpx, "AsyncClient", session)
    client, _ = client_for(payload())
    await execute_sql(client, sql=SQL, database_id=2)
    assert len(options) == 1
    assert options[0]["trust_env"] is False and options[0]["follow_redirects"] is False
