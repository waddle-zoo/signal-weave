# SignalWeave security and operations review

## October 2026 certificate trust update

Native v0.2.0 and earlier bundles include a certifi CA bundle affected by
[GHSA-6q48-6c7w-9gw2](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2).
Do not use those bundles for live credentials. Replace the native installation
with [v0.2.1](https://github.com/waddle-zoo/signal-weave/releases/tag/v0.2.1);
upgrading system Python does
not update a frozen executable's embedded certificates. Local cards and settings
can be preserved during replacement. This is a dependency exposure, not evidence
that a SignalWeave user was intercepted.

The v0.2.1 build requires certifi >=2026.10.19 (locked to 2026.10.23), uses uv
0.13.5, and bootstraps container pip 26.2.2 from the hash published by the
[Python security announcement](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576).
Rebuild existing container images with `docker build --pull --no-cache .`;
reusing an old image or layer does not repair its trust store. Source builders
must also update their own pip/uv using that upstream guidance before fetching
dependencies.

`scripts/check_ca_bundle.py` rejects all four incident roots by DER fingerprint,
including Sectigo/AAA cross-sign trust. Container dependency installation uses
patched pip's certifi-only verification (`--use-deprecated=legacy-certs`), not
the base image's additional system store; TLS verification remains enabled.
CI checks both runtime certifi and pip's vendored bundle. The hash-pinned pip
bootstrap is verified even if an old base image has an affected trust store.
The native build checks both its dependency and the actual packaged CA file,
records the bundle hash in `--build-info`, and requires the files to match.
Container CI checks the installed bundle too. The public-root negative fixture
tests each root in isolation and mixed into a safe bundle. This is a targeted
regression guard, not a substitute for dependency advisory review.

Release verification rejected all 14 published incident chains offline with
the fixed bundle; the retained v0.2.0 bundle accepted 7/14 as a positive control.
Failures were issuer-trust errors, not expiry, and ordinary HTTPS succeeded.
The identical checked bundle is present in all three downloaded public v0.2.1
archives. See the [release evidence](evidence/decisions-semantic-2026-10-25.md#verified-v021-security-rebuild).

Before publishing, review open dependency alerts, run `make verify`, require the
three native platform jobs and container checks to pass, then inspect the
downloaded public archive and complete the installer/setup/replay/uninstall
journey. Check the published release notes too; correct notes separately if
GitHub uses the commit message instead of the annotated tag. Never overwrite old
release assets to repair a dependency.

## Operating model

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
  `/healthz` and the non-secret `/readyz` remain public for container
  orchestration. The CLI refuses unauthenticated
  streamable HTTP unless `SIGNALWEAVE_ALLOW_INSECURE_HTTP=1` is explicitly set
  for an isolated test.
- For a shared deployment, set `SIGNALWEAVE_AUTH_MODE=oidc` and configure
  `SIGNALWEAVE_OIDC_ISSUER_URL`, `SIGNALWEAVE_OIDC_AUDIENCE`, and an explicit
  `SIGNALWEAVE_OIDC_TENANT_CLAIM` (default `tenant_id`). SignalWeave validates
  signed asymmetric JWTs against OIDC discovery/JWKS, issuer, audience, expiry,
  and the configured scope policy, then derives the request principal from the
  verified subject and tenant claim. Missing or invalid tenant claims fail
  closed. JWKS responses are cached and refreshed when a signing key rotates.
  The deployment may set `SIGNALWEAVE_OIDC_REQUIRED_SCOPES` for MCP-level
authorization. `SIGNALWEAVE_ALLOW_INSECURE_OIDC=1` is local-test-only and is
accepted only for loopback OIDC hosts; it cannot enable an external HTTP issuer
or JWKS endpoint.
  Configured and discovered JWKS URLs are also validated for HTTPS and safe URL
  shape before key retrieval; discovery metadata cannot redirect verification to
  an HTTP, credential-bearing, query-bearing, or fragment-bearing endpoint.
- In a static-token sidecar, set `PUSH_WEBHOOK_TOKEN` for the webhook bearer
  check. The webhook fails closed with `503` when it is not configured or when
  the sidecar principal is absent. In OIDC mode, the webhook uses the verified
  OIDC bearer token instead of a shared webhook token and derives the tenant
  from that token; `X-SignalWeave-Actor` is only an attribution label.
- Source adapters own authentication and execution. The Superset adapter executes saved chart definitions only; it does not accept arbitrary SQL from an MCP caller. The same boundary applies to every connector: SignalWeave does not turn a BI, notebook, query, or workflow API into an unrestricted tool surface.
- Hosted Preset, Hex, and Looker connection records require HTTPS endpoint URLs
  and reject inline URL credentials. The local development exception applies to
  the separate unmanaged Superset connector, not hosted connection bootstrap.
- The Preset Docker deployment includes a secrets overlay that injects API-token
  name and secret, the SignalWeave MCP bearer token, and the push-webhook token
  through mounted Docker secrets and clears direct token values inherited from
  `.env.preset`; use that overlay for shared deployments. The runtime rejects a
  direct value and its corresponding `*_FILE` setting being present together.
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
- Each card retains a bounded history of onboarding reviews, so a later
  correction can be compared with the receipt that preceded it; a separate
  external audit store is still required for unlimited retention.
- Context snapshots supplied through MCP are marked `unverified` and are visible
  in result provenance. A deployment-owned `ContextProvider` is the path for
  trusted graph or catalog context.
- If the bounded investigation selector fails, automatic outcomes are downgraded
  to `investigate` rather than silently using incomplete follow-up evidence.
- Trino execution accepts only compiler-produced `SELECT` queries with validated
  identifiers and bounded timestamp parameters. It is not a raw SQL endpoint.
- Push evaluation requires an idempotency key and writes a durable decision
  receipt with card version, actor, outcome, and delivery state. In a scoped
  deployment, the verified principal—not a caller-supplied actor label—owns
  the approval/evaluation audit identity. Replays return the existing receipt.
  The default SQLite store enforces the claim atomically;
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
durable control plane. OIDC resource-server validation is included, but a
production deployment still needs:

- TLS and an organization-owned OIDC issuer or identity-aware gateway;
- secret-manager injection and token rotation;
- reviewed card storage with version history and source permissions;
- an append-only decision/audit store and idempotent delivery worker;
- dashboards/alerts for source latency, failure rate, `investigate` rate, and delivery-method corrections; and
- a data policy for what evidence may be sent to TypeSafe Jev.

The optional JSON catalogs and static bearer token are suitable for a contained
proof or internal sidecar, not a substitute for those company controls. SignalWeave
does not claim OS-level process isolation or provide an identity provider.
