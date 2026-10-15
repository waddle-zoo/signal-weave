"""Exercise the certified native binary against a bounded Superset HTTP fixture.

This is an adapter integration leg, not a Superset-container test. The fixture
speaks the read-only API response shapes already exercised by
``tests/test_superset_client.py`` and keeps every dataset synthetic. The live
mode makes no more than one real Jev request, counted at an explicit local
proxy; the normal MCP and source paths remain the installed binary's own.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from evaluations.installed_trial_transport import (
    _initialize_mcp_session,
    _minimal_environment,
)
from scripts.binary_provenance import verify_binary
from signalweave.mcp_server import AGENT_PROFILE_TOOLS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BINARY = ROOT / "dist" / "signalweave"
DEFAULT_KEY_FILE = Path("/Users/brandonsovran/Downloads/apikey_typesafe")
DEFAULT_OUTPUT = ROOT / "docs/evidence/release-superset-adapter-2026-10-12/results-post-compact-paging.json"
CERTIFIED_BINARY_SHA256 = "6abe5f0e292a688a30c139f917e98cd6635bb4b6bb974597f23e3edfcda9d7b5"
CERTIFIED_SOURCE_SHA256 = "9460d2e8e08a3e06de7309cf6c8d554b17043074d8fa9fe7fbdcee972c1298e2"
CERTIFIED_MCP_PROTOCOL_VERSION = "2025-11-25"
MAX_REAL_JEV_ATTEMPTS = 1
RECEIPT_PAGE_LIMIT = 100
RECEIPT_MAX_PAGES = 100
RECEIPT_MAX_ITEMS = 10_000
RECEIPT_RESPONSE_ENVELOPE_MAX_BYTES = 8192
MAIN_DASHBOARD_ID = "41"
CATALOG_DASHBOARD_ID = "42"
WIDE_CHART_ID = "312"
FIXTURE_USERNAME = "release-fixture-user"
FIXTURE_PASSWORD = "fixture-only-password"
FIXTURE_TOKEN = "fixture-bearer-token"

CARD_POLICY = (
    "Report only numeric facts returned by the selected chart. Choose ignore when the source "
    "retrieves typed rows and no owner-defined exception rule is present. Choose "
    "insufficient_data when retrieval fails, the declared metric is absent or non-numeric, "
    "or a requested conclusion needs missing evidence. Do not infer a comparison, threshold, "
    "population, aggregate, cause, or delivery route from a title or renderer. A chart's "
    "visualization type describes its display; interpret values only from the returned rows "
    "and explicit saved metric fields."
)
CARD_TITLE = "Check the chart's event counts"
CARD_WHAT_TO_WATCH = "Please summarize the event counts shown in the selected chart."
CARD_WHY_WATCH = (
    "I want to know what the saved chart rows contain, without assuming a trend or alert threshold."
)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _chart(
    chart_id: int,
    title: str,
    viz_type: str,
    params: dict[str, Any],
    data: Any,
    *,
    cached: bool | list[bool] = False,
    params_as_json: bool = False,
    query_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": str(chart_id),
        "slice_name": title,
        "viz_type": viz_type,
        "datasource_id": 17,
        "datasource_type": "table",
        "params": json.dumps(params, separators=(",", ":")) if params_as_json else params,
        "query_context": query_context,
        "data": data,
        "cached": cached,
    }


def build_chart_cases() -> list[dict[str, Any]]:
    """Return twelve small chart variants and one 400-row wide table."""

    wide_rows = [
        {"cohort": f"segment-{index:03d}", "events": 100 + (index % 37)}
        for index in range(400)
    ]
    query_context = {
        "datasource": {"id": 17, "type": "table"},
        "queries": [
            {
                "columns": ["event_date"],
                "metrics": ["Revenue"],
                "row_limit": 999999,
                "series_limit": -2,
            }
        ],
        "form_data": {"slice_id": 311, "metrics": ["Revenue"]},
        "result_format": "csv",
        "result_type": "results",
        "force": True,
    }
    cases = [
        _chart(
            301,
            "Regional revenue table",
            "table",
            {"datasource": "17__table", "metrics": ["Revenue"], "groupby": ["region"]},
            [{"region": "North", "Revenue": 120}, {"region": "South", "Revenue": 95}],
            params_as_json=True,
        ),
        _chart(
            302,
            "Daily revenue line",
            "echarts_timeseries_line",
            {
                "datasource": {"id": 17, "type": "table"},
                "metrics": [{"label": "SUM(revenue)"}],
                "granularity_sqla": "event_date",
                "time_grain_sqla": "P1D",
            },
            [
                {"event_date": "2026-10-09", "revenue": 91},
                {"event_date": "2026-10-10", "revenue": 96},
                {"event_date": "2026-10-11", "revenue": 101},
            ],
        ),
        _chart(
            303,
            "Regional stacked revenue and orders",
            "echarts_timeseries_bar",
            {
                "datasource": "17__table",
                "metrics": ["Revenue", "Orders"],
                "granularity_sqla": "event_date",
                "groupby": ["region"],
            },
            [
                [
                    {"event_date": "2026-10-10", "region": "North", "Revenue": 60, "Orders": 6},
                    {"event_date": "2026-10-10", "region": "South", "Revenue": 30, "Orders": 3},
                ],
                [
                    {"event_date": "2026-10-11", "region": "North", "Revenue": 65, "Orders": 7},
                    {"event_date": "2026-10-11", "region": "South", "Revenue": 35, "Orders": 4},
                ],
            ],
            cached=[True, False],
        ),
        _chart(
            304,
            "Genre year heatmap",
            "heatmap_v2",
            {"datasource": "17__table", "metric": "count", "groupby": ["genre"], "x_axis": "year"},
            [
                {"genre": "Drama", "year": 2024, "count": 18},
                {"genre": "Drama", "year": 2025, "count": 21},
                {"genre": "Comedy", "year": 2024, "count": 13},
                {"genre": "Comedy", "year": 2025, "count": 17},
            ],
        ),
        _chart(
            305,
            "Net sales big number",
            "big_number_total",
            {"datasource": "17__table", "metric": {"label": "Net sales"}},
            [{"Net sales": 284}],
        ),
        _chart(
            306,
            "Revenue with null rows",
            "table",
            {"datasource": "17__table", "metrics": ["Revenue"], "groupby": ["region"]},
            [
                {"region": "North", "Revenue": 0},
                {"region": "South", "Revenue": None},
                {"region": "West", "Revenue": 77},
                {"region": "East", "Revenue": None},
            ],
        ),
        _chart(
            307,
            "Unknown renderer numeric result",
            "custom_unknown_visualization",
            {"datasource": "17__table", "metrics": ["value"]},
            [{"value": 11}, {"value": 12}],
        ),
        _chart(
            308,
            "Bubble result",
            "bubble_v2",
            {
                "datasource": "17__table",
                "x": {"label": "SUM(quantity_ordered)"},
                "y": {"label": "COUNT_DISTINCT(country)"},
                "size": "count",
                "entity": "deal_size",
                "series": "product_line",
            },
            {
                "records": [
                    {"deal_size": 120000, "product_line": "hardware", "count": 3},
                    {"deal_size": 85000, "product_line": "software", "count": 2},
                ]
            },
        ),
        _chart(
            309,
            "Orders histogram",
            "histogram_v2",
            {"datasource": "17__table", "column": "orders"},
            {"columns": ["orders", "count"], "data": [[1, 4], [2, 7]]},
        ),
        _chart(
            310,
            "Empty result chart",
            "gantt_chart",
            {
                "datasource": "17__table",
                "series": "priority",
                "start_time": "start_time",
                "end_time": "end_time",
            },
            [],
        ),
        _chart(
            311,
            "Saved query context fallback",
            "table",
            {"datasource": "17__table", "metrics": ["Revenue"]},
            [
                {"event_date": "2026-10-10", "Revenue": 88},
                {"event_date": "2026-10-11", "Revenue": 93},
            ],
            query_context=query_context,
        ),
        _chart(
            312,
            "Wide cohort events table",
            "table",
            {
                "datasource": "17__table",
                "metrics": ["events"],
                "groupby": ["cohort"],
                "row_limit": 500,
            },
            wide_rows,
        ),
    ]
    return cases


class SupersetHTTPFixture:
    """Small HTTP fixture that speaks bounded Superset read API response shapes."""

    def __init__(self) -> None:
        self.charts = {item["id"]: item for item in build_chart_cases()}
        self.requests: list[dict[str, Any]] = []
        self.login_requests = 0
        self.dashboard = {
            "id": int(MAIN_DASHBOARD_ID),
            "dashboard_title": "Release telemetry dashboard",
            "description": "Synthetic loopback fixture for the Superset adapter trial.",
            "owners": [{"username": "fixture-owner"}],
            "url": "http://127.0.0.1/fixture/dashboard/41/",
            "position_json": json.dumps(
                {
                    f"CHART-{chart['id']}": {
                        "type": "CHART",
                        "meta": {
                            "chartId": int(chart["id"]),
                            "sliceName": chart["slice_name"],
                            "viz_type": chart["viz_type"],
                        },
                    }
                    for chart in self.charts.values()
                }
            ),
            # No comparison-window or analytical-comparison declaration is
            # supplied. {} also proves the documented unfiltered fallback case.
            "json_metadata": json.dumps(
                {"default_filters": "{}", "native_filter_configuration": []}
            ),
        }
        self.catalog = [
            self.dashboard,
            {
                "id": int(CATALOG_DASHBOARD_ID),
                "dashboard_title": "Release telemetry archive",
                "description": "Empty secondary catalog entry for pagination.",
                "owners": [],
                "url": "http://127.0.0.1/fixture/dashboard/42/",
                "position_json": "{}",
                "json_metadata": "{}",
            },
        ]
        self.app = Starlette(
            routes=[
                Route("/health", self.health, methods=["GET"]),
                Route("/api/v1/security/login", self.login, methods=["POST"]),
                Route("/api/v1/dashboard/", self.list_dashboards, methods=["GET"]),
                Route("/api/v1/dashboard/{dashboard_id}", self.get_dashboard, methods=["GET"]),
                Route("/api/v1/chart/data", self.post_chart_data, methods=["POST"]),
                Route("/api/v1/chart/{chart_id}/data/", self.get_chart_data, methods=["GET"]),
                Route("/api/v1/chart/{chart_id}", self.get_chart, methods=["GET"]),
            ]
        )

    def _record(self, request: Request, **detail: Any) -> None:
        # Deliberately omit authorization, login payload, body contents and cache IDs.
        self.requests.append(
            {
                "method": request.method,
                "path": request.url.path,
                "query": dict(request.query_params),
                **detail,
            }
        )

    def _authorized(self, request: Request) -> bool:
        return request.headers.get("authorization") == f"Bearer {FIXTURE_TOKEN}"

    async def health(self, request: Request) -> JSONResponse:
        self._record(request)
        return JSONResponse({"status": "healthy"})

    async def login(self, request: Request) -> JSONResponse:
        body = await request.json()
        self.login_requests += 1
        self._record(request, provider=body.get("provider"), refresh=body.get("refresh"))
        if (
            body.get("username") != FIXTURE_USERNAME
            or body.get("password") != FIXTURE_PASSWORD
            or body.get("provider") != "db"
            or body.get("refresh") is not True
        ):
            return JSONResponse({"message": "invalid fixture login"}, status_code=401)
        return JSONResponse({"access_token": FIXTURE_TOKEN, "token_type": "Bearer"})

    async def list_dashboards(self, request: Request) -> JSONResponse:
        if not self._authorized(request):
            return JSONResponse({"message": "unauthorized"}, status_code=401)
        page = max(0, int(request.query_params.get("page", "0")))
        page_size = max(1, int(request.query_params.get("page_size", "100")))
        q_value = request.query_params.get("q")
        items = list(self.catalog)
        if q_value:
            try:
                filters = json.loads(q_value).get("filters", [])
            except (TypeError, ValueError, json.JSONDecodeError):
                return JSONResponse({"message": "invalid q filter"}, status_code=400)
            for item in filters:
                if item.get("col") == "dashboard_title" and item.get("opr") == "ct":
                    term = str(item.get("value", "")).casefold()
                    items = [entry for entry in items if term in entry["dashboard_title"].casefold()]
        self._record(request, page=page, page_size=page_size, result_count=len(items))
        start = page * page_size
        return JSONResponse({"result": items[start : start + page_size], "count": len(items)})

    async def get_dashboard(self, request: Request) -> JSONResponse:
        if not self._authorized(request):
            return JSONResponse({"message": "unauthorized"}, status_code=401)
        dashboard_id = request.path_params["dashboard_id"]
        self._record(request, dashboard_id=dashboard_id)
        item = next((entry for entry in self.catalog if str(entry["id"]) == dashboard_id), None)
        if item is None:
            return JSONResponse({"message": "not found"}, status_code=404)
        return JSONResponse({"result": item})

    async def get_chart(self, request: Request) -> JSONResponse:
        if not self._authorized(request):
            return JSONResponse({"message": "unauthorized"}, status_code=401)
        chart_id = request.path_params["chart_id"]
        self._record(request, chart_id=chart_id)
        chart = self.charts.get(chart_id)
        if chart is None:
            return JSONResponse({"message": "not found"}, status_code=404)
        metadata = {
            key: chart[key]
            for key in ("id", "slice_name", "viz_type", "datasource_id", "datasource_type", "params")
        }
        if chart.get("query_context") is not None:
            metadata["query_context"] = chart["query_context"]
        metadata["url"] = f"http://127.0.0.1/fixture/explore/?slice_id={chart_id}"
        return JSONResponse({"result": metadata})

    def _envelopes(self, chart: dict[str, Any]) -> list[dict[str, Any]]:
        data = chart["data"]
        cache = chart["cached"]
        parts = data if isinstance(cache, list) and isinstance(data, list) and len(cache) == len(data) else [data]
        cache_flags = cache if isinstance(cache, list) and len(cache) == len(parts) else [cache] * len(parts)
        return [
            {
                "data": part,
                "is_cached": flag,
                "cache_key": "fixture-cache-key-must-not-cross-adapter",
            }
            for part, flag in zip(parts, cache_flags, strict=True)
        ]

    async def get_chart_data(self, request: Request) -> JSONResponse:
        if not self._authorized(request):
            return JSONResponse({"message": "unauthorized"}, status_code=401)
        chart_id = request.path_params["chart_id"]
        dashboard_id = request.query_params.get("filters_dashboard_id")
        self._record(request, chart_id=chart_id, dashboard_id=dashboard_id)
        chart = self.charts.get(chart_id)
        if chart is None:
            return JSONResponse({"message": "not found"}, status_code=404)
        if dashboard_id != MAIN_DASHBOARD_ID:
            return JSONResponse({"message": "dashboard filter required"}, status_code=400)
        if chart_id == "311":
            return JSONResponse(
                {"message": "Chart has no query context saved. Please save the chart again."},
                status_code=400,
            )
        return JSONResponse(
            {
                "result": self._envelopes(chart),
                "dashboard_filters": {"applied": True, "dashboard_id": dashboard_id},
            }
        )

    async def post_chart_data(self, request: Request) -> JSONResponse:
        if not self._authorized(request):
            return JSONResponse({"message": "unauthorized"}, status_code=401)
        body = await request.json()
        form_data = body.get("form_data") if isinstance(body.get("form_data"), dict) else {}
        query_id = str(form_data.get("slice_id") or "")
        if not query_id:
            queries = body.get("queries")
            query_id = "312" if isinstance(queries, list) and queries else ""
        chart = self.charts.get(query_id)
        self._record(
            request,
            chart_id=query_id,
            body_bytes=len(_json_bytes(body)),
            result_format=body.get("result_format"),
            result_type=body.get("result_type"),
            force=body.get("force"),
            query_limits=[
                {
                    "row_limit": item.get("row_limit"),
                    "series_limit": item.get("series_limit"),
                }
                for item in body.get("queries", [])
                if isinstance(item, dict)
            ],
        )
        if chart is None:
            return JSONResponse({"message": "saved chart identity required"}, status_code=400)
        return JSONResponse({"result": self._envelopes(chart)})


def _chart_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    charts = snapshot.get("metadata", {}).get("charts", [])
    return {
        "chart_count": len(charts),
        "charts": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "viz_type": item.get("viz_type"),
                "semantic_status": item.get("semantic_status"),
                "row_count": item.get("result_row_count"),
                "observation_count": len(
                    [
                        observation
                        for observation in snapshot.get("observations", [])
                        if observation.get("subject_id", "").startswith(f"{item.get('id')}:")
                    ]
                ),
                "cache_status": item.get("cache_status"),
                "data_scope": item.get("data_scope"),
                "error_present": bool(item.get("error")),
                "semantic_notes": item.get("semantic_notes", []),
            }
            for item in charts
        ],
    }


def _evaluation_diagnostics(response: dict[str, Any]) -> dict[str, Any]:
    """Retain decision/schema evidence without copying the full response."""
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    telemetry = result.get("telemetry") if isinstance(result.get("telemetry"), dict) else {}
    retrieval = result.get("retrieval") if isinstance(result.get("retrieval"), dict) else {}
    observations = result.get("observations") if isinstance(result.get("observations"), list) else []
    evidence = result.get("evidence") if isinstance(result.get("evidence"), list) else []
    findings = (
        result.get("evidence_findings")
        if isinstance(result.get("evidence_findings"), list)
        else []
    )
    watches = result.get("watch_results") if isinstance(result.get("watch_results"), list) else []
    questions = result.get("question_results") if isinstance(result.get("question_results"), list) else []
    selected_sources = (
        retrieval.get("selected_sources")
        if isinstance(retrieval.get("selected_sources"), list)
        else []
    )

    def excerpt(value: Any, limit: int = 1200) -> str:
        return value[:limit] if isinstance(value, str) else ""

    return {
        "response_mode": response.get("response_mode"),
        "details_available": response.get("details_available"),
        "result_keys": sorted(result),
        "outcome": result.get("outcome"),
        "confidence": result.get("confidence"),
        "probabilities": result.get("probabilities", {}),
        "summary_excerpt": excerpt(result.get("summary")),
        "rationale_excerpt": excerpt(result.get("rationale")),
        "watch_results": [
            {
                "key": item.get("key"),
                "status": item.get("status"),
                "probability": item.get("probability"),
                "probabilities": item.get("probabilities", {}),
            }
            for item in watches
            if isinstance(item, dict)
        ],
        "question_results": [
            {
                "key": item.get("key"),
                "status": item.get("status"),
                "probability": item.get("probability"),
            }
            for item in questions
            if isinstance(item, dict)
        ],
        "source_count": telemetry.get("source_count"),
        "source_count_reported_by_telemetry": "source_count" in telemetry,
        "source_keys_count": len(result.get("source_keys", []))
        if isinstance(result.get("source_keys"), list)
        else None,
        "observation_count": len(observations),
        "evidence_count": len(evidence),
        "evidence_finding_count": len(findings),
        "analysis_count": len(result.get("analyses", []))
        if isinstance(result.get("analyses"), list)
        else None,
        "selected_sources": [
            {"adapter": item.get("adapter"), "resource": item.get("resource")}
            for item in selected_sources
            if isinstance(item, dict)
        ],
        "retrieval_candidate_count": retrieval.get("candidate_count"),
        "telemetry": {
            key: telemetry.get(key)
            for key in (
                "source_count",
                "observation_count",
                "evidence_count",
                "jev_requests",
                "jev_input_tokens",
                "jev_output_tokens",
                "jev_payload_bytes",
                "jev_payload_budget_bytes",
                "warnings",
            )
            if key in telemetry
        },
        "workflow": {
            key: result["workflow"].get(key)
            for key in ("status", "action", "required_source_keys")
            if isinstance(result.get("workflow"), dict) and key in result["workflow"]
        },
    }


def _safe_stdout(completed: subprocess.CompletedProcess[str]) -> str:
    # Used only for harmless noninteractive commands; credentials never enter
    # these command arguments or stdout. Keep any unexpected message bounded.
    return completed.stdout[:8000]


def _run_command(
    binary: Path, args: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 90
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(binary), *args],
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


async def _call_tool(session: ClientSession, name: str, arguments: dict[str, Any]) -> Any:
    response = await session.call_tool(name, arguments)
    if response.isError:
        raise RuntimeError(f"MCP tool {name} returned an error; details withheld")
    if response.structuredContent is not None:
        return response.structuredContent
    for block in response.content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            try:
                return json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
    raise RuntimeError(f"MCP tool {name} returned no structured result")


async def _read_receipt_list_pages(
    session: ClientSession,
    *,
    receipt_id: str,
    result_path: list[str],
    expected_count: int | None = None,
) -> dict[str, Any]:
    """Consume one complete receipt list with per-page byte and item bounds.

    Only counters, an ordered digest and the exact terminal item are retained;
    page contents are not copied into the result artifact.
    """
    offset = 0
    total: int | None = None
    item_count = 0
    page_count = 0
    total_page_bytes = 0
    total_response_bytes = 0
    max_page_bytes = 0
    max_response_bytes = 0
    tail_item: Any = None
    item_digest = hashlib.sha256()

    while True:
        if page_count >= RECEIPT_MAX_PAGES or item_count > RECEIPT_MAX_ITEMS:
            raise ValueError("receipt paging exceeded the trial's hard bound")
        response = await _call_tool(
            session,
            "get_decision_receipt",
            {
                "receipt_id": receipt_id,
                "result_path": result_path,
                "offset": offset,
                "limit": RECEIPT_PAGE_LIMIT,
            },
        )
        page = response.get("result_page") if isinstance(response, dict) else None
        if not isinstance(page, dict) or response.get("status") != "found":
            raise ValueError("receipt page response was incomplete")
        if page.get("path") != result_path or page.get("kind") != "list":
            raise ValueError("receipt page did not match the requested list")
        if page.get("offset") != offset:
            raise ValueError("receipt page offset did not match the request")
        items = page.get("items")
        page_total = page.get("total")
        byte_budget = page.get("byte_budget")
        if (
            not isinstance(items, list)
            or isinstance(page_total, bool)
            or not isinstance(page_total, int)
            or page_total < 0
            or isinstance(byte_budget, bool)
            or not isinstance(byte_budget, int)
            or byte_budget <= 0
        ):
            raise ValueError("receipt page omitted bounded list metadata")
        if total is None:
            total = page_total
            if total > RECEIPT_MAX_ITEMS:
                raise ValueError("receipt section exceeds the trial item bound")
            if expected_count is not None and total != expected_count:
                raise ValueError("receipt section total differs from its advertised count")
        elif page_total != total:
            raise ValueError("receipt section total changed while paging")
        if len(items) > RECEIPT_PAGE_LIMIT or offset + len(items) > total:
            raise ValueError("receipt page exceeded the requested item bound")

        page_bytes = len(_json_bytes(page))
        response_bytes = len(_json_bytes(response))
        if page_bytes > byte_budget:
            raise ValueError("receipt page exceeded its declared byte budget")
        if response_bytes > byte_budget + RECEIPT_RESPONSE_ENVELOPE_MAX_BYTES:
            raise ValueError("receipt page response exceeded its bounded envelope")
        if page.get("oversized_item") is not None:
            raise ValueError("receipt page contains an oversized item marker")

        page_count += 1
        total_page_bytes += page_bytes
        total_response_bytes += response_bytes
        max_page_bytes = max(max_page_bytes, page_bytes)
        max_response_bytes = max(max_response_bytes, response_bytes)
        for item in items:
            encoded = _json_bytes(item)
            item_digest.update(len(encoded).to_bytes(8, "big"))
            item_digest.update(encoded)
            tail_item = item
        item_count += len(items)

        has_more = page.get("has_more")
        next_offset = page.get("next_offset")
        if not isinstance(has_more, bool):
            raise ValueError("receipt page omitted its continuation flag")
        if not has_more:
            if item_count != total or next_offset is not None:
                raise ValueError("receipt paging stopped before the full list was read")
            break
        if not items or next_offset != offset + len(items):
            raise ValueError("receipt paging did not advance monotonically")
        offset = next_offset

    return {
        "path": result_path,
        "expected_count": expected_count,
        "reported_total": total,
        "consumed_item_count": item_count,
        "page_count": page_count,
        "page_limit": RECEIPT_PAGE_LIMIT,
        "total_page_json_bytes": total_page_bytes,
        "total_response_json_bytes": total_response_bytes,
        "max_page_json_bytes": max_page_bytes,
        "max_response_json_bytes": max_response_bytes,
        "ordered_items_sha256": item_digest.hexdigest(),
        "exact_tail_item": tail_item,
        "complete": item_count == total,
    }


async def _read_evaluation_receipt_pages(
    session: ClientSession,
    evaluation: dict[str, Any],
    *,
    expected_observations: int,
) -> dict[str, Any]:
    """Read observation/evidence pages from the receipt without new inference."""
    access = evaluation.get("evidence_access")
    access = access if isinstance(access, dict) else {}
    receipt = evaluation.get("receipt")
    receipt = receipt if isinstance(receipt, dict) else {}
    receipt_id = access.get("receipt_id") or receipt.get("receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id:
        return {
            "status": "receipt_id_unavailable",
            "evidence_access_advertised": bool(access),
            "sections": {},
        }

    advertised_sections = access.get("available_sections")
    advertised_sections = advertised_sections if isinstance(advertised_sections, list) else []

    def advertised_count(name: str) -> int | None:
        for item in advertised_sections:
            if not isinstance(item, dict) or item.get("path") != [name]:
                continue
            count = item.get("count")
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                return count
        return None

    sections: dict[str, Any] = {}
    for name in ("observations", "evidence"):
        expected = expected_observations if name == "observations" else advertised_count(name)
        try:
            sections[name] = await _read_receipt_list_pages(
                session,
                receipt_id=receipt_id,
                result_path=[name],
                expected_count=expected,
            )
        except Exception as error:
            # Preserve an actionable, secret-free status if a later binary's
            # paging contract changes; never serialize an exception message.
            sections[name] = {
                "path": [name],
                "expected_count": expected,
                "complete": False,
                "error_type": type(error).__name__,
            }
    all_complete = all(section.get("complete") is True for section in sections.values())
    return {
        "status": "complete" if all_complete else "incomplete",
        "evidence_access_advertised": bool(access),
        "advertised_coverage": access.get("coverage"),
        "advertised_section_counts": {
            name: advertised_count(name) for name in ("observations", "evidence")
        },
        "sections": sections,
        "source_or_model_calls_from_paging": 0,
        "raw_pages_retained": False,
    }


@asynccontextmanager
async def _serve_loopback(app: Any, *, label: str):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError(f"{label} loopback server did not start")
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task
        sock.close()


class JevRequestProxy:
    """Count bounded real provider attempts without recording source payloads."""

    def __init__(self, max_attempts: int = MAX_REAL_JEV_ATTEMPTS) -> None:
        self.max_attempts = max_attempts
        self.requests: list[dict[str, Any]] = []
        self.rejected_for_budget = 0
        self.route = ""
        self._lock = asyncio.Lock()

    async def handle(self, request: Request) -> Response:
        body = await request.body()
        try:
            payload = json.loads(body)
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        async with self._lock:
            if len(self.requests) >= self.max_attempts:
                self.rejected_for_budget += 1
                return JSONResponse({"error": "trial_request_budget_exhausted"}, status_code=429)
            attempt = {
                "attempt": len(self.requests) + 1,
                "model": payload.get("model") if isinstance(payload, dict) else None,
                "request_bytes": len(body),
                "state_bytes": len(_json_bytes(payload.get("state"))) if isinstance(payload, dict) and "state" in payload else None,
                "question_count": len(payload.get("questions", {})) if isinstance(payload, dict) and isinstance(payload.get("questions"), dict) else None,
                "status_code": None,
                "usage": None,
            }
            self.requests.append(attempt)
        started = time.perf_counter()
        headers = {"content-type": request.headers.get("content-type", "application/json")}
        authorization = request.headers.get("authorization")
        if authorization:
            headers["authorization"] = authorization
        try:
            async with httpx.AsyncClient(
                base_url="https://api.typesafe.ai",
                timeout=60,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                upstream = await client.post("/v1/systemone", content=body, headers=headers)
            upstream_payload: Any = None
            try:
                upstream_payload = upstream.json()
            except ValueError:
                pass
            usage = upstream_payload.get("usage") if isinstance(upstream_payload, dict) else None
            attempt.update(
                status_code=upstream.status_code,
                usage=usage if isinstance(usage, dict) else None,
                seconds=round(time.perf_counter() - started, 3),
            )
            return Response(
                upstream.content,
                status_code=upstream.status_code,
                media_type=upstream.headers.get("content-type", "application/json"),
            )
        except Exception as error:
            # Record the exception class only. HTTP libraries may put URLs or
            # request details into messages; neither is needed for this report.
            attempt.update(
                status_code="transport_error",
                error_type=type(error).__name__,
                seconds=round(time.perf_counter() - started, 3),
            )
            return JSONResponse({"error": "upstream_transport_error"}, status_code=502)


@asynccontextmanager
async def _jev_proxy(proxy: JevRequestProxy):
    route = __import__("secrets").token_urlsafe(24)
    proxy.route = route
    app = Starlette(routes=[Route(f"/{route}/v1/systemone", proxy.handle, methods=["POST"])])
    async with _serve_loopback(app, label="Jev counter proxy") as url:
        yield f"{url}/{route}"


def _assert_certified_binary(binary: Path) -> dict[str, Any]:
    identity = verify_binary(binary, ROOT)
    if identity.get("binary_sha256") != CERTIFIED_BINARY_SHA256:
        raise RuntimeError("native binary SHA-256 does not match the certified trial candidate")
    if identity.get("source_sha256") != CERTIFIED_SOURCE_SHA256:
        raise RuntimeError("native source fingerprint does not match the certified trial candidate")
    if identity.get("version") != "0.2.0rc2":
        raise RuntimeError("native binary version does not match the certified trial candidate")
    return identity


def _read_health_output(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        decoded = json.loads(completed.stdout)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"exit_code": completed.returncode, "json_output": False}
    messages = decoded.get("messages", []) if isinstance(decoded, dict) else []
    return {
        "exit_code": completed.returncode,
        "json_output": isinstance(decoded, dict),
        "mode": decoded.get("mode") if isinstance(decoded, dict) else None,
        "healthy": bool(decoded.get("healthy")) if isinstance(decoded, dict) else False,
        "messages": [str(item)[:500] for item in messages if isinstance(item, str)],
    }


async def run_trial(
    *,
    binary: Path = DEFAULT_BINARY,
    key_file: Path = DEFAULT_KEY_FILE,
    output: Path = DEFAULT_OUTPUT,
    live_jev: bool = True,
) -> dict[str, Any]:
    binary = binary.expanduser().resolve()
    key_file = key_file.expanduser().resolve()
    if live_jev and (not key_file.is_file() or key_file.is_symlink()):
        raise RuntimeError("live Jev mode requires a regular key file")

    fixture = SupersetHTTPFixture()
    jev_proxy = JevRequestProxy()
    result: dict[str, Any] = {
        "trial": "release_superset_adapter_trial",
        "date": "2026-10-12",
        "source_classification": "loopback HTTP fixture; not an actual Superset container",
        "fixture_protocol": "Superset read-only REST response shapes based on existing client tests",
        "live_jev_requested": live_jev,
        "live_jev_max_forwarded_attempts": MAX_REAL_JEV_ATTEMPTS if live_jev else 0,
        "card_policy": CARD_POLICY,
        "comparison_metadata_injected": False,
        "analytical_comparisons_injected": False,
        "card_source_scope": {
            "adapter": "superset",
            "resource": f"dashboard:{MAIN_DASHBOARD_ID}",
            "chart_ids": [WIDE_CHART_ID],
        },
    }

    with tempfile.TemporaryDirectory(prefix="release-superset-adapter-") as temporary:
        work = Path(temporary).resolve()
        home = work / "private-home"
        (work / "tmp").mkdir(mode=0o700)
        home.mkdir(mode=0o700)
        key_copy = work / "typesafe.key"
        source_password = work / "superset-password"
        if live_jev:
            shutil.copyfile(key_file, key_copy)
            key_copy.chmod(0o600)
        else:
            key_copy.write_text("offline-not-a-real-key\n", encoding="utf-8")
            key_copy.chmod(0o600)
        source_password.write_text(FIXTURE_PASSWORD + "\n", encoding="utf-8")
        source_password.chmod(0o600)

        environment = _minimal_environment(home)
        environment.update(
            {
                "SIGNALWEAVE_MCP_PROFILE": "agent",
                "TYPESAFE_MAX_RETRIES": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        async with _serve_loopback(fixture.app, label="Superset fixture") as superset_url:
            result["fixture_url"] = superset_url
            # This is the exact certified candidate supplied by the coordinator.
            binary_before = await asyncio.to_thread(_assert_certified_binary, binary)
            setup = await asyncio.to_thread(
                _run_command,
                binary,
                [
                    "setup",
                    "--profile",
                    "agent",
                    "--non-interactive",
                    "--home",
                    str(home),
                    "--key-file",
                    str(key_copy),
                    "--source",
                    "superset",
                    "--url",
                    superset_url,
                    "--username",
                    FIXTURE_USERNAME,
                    "--secret-file",
                    str(source_password),
                    "--decision-provider",
                    "jev",
                    "--tenant",
                    "release-superset-fixture",
                    "--principal",
                    "release-superset-adapter-trial",
                    "--no-register-agent",
                ],
                cwd=work,
                env=environment,
            )
            if setup.returncode:
                raise RuntimeError("certified native setup failed; command output withheld")
            result["native_setup"] = {
                "exit_code": setup.returncode,
                "profile": "agent",
                "source": "superset",
                "agent_registration": "disabled",
                "private_home_isolated": True,
                "credentials_printed": False,
            }

            health = await asyncio.to_thread(
                _run_command,
                binary,
                ["health", "--home", str(home), "--live", "--json"],
                cwd=work,
                env=environment,
            )
            health_report = _read_health_output(health)
            if health.returncode:
                raise RuntimeError("native health --live failed; diagnostic output withheld")
            result["native_health_live"] = health_report

            if live_jev:
                async with _jev_proxy(jev_proxy) as jev_url:
                    environment_with_jev = _minimal_environment(home, jev_url=jev_url)
                    environment_with_jev.update(
                        {
                            "SIGNALWEAVE_MCP_PROFILE": "agent",
                            "TYPESAFE_MAX_RETRIES": "0",
                            "PYTHONDONTWRITEBYTECODE": "1",
                        }
                    )
                    result.update(
                        await _run_native_mcp_trial(
                            binary=binary,
                            home=home,
                            work=work,
                            environment=environment_with_jev,
                            fixture=fixture,
                            live_jev=True,
                            jev_proxy=jev_proxy,
                        )
                    )
            else:
                result.update(
                    await _run_native_mcp_trial(
                        binary=binary,
                        home=home,
                        work=work,
                        environment=environment,
                        fixture=fixture,
                        live_jev=False,
                        jev_proxy=jev_proxy,
                    )
                )

            binary_after = await asyncio.to_thread(_assert_certified_binary, binary)
            result["binary_identity"] = {
                "before": binary_before,
                "after": binary_after,
                "unchanged": binary_before["binary_sha256"] == binary_after["binary_sha256"],
            }
            if not result["binary_identity"]["unchanged"]:
                raise RuntimeError("native binary changed during the trial")

    result["fixture_http"] = {
        "login_requests": fixture.login_requests,
        "request_counts": dict(sorted(Counter(item["path"] for item in fixture.requests).items())),
        "dashboard_scoped_chart_data_requests": sum(
            1
            for item in fixture.requests
            if item["path"].endswith("/data/")
            and item.get("dashboard_id") == MAIN_DASHBOARD_ID
        ),
        "chart_query_context_fallback_posts": sum(
            1
            for item in fixture.requests
            if item["method"] == "POST" and item["path"] == "/api/v1/chart/data"
        ),
        "saved_query_context_post_summaries": [
            {
                "chart_id": item.get("chart_id"),
                "body_bytes": item.get("body_bytes"),
                "result_format": item.get("result_format"),
                "result_type": item.get("result_type"),
                "force": item.get("force"),
                "query_limits": item.get("query_limits"),
            }
            for item in fixture.requests
            if item["method"] == "POST" and item["path"] == "/api/v1/chart/data"
        ],
        "credentials_or_cache_keys_recorded": False,
    }
    result["jev_proxy"] = {
        "forwarded_attempts": len(jev_proxy.requests),
        "budget_rejections": jev_proxy.rejected_for_budget,
        "max_forwarded_attempts": jev_proxy.max_attempts,
        "requests": jev_proxy.requests,
        "raw_request_or_response_bodies_recorded": False,
    }
    result["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output.chmod(0o600)
    return result


async def _run_native_mcp_trial(
    *,
    binary: Path,
    home: Path,
    work: Path,
    environment: dict[str, str],
    fixture: SupersetHTTPFixture,
    live_jev: bool,
    jev_proxy: JevRequestProxy,
) -> dict[str, Any]:
    parameters = StdioServerParameters(
        command=str(binary),
        args=["serve", "--home", str(home), "--profile", "agent"],
        cwd=str(work),
        env=environment,
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            initialized = await _initialize_mcp_session(session)
            protocol_version = str(getattr(initialized, "protocolVersion", ""))
            if protocol_version != CERTIFIED_MCP_PROTOCOL_VERSION:
                raise RuntimeError("native MCP protocol differs from the certified trial contract")
            tools = (await session.list_tools()).tools
            tool_names = sorted(tool.name for tool in tools)
            if set(tool_names) != set(AGENT_PROFILE_TOOLS):
                raise RuntimeError("native binary tool list differs from the certified default agent profile")

            guide = await _call_tool(session, "get_signalweave_guide", {"task": "start"})
            guide_text = json.dumps(guide, ensure_ascii=False).casefold()
            instruction_text = str(getattr(initialized, "instructions", "") or "").casefold()
            combined_guidance = f"{guide_text}\n{instruction_text}"
            guide_evidence = {
                "report_before_automation": "useful current report" in combined_guidance,
                "pending_alert_criteria_do_not_block_reporting": "do not withhold a useful current report" in combined_guidance,
                "explicit_fallback_instructions_present": "honor an owner's explicit fallback" in combined_guidance,
                "explicit_fallback_check_scope": "phrase-presence check across guide output and MCP server instructions; not a behavior test",
            }

            first_page = await _call_tool(
                session,
                "search_catalog",
                {"query": "Release telemetry", "adapter": "superset", "limit": 1},
            )
            second_page = None
            if first_page.get("next_cursor"):
                second_page = await _call_tool(
                    session,
                    "search_catalog",
                    {
                        "query": "Release telemetry",
                        "adapter": "superset",
                        "limit": 1,
                        "cursor": first_page["next_cursor"],
                    },
                )
            catalog_refs = [
                item["resource"]
                for page in (first_page, second_page or {})
                for item in page.get("resources", [])
            ]
            if len(catalog_refs) != 2 or not first_page.get("has_more") or not second_page:
                raise RuntimeError("native catalog pagination did not return both fixture dashboards")

            dashboard_inspection = await _call_tool(
                session,
                "inspect_resource",
                {
                    "adapter": "superset",
                    "resource": f"dashboard:{MAIN_DASHBOARD_ID}",
                    "label": "Release telemetry dashboard",
                },
            )
            dashboard_snapshot_bytes = len(_json_bytes(dashboard_inspection))
            dashboard_rows = _chart_summary(dashboard_inspection)
            chart_coverage = {item["id"]: item for item in dashboard_rows["charts"]}
            if len(chart_coverage) != 12:
                raise RuntimeError("dashboard inspection did not return all twelve fixture chart shapes")
            wide_chart = chart_coverage[WIDE_CHART_ID]
            if wide_chart["row_count"] != 400 or wide_chart["observation_count"] != 400:
                raise RuntimeError("wide chart did not retain 400 rows as 400 numeric observations")

            chart_inspection = await _call_tool(
                session,
                "inspect_resource",
                {
                    "adapter": "superset",
                    "resource": f"chart:{WIDE_CHART_ID}",
                    "label": "Wide cohort events table",
                },
            )
            chart_snapshot_bytes = len(_json_bytes(chart_inspection))
            chart_observation_count = len(chart_inspection.get("observations", []))
            if chart_observation_count != 400:
                raise RuntimeError("chart-scoped inspection did not retain 400 numeric observations")

            cache_blob = _json_bytes(dashboard_inspection).decode("utf-8")
            if "fixture-cache-key-must-not-cross-adapter" in cache_blob:
                raise RuntimeError("provider cache key unexpectedly crossed the adapter boundary")
            catalog_calls = [item for item in fixture.requests if item["path"] == "/api/v1/dashboard/"]
            pagination = {
                "page_count": len(catalog_calls),
                "requested_pages": [item.get("page") for item in catalog_calls],
                "selected_refs": catalog_refs,
                "complete": len(catalog_refs) == 2,
            }
            no_comparison_contracts = (
                not dashboard_inspection.get("analytical_comparisons")
                and not dashboard_inspection.get("contract", {}).get("comparison_contracts")
                and not dashboard_inspection.get("contract", {}).get("available_comparison_windows")
            )
            if not no_comparison_contracts:
                raise RuntimeError("fixture unexpectedly supplied comparison semantics")

            result: dict[str, Any] = {
            "native_mcp": {
                    "initialized": True,
                "protocol_version": protocol_version,
                    "profile": "agent",
                    "tools": tool_names,
                    "tool_count": len(tool_names),
                    "exact_default_tool_contract": True,
                    "guide": guide_evidence,
            },
                "catalog_pagination": pagination,
                "dashboard_inspection": {
                    **dashboard_rows,
                    "snapshot_json_bytes": dashboard_snapshot_bytes,
                    "numeric_observation_count": len(dashboard_inspection.get("observations", [])),
                    "dashboard_scope": dashboard_inspection.get("metadata", {}).get("dashboard_scope"),
                    "contract_comparison_windows": dashboard_inspection.get("contract", {}).get("available_comparison_windows", []),
                    "analytical_comparisons": len(dashboard_inspection.get("analytical_comparisons", [])),
                    "no_comparison_contracts_injected": no_comparison_contracts,
                    "provider_cache_key_leaked": False,
                },
                "chart_scope_inspection": {
                    "resource": f"chart:{WIDE_CHART_ID}",
                    "snapshot_json_bytes": chart_snapshot_bytes,
                    "numeric_observations": chart_observation_count,
                    "contract_comparison_windows": chart_inspection.get("contract", {}).get("available_comparison_windows", []),
                    "analytical_comparisons": len(chart_inspection.get("analytical_comparisons", [])),
                    "semantic_status": chart_inspection.get("metadata", {}).get("semantic_status"),
                },
                "source_payload_check": {
                    "wide_chart_rows": wide_chart["row_count"],
                    "wide_chart_numeric_observations": wide_chart["observation_count"],
                    "dashboard_snapshot_bytes": dashboard_snapshot_bytes,
                    "chart_snapshot_bytes": chart_snapshot_bytes,
                    "result_under_default_1mb_snapshot_limit": max(
                        dashboard_snapshot_bytes, chart_snapshot_bytes
                    ) < 1_000_000,
                },
            }

            card = await _call_tool(
                session,
                "onboard_insight_card",
                {
                    "title": CARD_TITLE,
                    "what_to_watch": CARD_WHAT_TO_WATCH,
                    "why_watch": CARD_WHY_WATCH,
                    "decision_guidance": CARD_POLICY,
                    "selected_sources": [
                        {
                            "ref": f"superset|dashboard:{MAIN_DASHBOARD_ID}",
                            "key": "wide-chart",
                            "label": "Release telemetry dashboard: wide cohort events table",
                            "parameters": {"chart_ids": [WIDE_CHART_ID]},
                        }
                    ],
                    "adapter": "superset",
                    "response_mode": "compact",
                    "retrieval_mode": "fixed",
                    "investigation_mode": "none",
                },
            )
            card_id = card.get("card", {}).get("id")
            if not card_id:
                raise RuntimeError("native onboarding did not save the exact-source draft card")
            review = await _call_tool(
                session,
                "review_insight_card",
                {"card_id": card_id, "adapter": "superset", "response_mode": "compact"},
            )
            readiness = review.get("review", {}).get("readiness_status")
            if readiness != "ready_for_approval":
                result["card_preflight"] = {
                    "card_id": card_id,
                    "readiness_status": readiness,
                    "blocker_codes": [
                        item.get("code") for item in review.get("review", {}).get("blockers", [])
                    ],
                    "approved_card_execution": "not run; source review did not admit approval",
                }
                return result
            approval = await _call_tool(
                session,
                "approve_insight_card",
                {"card_id": card_id, "actor": "release-superset-fixture-reviewer", "adapter": "superset"},
            )
            if approval.get("status") != "approved":
                raise RuntimeError("native approval tool did not approve the reviewed fixture card")
            result["card_preflight"] = {
                "card_id": card_id,
                "readiness_status": readiness,
                "status": approval.get("status"),
                "review_actor": "release-superset-fixture-reviewer (synthetic trial actor)",
                "workflow_acceptance": approval.get("workflow_acceptance", {}).get("status"),
                "delivery_methods": approval.get("card", {}).get("delivery_methods", []),
            }
            if not live_jev:
                result["approved_card_execution"] = "not run; offline mode intentionally did not make a Jev call"
                return result
            if len(jev_proxy.requests) >= jev_proxy.max_attempts:
                result["approved_card_execution"] = "not run; Jev attempt budget already exhausted during source review"
                return result
            evaluation = await _call_tool(
                session,
                "evaluate_insight_card",
                {
                    "card_id": card_id,
                    "idempotency_key": "release-superset-adapter-fixture-2026-10-12",
                    "actor": "release-superset-adapter-trial",
                    "response_mode": "compact",
                },
            )
            evaluation_result = evaluation.get("result", {})
            evaluation_bytes = len(_json_bytes(evaluation))
            receipt_paging = await _read_evaluation_receipt_pages(
                session,
                evaluation,
                expected_observations=chart_observation_count,
            )
            result["receipt_evidence_paging"] = receipt_paging
            result["approved_card_execution"] = {
                "status": "completed",
                "card_id": card_id,
                "source_ref": f"superset|dashboard:{MAIN_DASHBOARD_ID}",
                "source_parameters": {"chart_ids": [WIDE_CHART_ID]},
                "outcome": evaluation_result.get("outcome"),
                "delivery_enabled": evaluation.get("receipt", {}).get("delivery_enabled"),
                "evaluator": evaluation_result.get("evaluator"),
                "source_count": (
                    evaluation_result.get("telemetry", {}).get("source_count")
                    if isinstance(evaluation_result.get("telemetry"), dict)
                    else None
                ),
                "result_json_bytes": evaluation_bytes,
                "response_has_error": bool(evaluation_result.get("error")),
                "full_raw_result_persisted": False,
                "decision_diagnostics": _evaluation_diagnostics(evaluation),
            }
            result["evaluation_payload_check"] = {
                "compact_mcp_response_bytes": evaluation_bytes,
                "jeV_state_bytes": jev_proxy.requests[-1].get("state_bytes") if jev_proxy.requests else None,
                "jeV_request_bytes": jev_proxy.requests[-1].get("request_bytes") if jev_proxy.requests else None,
                "jeV_input_tokens": (jev_proxy.requests[-1].get("usage") or {}).get("input_tokens") if jev_proxy.requests else None,
                "jeV_output_tokens": (jev_proxy.requests[-1].get("usage") or {}).get("output_tokens") if jev_proxy.requests else None,
                "jeV_attempts_so_far": len(jev_proxy.requests),
                "source_numeric_observations": chart_observation_count,
                "receipt_paging_status": receipt_paging.get("status"),
            }
            return result


async def _main(args: argparse.Namespace) -> None:
    result = await run_trial(
        binary=args.binary,
        key_file=args.key_file,
        output=args.output,
        live_jev=args.live_jev,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--key-file", type=Path, default=DEFAULT_KEY_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--no-live-jev",
        dest="live_jev",
        action="store_false",
        help="Run native setup, catalog, inspection and card approval without provider calls.",
    )
    parser.set_defaults(live_jev=True)
    args = parser.parse_args()
    os.umask(0o077)
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
