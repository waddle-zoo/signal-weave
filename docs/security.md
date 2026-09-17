# SignalWeave security and operations review

SignalWeave is a read-and-decide layer. It should not become an unreviewed code
execution or notification surface.

## Defenses in the repository

- Set `SIGNALWEAVE_API_TOKEN` outside the repository to protect MCP and webhook HTTP traffic; `/healthz` remains public for liveness.
- `PUSH_WEBHOOK_TOKEN` can add a separate bearer check for push relays.
- Source adapters own authentication and execution. The Superset adapter executes saved chart definitions only; it does not accept arbitrary SQL from an MCP caller.
- Superset row and series limits are bounded, dashboard pagination is capped, and chart fetches have timeouts.
- A required source timeout, missing resource, empty/ambiguous Superset result, or failed adapter becomes evidence of insufficient data—not an automatic `ignore`.
- Workflow recipients are allowlisted. Jev cannot invent a destination, and actions without an approved recipient are downgraded to `investigate`.
- Stale data escalates only when an approved escalation recipient exists; otherwise it becomes `investigate`.
- Low-confidence automatic outcomes are downgraded to `investigate`.
- The source registry resolves refs independently, so a mixed workflow can show which dashboard/query/DAG/table failed.
- The workflow catalog is written atomically, and the monitor image runs as a non-root user.

Run the adversarial unit checks with:

```bash
uv run python -m pytest -q
```

## Source adapter responsibilities

Every future adapter must define a narrow locator grammar and a read-only execution
policy. A SQL adapter should accept reviewed query references, not caller-supplied
SQL. An Airflow adapter should read approved DAG/run status, not execute DAGs. A
table adapter should perform bounded metadata/data-quality checks, not expose a
general database shell.

Adapters should return source errors as `ResourceSnapshot.error`, preserve the
source URL or run ID when possible, and include enough evidence for a human to
understand what was unavailable.

## Deployment responsibilities

The repository intentionally does not pretend to be an identity provider or
durable control plane. A production deployment should add:

- TLS and an identity-aware gateway or OIDC integration;
- secret-manager injection and token rotation;
- reviewed workflow storage with version history and source permissions;
- an append-only decision/audit store and idempotent delivery worker;
- dashboards/alerts for source latency, failure rate, `investigate` rate, and recipient corrections; and
- a data policy for what evidence may be sent to TypeSafe Jev.

The local JSON catalog and static bearer token are suitable for a contained proof
or internal sidecar, not a substitute for those company controls.
