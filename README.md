<p align="center">
  <img src="assets/signalweave-logo.svg" alt="SignalWeave" width="430">
</p>

<p align="center">
  <strong>Typed decisions for the signals your company already has.</strong><br>
  Turn dashboards, queries, jobs, and source context into evidence-backed results.
</p>

<p align="center">
  <a href="https://github.com/waddle-zoo/signal-weave/actions/workflows/ci.yml"><img src="https://github.com/waddle-zoo/signal-weave/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2ea44f.svg" alt="Apache 2.0 license"></a>
</p>

Most companies already know what they want to watch. The hard part is not making
another dashboard. It is getting an agent to understand a set of dashboards,
charts, notebooks, queries, and operational signals well enough to check them,
spot what matters, and run the right bounded workflow without a person opening
everything every morning.

SignalWeave is a small open-source MCP and webhook service for that seam. A
person writes a free-form insight card, source adapters return bounded evidence,
[TypeSafe Jev](https://docs.typesafe.ai/introduction) makes narrow typed
judgments, and your existing agent, scheduler, or delivery system decides what
to do next.

<p align="center">
  <img src="assets/decision-flow.svg" alt="SignalWeave turns an insight card and source evidence into Jev judgments, safety gates, and an existing push or agent action" width="900">
</p>

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and a TypeSafe API
key.

```bash
git clone https://github.com/waddle-zoo/signal-weave.git
cd signal-weave
uv sync --extra dev
export TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe
make verify
```

Run the optional localhost Superset demo (the first shipped connector):

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  docker compose up --build
```

Superset is available at <http://localhost:8088>. SignalWeave serves MCP at
<http://localhost:18000/mcp>, health at <http://localhost:18000/healthz>, and
push evaluation at `POST /webhooks/evaluate`. The demo credentials are
`admin` / `admin`; the loopback demo token is `local-dev-token`. Ports are
loopback-only and must not be exposed. Set `SIGNALWEAVE_API_TOKEN` and
`PUSH_WEBHOOK_TOKEN` to real deployment secrets outside local development.

For an already approved card export, the standalone checker can run one
delivery-disabled Jev evaluation against local Superset:

```bash
SUPERSET_URL=http://127.0.0.1:8088 \
SUPERSET_USERNAME=admin SUPERSET_PASSWORD=admin \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python scripts/live_card_check.py \
  --card /absolute/path/to/approved-card.json
```

The checked-in example is intentionally a draft and will be rejected by this
command until a caller completes onboarding and approval. For the real flow,
use the MCP sequence below: `onboard_insight_card` → human review →
`approve_insight_card` → `evaluate_insight_card`. That approval boundary is
part of the product, not a demo shortcut.

## The card

The user-facing contract is intentionally generic:

```json
{
  "title": "Sales pulse",
  "what_to_watch": "Revenue and related dashboard signals.",
  "why_watch": "Help Revenue Operations distinguish expected movement from a business issue.",
  "watch_for": [
    "Revenue changes materially.",
    "A related chart corroborates the movement."
  ],
  "questions": [
    "Is this outside expected seasonal behavior?",
    "Does this warrant a Revenue Operations response?"
  ],
  "follow_up_guidance": "If the evidence is material but inconclusive, inspect the authorized diagnostic sources and re-evaluate this card before delivery.",
  "sources": [
    {
      "key": "sales-dashboard",
      "adapter": "superset",
      "resource": "dashboard:7",
      "label": "Sales dashboard",
      "parameters": {"chart_ids": ["62", "64"]}
    }
  ],
  "delivery_methods": [
    {
      "key": "revenue-operations",
      "outcome": "notify",
      "label": "Revenue Operations",
      "destination": "slack://revenue-operations",
      "instructions": "Notify when the evidence supports a non-urgent response."
    }
  ]
}
```

In plain language:

- `what_to_watch` says what the card is about;
- `why_watch` says which decision it should support;
- `watch_for` optionally names conditions to surface one by one;
- `questions` optionally names questions the evidence should answer; and
- `delivery_methods` maps outcomes to caller-owned destinations.

The result gives you the chosen `outcome`, configured delivery methods,
per-item `watch_results`, per-question `question_results`, every normalized
observation, source evidence, confidence, and provenance. If the card names 100
things to watch, Jev receives all 100 observations; changed rows are only placed
first for client rendering.

## MCP flow

An existing UI or agent can guide onboarding without SignalWeave owning the UI:

```text
onboard_insight_card(what_to_watch, why_watch, watch_for?, questions?, ...)
discover_insight_sources(goal, adapter?, limit?)
propose_insight_card(what_to_watch, why_watch, watch_for?, questions?, ...)
resolve_insight_sources(card_id)
simulate_insight_card(card_id)
approve_insight_card(card_id)
evaluate_insight_card(card_id)
get_decision_receipt(idempotency_key? | receipt_id?)
```

For the fastest path, `onboard_insight_card` is the single-call contract: it
returns a Jev-ranked bounded catalog, a typed execution plan, a persisted draft,
review blockers, setup questions, and the next action for the caller-owned UI or
agent. It always returns `approval_required=true` and `delivery_enabled=false`.
Use the lower-level calls when a UI wants to make discovery, source selection,
simulation, or approval separate screens.

Or, when source refs are already known:

```text
draft_insight_card(title, what_to_watch, why_watch, sources, ...)
```

The proposal path uses Jev to rank a bounded source catalog, stores a draft, and
returns setup questions. Preview is delivery-disabled. Approval is explicit.
Proposal-created cards default to `retrieval_mode="expand"`: the selected source
stays a human-approved anchor, while Jev can add a bounded set of authorized,
optional context sources at evaluation time. `resolve_insight_sources` previews
that bundle. Direct drafts default to `fixed`; set `retrieval_mode="expand"` if
the caller wants the same related-source behavior.
After approval, an existing scheduler or alert relay posts:

```json
{"card_id": "card-sales-pulse"}
```

The caller owns scheduling, delivery, retries around the sink, and side effects.
SignalWeave records a durable `shadow` receipt with delivery disabled, and
replays completed results for the same evaluation idempotency key. A caller can
recover the full result later with `get_decision_receipt`, using either the
scheduler key or the returned receipt id.

The narrow shadow-pilot contract and its proof commands are documented in
[`docs/shadow-pilot-contract.md`](docs/shadow-pilot-contract.md).

Cards can also opt into a caller-owned multi-step loop with
`follow_up_guidance`. The result includes a typed `workflow` handoff such as
`retrieve_evidence`, `repair_source`, `deliver`, or `suppress`; a legacy
investigate card with a configured route remains a terminal `deliver` handoff.
The agent runs its own tools and submits a versioned context snapshot back to
the same card.
SignalWeave never invents destinations or executes side effects. See
[`docs/multi-step-workflows.md`](docs/multi-step-workflows.md) and the live
Northstar trial in `evaluations/northstar_multistep_trial.py`.

Cards created through the proposal path also default to one bounded investigation
stage. Jev first decides whether the initial evidence needs more context, then
scores a small set of authorized read-only candidates. SignalWeave fetches only
the selected candidates and runs the final judgment over the combined evidence.
The result includes the selected sources, omitted candidates, context version,
typed evidence roles (`driver`, `corroborates`, `contradicts`, `quality`, or
`unknown`), and an explicit abstention warning when no follow-up is justified.
Set `investigation_mode="none"` for a fixed-evidence card.

An existing agent or graph service can provide a versioned context snapshot when
calling `simulate_insight_card` or `evaluate_insight_card`:

```json
{
  "provider": "company-context",
  "version": "graph-2026-09-18T10:00Z",
  "facts": [
    {
      "fact_id": "edge-123",
      "subject_ref": "superset|dashboard:7",
      "relation": "diagnosed_by",
      "object_ref": "superset|dashboard:12",
      "statement": "Checkout conversion is diagnosed by payment failures.",
      "provenance": ["owner:growth", "source:metric-catalog"]
    }
  ]
}
```

Context supplied through MCP is marked `unverified` and is evidence for the run,
not a silent policy update; if non-empty unverified context would support an
automatic `notify` or `escalate`, the result is downgraded to `investigate`. A
server-side `ContextProvider` can supply trusted context from a deployment-owned
system. Cards and graph changes remain caller-owned and reviewable.

## Bootstrap and certify before push

SignalWeave includes a read-only bootstrap check for each installed adapter. A
deployment supplies a real probe goal and the capabilities it requires; the
`assess_bootstrap` MCP tool reports authorized catalog coverage, native bounded
search, sample inspection, tenant scope, and optional freshness/lineage metadata.
It reports a local catalog scan as a review warning instead of presenting it as
large-catalog readiness.

Before activating a card, replay owner-labeled snapshots through the same Jev
engine with `evaluate_card_workflow`. The report keeps labels outside Jev and
measures outcome accuracy, delivery exactness, evidence recall, retrieval
precision/recall, unsafe-action rate, errors, and latency. Its `blocked`,
`shadow`, or `approved` status is a promotion signal, not a claim that Jev is
universally correct.

For onboarding retrieval, `RetrievalQualityEvaluator` reports candidate-pool
recall separately from Jev's recommended-set precision and recall. That makes a
missing catalog relationship, an incorrect Jev ranking, and a downstream card
decision three different failures to fix. The reusable contracts and example
fixture shape are documented in
[`docs/bootstrap-and-certification.md`](docs/bootstrap-and-certification.md).
The full synthetic Jev-only enterprise trial and its adversarial gate are in
[`docs/generalized-readiness-trial.md`](docs/generalized-readiness-trial.md).
The stronger one-team historical-decision replay is documented in
[`docs/northstar-growth-history-trial.md`](docs/northstar-growth-history-trial.md):
on the local Northstar example rows, Jev reduced 25 movement-only pushes to 8
typed routes, with zero unnecessary routes and complete evidence on the 12-case
holdout-style slice after one card-calibration pass. This is simulated company
evidence, not a customer claim.
The longitudinal panel trial extends that proof across eight simulated months,
48 workflows, repeated multi-step investigations, and independent role reviews:
[`docs/northstar-longitudinal-panel-trial.md`](docs/northstar-longitudinal-panel-trial.md).

## Plain-language metric queries

For data-lake questions, use a metric query card over an approved Trino catalog:

```text
propose_metric_query_card(question, why, selected_sources, dimensions?, time_grain?)
compile_metric_query_card(card_id, window_start, window_end)
approve_metric_query_card(card_id, actor?)
```

Jev selects among catalog-owned metric definitions. SignalWeave then compiles a
typed plan into deterministic `SELECT` SQL with approved relations, columns,
aggregations, dimensions, and a required partition/time bound. It never accepts
raw SQL from the MCP caller and never asks Jev to generate executable SQL. The
included Trino adapter can execute only those compiled queries and returns bounded,
normalized observations.

## Why Jev instead of one large prompt?

Embeddings and RAG can retrieve a relevant dashboard, definition, owner, or
document. They do not by themselves provide a stable boundary for deciding when
several signals belong together, when context explains a movement, or when the
evidence is unsafe to act on.

SignalWeave uses Jev as a programmable decision primitive, not an autonomous
agent. Jev selects from a finite capability vocabulary and evaluates the card's
watch items, questions, and outcome conditions with typed probabilities. Code
keeps ownership of baselines, freshness, allowlists, confidence routing, and
side effects. In the bounded investigation path, Jev also scores candidate
evidence for explanatory usefulness; it does not generate a tool call, query, or
destination. Destinations never come from model output.

That combination gives a person natural-language flexibility without turning the
whole source state and action policy into one untestable response. It also means
an existing agent can enrich the state with approved knowledge-graph context or
human feedback later without SignalWeave owning the graph or the agent loop.

## Analytical artifact integrations

The core unit is an analytical artifact set, not a Superset dashboard. An
adapter can expose a BI dashboard or chart, a saved query, a notebook/project,
a data-lake result, a data-quality check, or a workflow status. A single card can
combine artifacts from different systems when that is what the owner's question
requires. Jev ranks and judges the bounded evidence; code owns source execution,
freshness, permissions, and side effects.

The first shipped connector is Apache Superset. Hosted Preset, Hex, and Looker
connectors now use the same adapter contract while the core remains
vendor-neutral. They are read-only by default and keep provider credentials
outside cards and MCP payloads. See [`docs/hosted-connectors.md`](docs/hosted-connectors.md)
and [`docs/preset-integration.md`](docs/preset-integration.md) for the Preset
quickstart and hosted deployment boundary.
See the official [Looker API](https://cloud.google.com/looker/docs/api-getting-started)
and [Hex public API](https://learn.hex.tech/docs/api-integrations/api/overview)
documentation for the source capabilities those adapters map.

SignalWeave does not assume Superset RBAC or impose a universal enterprise ACL.
Each adapter runs under the deployment's approved credentials or identity
gateway and must return only the artifacts that caller is allowed to use. A
source without native per-user permissions should be placed behind an approved
gateway or isolated deployment; that security decision belongs to the source
integration, not to a hidden SignalWeave default.

## Hosted BI with a separate SignalWeave deployment

Customers can connect hosted Preset, Hex, or Looker workspaces to a separate
SignalWeave deployment that they operate today. The repository does not include
a managed SignalWeave endpoint. The connection stores only a tenant-scoped
credential reference; the source secret stays in the deployment's vault. The
connector retrieves bounded metadata or cached results, Jev evaluates the
approved card, and the customer's existing agent, scheduler, and delivery
system owns the next action.

```text
hosted BI workspace -> SignalWeave adapter -> typed evidence -> Jev -> agent
```

The repository includes the provider clients, read-only adapters, explicit
metadata/cached/live data policies, and contract tests using realistic hosted
API responses. Cloud OAuth, KMS-backed secret storage, and managed polling are
deployment work; they are intentionally outside the source adapter. See
[`docs/hosted-connectors.md`](docs/hosted-connectors.md).

For Preset specifically, this direct API connector requires a Preset plan with
API access; Preset currently documents that API as Enterprise-only. Preset's
current MCP documentation also describes its MCP server as an Enterprise
add-on, so customers with that entitlement can connect an agent to Preset's
remote MCP and SignalWeave's MCP as an interim, agent-mediated path. That path
is weaker for unattended push monitoring and is not a universal workaround for
customers without the relevant Preset entitlement.

For the Preset-specific integration proof—varied chart/result shapes, partial
provider failures, token refresh, metadata-only behavior, and fail-closed
response limits—run `make preset-trial` and read
[`docs/preset-integration-trial.md`](docs/preset-integration-trial.md).
For Docker deployments, use
[`docker-compose.preset.secrets.yml`](docker-compose.preset.secrets.yml) as an
override to mount the Preset API-token name and secret as Docker secrets rather
than placing their values in `.env.preset`.
For a customer deployment, run `make preset-bootstrap-check` first; it validates
the connection and one dashboard catalog page without making a Jev call.
Before that provider request, `make preset-config-check` validates the local
Preset/tenant/auth/policy wiring with zero network requests and zero Jev calls;
it does not prove the credential is accepted by Preset.
Then run `make preset-provider-smoke` with one real dashboard/chart ID to verify
the filtered chart-data boundary without requiring or spending a Jev call.
The real-account onboarding/shadow acceptance gate is a two-step flow:
`make preset-live-trial` creates the reviewable draft, then
`make preset-live-trial-approve` performs the explicitly approved,
delivery-disabled shadow run. Both require tenant-scoped credentials and a live
Jev key. Passing the fixture trial is not a substitute for that customer gate.

SignalWeave is not a replacement for Temporal, Airflow, Dagster, a BI tool,
Glean, a knowledge graph, or a general-purpose agent framework. It is the typed
decision layer between those systems.

Use `signalweave serve --transport streamable-http` for HTTP deployments. The
CLI is the supported boundary that installs bearer/OIDC authentication and
requires a trusted tenant/principal; direct `create_mcp()` embedding is for
stdio or test integrations unless the embedding application supplies the same
principal requirement and middleware.

## Evidence and limits

The strongest current proof is a bounded live Jev shadow trial, not a promise of
universal accuracy. Across six synthetic company shapes and 60 messy monitoring
cases, live Jev made 53/60 exact outcome decisions, recalled 100% of required
evidence, and produced 0 unsafe automatic actions; an independent adversarial
review passed. Median Jev latency was 532 ms and p95 was 662 ms. The separate
eight-case live onboarding replay achieved 8/8 required-candidate recall, 8/8
safe review-preserving outcomes, 6/8 exact recommendation sets, and 0 tenant
leaks. See [`docs/live-jev-proof-2026-09-27.md`](docs/live-jev-proof-2026-09-27.md).

The Northstar local Superset proof also completed the production MCP lifecycle:
discovery, free-form onboarding, persisted review, human approval, live Jev
evaluation, and idempotent replay. It normalized 10 charts into 25 observations
and 36 evidence items, then replayed without duplicate provider or Jev calls.
The clarified owner policy passed 6/6 local counterfactual cases with 0 false
or missed notifications.

The repository also contains discovery, metric-plan, evidence-bundle, provider,
and generated-shape trials. They are synthetic regression measurements, not
customer accuracy or production-cost claims. In particular, the modeled query
and cost reductions in the research notes are not measured savings.

The MCP enterprise trial also exposed the limits: malformed client calls and
unscoped catalogs caused source-discovery failures. Keep tenant identity, metric
definition, population, grain, freshness, lineage, and source status in adapter
metadata, and run a domain-owner-labeled, time-split shadow trial before enabling
automated actions.

The default runtime stores cards and receipts in one SQLite file. It is suitable
for a single-process shadow pilot. Multi-replica deployments still need a shared
transactional store, migrations, backups, lease-based recovery, and operational
quotas before they should route production traffic to more than one evaluator.
The repo intentionally does not claim those distributed guarantees.

Operator labels are also durable and retry-safe when the caller supplies a
stable `feedback_id` to `record_decision_feedback`. Labels are linked to the
receipt's card and context versions; revising a card later cannot rewrite what
the operator labeled about an earlier run.

See [`docs/live-jev-proof-2026-09-27.md`](docs/live-jev-proof-2026-09-27.md) and
[`docs/release-readiness-review-2026-09-27.md`](docs/release-readiness-review-2026-09-27.md)
for the measured case, adversarial findings, and release boundary.

To reproduce the scheduled analytical-artifact monitor contract—no-change
suppression, contextual notification, complete evidence, and idempotent
scheduler retry—run `make daily-trial`. The current fixture uses Superset-shaped
artifacts because Superset is the first shipped connector; the engine contract
does not require that shape. It is an integration proof, not a universal
accuracy claim.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — contracts, pipeline, and boundaries
- [`docs/demo.md`](docs/demo.md) — local setup and onboarding walkthrough
- [`docs/enterprise-v1-acceptance.md`](docs/enterprise-v1-acceptance.md) — v1 acceptance gates, deployment modes, and evidence
- [`docs/source-adapters.md`](docs/source-adapters.md) — adapter contract and security boundary
- [`docs/metric-query-cards.md`](docs/metric-query-cards.md) — approved catalogs, Trino plans, and SQL bounds
- [`docs/benchmark.md`](docs/benchmark.md) — comparison methodology
- [`docs/evidence-brief.md`](docs/evidence-brief.md) — measured product case
- [`docs/enterprise-experiment.md`](docs/enterprise-experiment.md) — MCP-only enterprise readiness experiment
- [`docs/enterprise-closure.md`](docs/enterprise-closure.md) — current proof boundary and next gate
- [`docs/enterprise-readiness-report-2026-09-25.md`](docs/enterprise-readiness-report-2026-09-25.md) — high-level product-value, landscape, evidence, and enterprise-readiness assessment
- [`docs/adversarial-v1-review-2026-09-25.md`](docs/adversarial-v1-review-2026-09-25.md) — security, retrieval, packaging, and release verdict for the reviewed branch
- [`docs/adversarial-review.md`](docs/adversarial-review.md) — public-readiness review and explicit gaps
- [`docs/retrieval-explanation.md`](docs/retrieval-explanation.md) — bounded investigation contract and adversarial trial
- [`docs/postfix-agent-trial.md`](docs/postfix-agent-trial.md) — live post-fix Luna agent trial
- [`docs/security.md`](docs/security.md) — credentials and deployment notes
- [`ROADMAP.md`](ROADMAP.md) — future work tracker
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup and pull-request guidance
- [`AGENTS.md`](AGENTS.md) — guidance for coding agents

## License

SignalWeave is available under the [Apache 2.0 license](LICENSE).
