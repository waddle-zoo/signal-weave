# Superset Semantic Monitor MCP

An intentionally small MCP server for push-based analytics over Apache Superset.

Dashboard owners describe what matters in natural language. The server compiles that intent into a versioned monitoring plan, runs deterministic metric calculations, and uses TypeSafe for the semantic decisions that SQL and thresholds cannot express cleanly.

It is not a replacement for Superset, Airflow, Temporal, or LangGraph. It is a decision layer that can be called by an existing agent or scheduler.

## First vertical slice

```text
Superset dashboard + owner intent
        -> monitoring plan
        -> deterministic observations
        -> TypeSafe/heuristic decision
        -> evidence-backed alert or no-op
```

The initial outcome vocabulary is:

- `ignore`
- `investigate`
- `notify`
- `escalate`
- `insufficient_data`

The TypeSafe path uses the official Python SDK when `TYPESAFE_MODE=jev`. The default `heuristic` path is deterministic and makes local development, tests, and offline demos useful without an API key.

## Run locally

```bash
uv sync --extra dev
uv run semantic-monitor simulate --scenario all
uv run pytest
uv run ruff check .
```

Run the MCP server:

```bash
TYPESAFE_MODE=heuristic uv run semantic-monitor serve --transport streamable-http
```

For the TypeSafe path, point `TYPESAFE_API_KEY_FILE` at a file that contains the key. The key is read at runtime and is never copied into the repository:

```bash
TYPESAFE_MODE=jev \
TYPESAFE_API_KEY_FILE=/path/to/apikey_typesafe \
uv run semantic-monitor simulate --scenario revenue_decline
```

## Docker

The compose stack includes a local Superset, Postgres metadata storage, Redis, and the monitor MCP server. It also loads Superset's example data where supported by the image.

```bash
docker compose up --build
```

The MCP server is available at `http://localhost:18000/mcp` and Superset at `http://localhost:8088` (`admin` / `admin`). Set `MONITOR_PORT_HOST` if that port is also occupied.

The same service exposes `POST http://localhost:18000/webhooks/evaluate` for push-triggered runs. Send `{"monitor_id":"..."}` from a Superset alert, webhook relay, or existing scheduler. Set `PUSH_WEBHOOK_TOKEN` to require a bearer token. The endpoint evaluates the saved card and returns the same evidence-backed decision as the MCP tool; delivery is intentionally left to the caller.

For a real TypeSafe run without putting the key in an environment file:

```bash
docker compose run --rm \
  -e TYPESAFE_MODE=jev \
  -e TYPESAFE_API_KEY_FILE=/run/secrets/typesafe_api_key \
  -v /Users/brandonsovran/Downloads/apikey_typesafe:/run/secrets/typesafe_api_key:ro \
  monitor python -m semantic_monitor.cli simulate --scenario revenue_decline
```

## Design rules

1. Superset and ordinary code calculate facts; TypeSafe interprets bounded state.
2. Natural-language intent compiles into a reviewable plan; it does not generate arbitrary SQL at runtime.
3. High-confidence results may notify; ambiguous results stay visible as `investigate` or `insufficient_data`.
4. Recipients come from explicit allowlisted groups, never invented names.
5. The same evaluation core serves MCP calls and future scheduled push runners.
