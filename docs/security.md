# SignalWeave security and operations review

SignalWeave is a read-and-decide layer. It should not become an unreviewed code
execution or notification surface.

The local compose stack is for localhost-only development. It binds published
ports to loopback, uses the demo Superset credentials `admin` / `admin`, and leaves
optional bearer tokens empty. Do not expose it to an untrusted network. Jev
evaluation sends normalized evidence to the configured TypeSafe service, so each
deployment must establish a data policy before using company data.

## Defenses in the repository

- Set `SIGNALWEAVE_API_TOKEN` outside the repository to protect MCP and webhook HTTP traffic; `/healthz` remains public for liveness. The local demo intentionally leaves this blank only because its published ports are loopback-bound.
- `PUSH_WEBHOOK_TOKEN` can add a separate bearer check for push relays.
- Source adapters own authentication and execution. The Superset adapter executes saved chart definitions only; it does not accept arbitrary SQL from an MCP caller.
- Superset row and series limits are bounded, dashboard pagination is capped, and chart fetches have timeouts.
- A required source timeout or missing resource becomes evidence of insufficient data—not an automatic `ignore`. Adapter failure propagation and machine-readable freshness are still release-hardening work; see [`adversarial-review.md`](adversarial-review.md).
- Card delivery methods are allowlisted. Jev cannot invent a destination, and outcomes without a matching configured method are downgraded to `investigate`.
- Stale data escalates only when a configured escalation delivery method exists; otherwise it becomes `investigate`.
- Low-confidence automatic outcomes are downgraded to `investigate`.
- The source registry resolves refs independently, so a mixed card can show which dashboard/query/DAG/table failed.
- `SIGNALWEAVE_TENANT_ID` can restrict discovery and evaluation to resources whose
  typed catalog contract belongs to the configured tenant; missing or foreign
  resources fail closed.
- Trino execution accepts only compiler-produced `SELECT` queries with validated
  identifiers and bounded timestamp parameters. It is not a raw SQL endpoint.
- Push evaluation requires an idempotency key and writes a durable decision
  receipt with card version, actor, outcome, and delivery state. Replays return
  the existing receipt. The default SQLite store enforces the claim atomically;
  its single-file scope is suitable for one service process or a shared mounted
  volume, not a multi-replica deployment without a stronger store.
- Insight cards and metric query cards use the same SQLite persistence boundary by
  default, and the service image runs as a non-root user.

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
- reviewed card storage with version history and source permissions;
- an append-only decision/audit store and idempotent delivery worker;
- dashboards/alerts for source latency, failure rate, `investigate` rate, and delivery-method corrections; and
- a data policy for what evidence may be sent to TypeSafe Jev.

The optional JSON catalogs and static bearer token are suitable for a contained
proof or internal sidecar, not a substitute for those company controls. SignalWeave
does not claim OS-level process isolation or provide an identity provider.
