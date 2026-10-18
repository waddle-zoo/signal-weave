"""Bounded SQL Lab transport for SQL already reviewed by the source layer.

This is not SQL validation, authorization, or a read-only security boundary.
The caller also owns Preset data-mode admission. Authentication is delegated to
the existing client; a submission is retried only once after an explicit 401.
"""
from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from .superset_client import SupersetClient

_CSRF = "/api/v1/security/csrf_token/"
_EXECUTE = "/api/v1/sqllab/execute/"
_RESULTS = "/api/v1/sqllab/results/"
_PENDING = {"pending", "running", "queued", "scheduled", "fetching", "processing"}


class SQLQueryError(ValueError):
    """A sanitized SQL Lab transport, result, or admission failure."""


class _Unauthorized(SQLQueryError):
    """An explicit authentication rejection, not an ambiguous execution failure."""


@dataclass(frozen=True)
class SQLQueryResult:
    rows: list[dict]
    columns: list[str]
    query_id: str | None
    client_id: str | None
    results_key: str | None
    received_at: datetime


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SQLQueryError("SQL Lab returned duplicate JSON keys")
        result[key] = value
    return result


def _invalid_constant(value):
    raise SQLQueryError("SQL Lab returned a non-finite number")


async def _request(session, client, method, path, max_bytes, **kwargs):
    client._requests_made += 1
    counts = client._request_path_counts
    counts[path] = counts.get(path, 0) + 1
    async with session.stream(method, path, **kwargs) as response:
        if response.status_code == 401:
            raise _Unauthorized("SQL Lab HTTP request failed (401)")
        if response.status_code not in {200, 202}:
            raise SQLQueryError(f"SQL Lab HTTP request failed ({response.status_code})")
        body = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=min(65_536, max_bytes + 1)):
            if len(body) + len(chunk) > max_bytes:
                raise SQLQueryError("SQL Lab response exceeded the byte limit")
            body.extend(chunk)
        payload = json.loads(body, parse_float=Decimal, parse_constant=_invalid_constant,
                             object_pairs_hook=_unique_object)
        if not isinstance(payload, dict):
            raise SQLQueryError("SQL Lab returned an invalid response object")
        return payload, response.status_code


def _query(payload):
    query = payload.get("query")
    if query is not None and not isinstance(query, dict):
        raise SQLQueryError("SQL Lab returned invalid query metadata")
    return query or {}


def _update_ids(payload, identities):
    query = _query(payload)
    candidates = ((payload.get("query_id"), query.get("serverId"), query.get("queryId")),
                  (payload.get("client_id"), query.get("client_id"), query.get("id")),
                  (payload.get("results_key"), query.get("resultsKey")))
    for field, values in zip(("query_id", "client_id", "results_key"), candidates, strict=True):
        value = next((value for value in values if value is not None), None)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value):
            raise SQLQueryError("SQL Lab returned invalid result identifiers")
        value = str(value)
        if identities[field] is not None and identities[field] != value:
            raise SQLQueryError("SQL Lab result identity changed while polling")
        identities[field] = value


def _pending(payload, status_code):
    query = _query(payload)
    if any(item.get(key) for item in (payload, query) for key in ("error", "errors", "errorMessage")):
        raise SQLQueryError("SQL Lab reported a query error")
    states = [payload.get("status"), query.get("state")]
    if any(state is not None and state not in _PENDING | {"success"} for state in states):
        raise SQLQueryError("SQL Lab query did not complete successfully")
    return status_code == 202 or any(state in _PENDING for state in states) or "data" not in payload


def _rows(payload, max_rows):
    query = _query(payload)
    if any(item.get(key) for item in (payload, query)
           for key in ("truncated", "displayLimitReached", "limit_reached")):
        raise SQLQueryError("SQL Lab returned a truncated result")
    if query.get("limitingFactor") not in (None, "", "NOT_LIMITED", "not_limited"):
        raise SQLQueryError("SQL Lab reported a limited result")
    rows, metadata = payload.get("data"), payload.get("columns")
    if not isinstance(rows, list) or not isinstance(metadata, list):
        raise SQLQueryError("SQL Lab returned invalid rows or columns")
    if len(rows) > max_rows:
        raise SQLQueryError("SQL Lab result exceeded the row limit")
    columns = [column.get("column_name", column.get("name"))
               if isinstance(column, dict) else column for column in metadata]
    if any(not isinstance(column, str) for column in columns) or len(set(columns)) != len(columns):
        raise SQLQueryError("SQL Lab returned invalid or duplicate column names")
    if any(not isinstance(row, dict) or set(row) != set(columns) for row in rows):
        raise SQLQueryError("SQL Lab rows do not match the declared columns")
    count, limit = query.get("rows"), query.get("limit")
    if (isinstance(count, int) and count > len(rows)) or (
        _positive_int(limit) and len(rows) >= limit
    ):
        raise SQLQueryError("SQL Lab result may be incomplete or limited")
    return rows, columns


