# SignalWeave security and operations review

SignalWeave is a read-and-decide layer. It should not become an unreviewed code
execution or notification surface.

The local compose stack is for localhost-only development. It binds published
ports to loopback and uses the demo Superset credentials `admin` / `admin`.
It supplies the loopback-only token `local-dev-token`; replace it through
environment variables before any shared deployment. Do not expose it to an
untrusted network. Jev
evaluation sends normalized evidence to the configured TypeSafe service, so each
deployment must establish a data policy before using company data.

## Defenses in the repository

- Set `SIGNALWEAVE_API_TOKEN` outside the repository to protect MCP HTTP traffic;
  `/healthz` remains public for liveness. The CLI refuses unauthenticated
  streamable HTTP unless `SIGNALWEAVE_ALLOW_INSECURE_HTTP=1` is explicitly set
  for an isolated test.
- Set `PUSH_WEBHOOK_TOKEN` for the webhook bearer check. The webhook fails closed
  with `503` when it is not configured and uses only the authenticated
  `X-SignalWeave-Actor` header for actor attribution.
- Source adapters own authentication and execution. The Superset adapter executes saved chart definitions only; it does not accept arbitrary SQL from an MCP caller. The same boundary applies to every connector: SignalWeave does not turn a BI, notebook, query, or workflow API into an unrestricted tool surface.
- Source-specific row and series limits are bounded, catalog pagination is capped, and source fetches have timeouts.
- A required source timeout, missing resource, stale contract, or partial result
  becomes visible evidence and cannot silently become an automatic `ignore`.
  Optional investigation-source failures are recorded in the trace and route to
  `investigate` when the follow-up was selected.
- Card delivery methods are allowlisted. Jev cannot invent a destination, and outcomes without a matching configured method are downgraded to `investigate`.
- Stale data escalates only when a configured escalation delivery method exists; otherwise it becomes `investigate`.
- Low-confidence automatic outcomes are downgraded to `investigate`.
- The source registry resolves refs independently, so a mixed card can show which dashboard/query/DAG/table failed.
- `SIGNALWEAVE_TENANT_ID` and `SIGNALWEAVE_PRINCIPAL_ID` configure the default
  sidecar principal used to scope onboarding and evaluation; they must be
  supplied together. A shared MCP gateway may instead pass a trusted
  `principal_resolver` to `create_mcp`; the resolver receives the MCP request
  context and returns a verified `PrincipalContext` for that request. Raw tool
  arguments cannot set identity. Discovery, inspection, approval re-checks,
  bounded investigation, and evaluation are restricted to resources whose
  typed catalog contract belongs to the resolved tenant; missing or foreign
  resources fail closed. This is not a universal RBAC layer: each adapter must
  enforce the source's own credential or identity boundary.
- Follow-up source selection is checked against the already authorized catalog in
  code; Jev cannot cause an opaque or cross-tenant source to be inspected.
- Insight cards created through a scoped request retain the principal tenant and
  onboarding receipt. Card listing, lookup, review, approval, simulation, and
  evaluation reject a card outside the current principal tenant; this is a
  tenant boundary, not a replacement for gateway roles or source RBAC.
- `record_insight_card_correction` stores caller-owned, append-only onboarding
  feedback with card version and principal provenance. It does not mutate
  source selection, thresholds, delivery, or Jev policy by itself.
- Context snapshots supplied through MCP are marked `unverified` and are visible
  in result provenance. A deployment-owned `ContextProvider` is the path for
  trusted graph or catalog context.
- If the bounded investigation selector fails, automatic outcomes are downgraded
  to `investigate` rather than silently using incomplete follow-up evidence.
- Trino execution accepts only compiler-produced `SELECT` queries with validated
  identifiers and bounded timestamp parameters. It is not a raw SQL endpoint.
- Push evaluation requires an idempotency key and writes a durable decision
  receipt with card version, actor, outcome, and delivery state. Replays return
  the existing receipt. The default SQLite store enforces the claim atomically;
  its single-file scope is suitable for one service process or a shared mounted
  volume, not a multi-replica deployment without a stronger store.
- Idempotency replays are bound to the card version, actor, and context snapshot;
  reusing a key for a different request is rejected. The push webhook also
  enforces a bounded request body and rejects malformed JSON.
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
