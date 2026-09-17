# SignalWeave security and operations review

This is the boundary a small self-hosted deployment should make explicit before it enables push delivery.

## Defenses in the repository

- Set `SIGNALWEAVE_API_TOKEN` outside the repository to protect the MCP and webhook HTTP surface. `/healthz` remains public for liveness checks.
- `PUSH_WEBHOOK_TOKEN` can add a separate bearer check for push relays.
- The Superset adapter executes saved chart definitions only; it does not accept arbitrary SQL from an MCP caller.
- Query row and series limits are bounded, dashboard pagination is capped, and chart fetches have timeouts.
- A source timeout, missing selected chart, empty result, or ambiguous numeric result is evidence of insufficient data, never an automatic `ignore`.
- TypeSafe recipients are allowlisted by the monitor card. A typed result cannot invent a destination; actions without an approved recipient are downgraded to `investigate`.
- Stale data escalates only when an approved escalation recipient exists; otherwise it becomes `investigate`.
- Low-confidence `notify` and `ignore` outcomes are downgraded to `investigate`.
- The monitor image runs as a non-root user, and monitor-card writes are atomic to avoid a partially written JSON catalog.

Run the adversarial unit checks with:

```bash
uv run python -m pytest -q
```

## Deployment responsibilities

The repository intentionally does not pretend to be an identity provider or a durable control plane. A production deployment should add:

- TLS and an identity-aware gateway or OIDC integration;
- secret-manager injection and token rotation;
- a durable, reviewed monitor-card store with version history;
- an append-only decision/audit store and idempotent delivery worker;
- dashboards or alerts for source latency, failure rate, `investigate` rate, and recipient corrections;
- a data policy for what evidence may be sent to TypeSafe Jev.

The local JSON catalog and static bearer token are suitable for a contained proof or internal sidecar, not a substitute for those company controls.