async def execute_sql(
    client: SupersetClient, *, sql: str, database_id: int,
    catalog: str | None = None, schema: str | None = None, max_rows: int = 1000,
    max_bytes: int = 500000, timeout_seconds: float = 90, max_polls: int = 60,
) -> SQLQueryResult:
    """Fail rather than return partial, timed-out, or truncated rows.

    Only an explicit 401 can refresh authentication and retry submission once.
    SQL Lab 4.x uses a Rison ``q`` object containing the results ``key``.
    Byte limits apply to each decoded HTTP response, not cumulative traffic.
    A timeout stops local waiting; it does not cancel a backend query.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise SQLQueryError("SQL must be nonblank")
    if not all(_positive_int(value) for value in (database_id, max_rows, max_bytes, max_polls)):
        raise SQLQueryError("SQL Lab identifiers and limits must be positive integers")
    if any(value is not None and (not isinstance(value, str) or not value.strip()) for value in (catalog, schema)):
        raise SQLQueryError("SQL Lab catalog and schema must be nonblank strings or null")
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
        raise SQLQueryError("SQL Lab timeout must be finite and positive")
    for name in ("max_result_rows", "max_snapshot_bytes"):
        limit = getattr(client, name, None)
        if limit is not None:
            if not _positive_int(limit):
                raise SQLQueryError("SQL Lab client has invalid response limits")
            if name == "max_result_rows":
                max_rows = min(max_rows, limit)
            else:
                max_bytes = min(max_bytes, limit)
    identities = dict.fromkeys(("query_id", "client_id", "results_key"))
    try:
        async with asyncio.timeout(timeout_seconds):
            headers = await client._auth_headers()
            async with httpx.AsyncClient(base_url=client.base_url, headers={
                **headers, "Accept": "application/json", "Accept-Encoding": "identity",
                "Referer": client.base_url + "/",
            }, transport=client._transport, timeout=timeout_seconds,
                follow_redirects=False, trust_env=False) as session:
                body = {"sql": sql, "database_id": database_id, "runAsync": False,
                        "queryLimit": max_rows + 1}
                body.update({key: value for key, value in (("catalog", catalog), ("schema", schema)) if value is not None})
                for attempt in range(2):
                    try:
                        csrf, _ = await _request(session, client, "GET", _CSRF, max_bytes)
                        token = csrf.get("result")
                        if not isinstance(token, str) or not token.strip():
                            raise SQLQueryError("SQL Lab CSRF token is unavailable")
                        session.headers["X-CSRFToken"] = token
                        payload, status = await _request(session, client, "POST", _EXECUTE, max_bytes, json=body)
                        break
                    except _Unauthorized:
                        if attempt:
                            raise
                        headers = await client._auth_headers(force_refresh=True)
                        if not headers:
                            raise SQLQueryError("SQL Lab authentication refresh is unavailable") from None
                        session.headers.update(headers)
                for poll in range(max_polls + 1):
                    _update_ids(payload, identities)
                    if not _pending(payload, status):
                        rows, columns = _rows(payload, max_rows)
                        return SQLQueryResult(rows, columns, **identities, received_at=datetime.now(timezone.utc))
                    key = identities["results_key"]
                    if key is None or poll == max_polls:
                        raise SQLQueryError("SQL Lab asynchronous query is unfinished or has no results key")
                    if poll:
                        await asyncio.sleep(1)
                    # Quote/escape Rison strings; never interpolate keys into a URL path.
                    escaped = key.replace("!", "!!").replace("'", "!'")
                    payload, status = await _request(session, client, "GET", _RESULTS, max_bytes,
                                                     params={"q": f"(key:'{escaped}')"})
    except SQLQueryError:
        raise
    except TimeoutError:
        raise SQLQueryError("SQL Lab request deadline exceeded; backend query may still be running") from None
    except Exception:
        raise SQLQueryError("SQL Lab authentication, transport, or response failed") from None
