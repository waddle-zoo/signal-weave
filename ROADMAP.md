# SignalWeave roadmap

This is a working tracker, not a promise or a product catalog. The project stays
focused on one job: turning an approved insight card and existing operational
evidence into a bounded, explainable result that an existing system can act on.

## Current focus

- [x] Jev-only production decision path with no implicit heuristic fallback
- [x] Source-oriented insight-card and adapter contracts
- [x] Superset-backed first-connector demo and integration tests
- [x] MCP tools for cataloging, goal-to-card discovery, free-form drafting, preview, approval, and evaluation
- [x] Webhook surface for push-triggered evaluation
- [x] Code-owned evidence, freshness, delivery-method, and confidence safety gates
- [x] Tenant-aware source catalog contracts and authorized discovery boundaries
- [x] Plain-language metric query cards with typed plans and deterministic SQL compilation
- [x] Bounded Trino execution for compiler-produced read-only queries
- [x] Idempotent push decision receipts and explicit approval identity
- [x] Jev-ranked evidence-bundle expansion that preserves human anchors and adds optional context
- [x] Hybrid metadata/context candidate pools that preserve relationship-linked sources before Jev ranking
- [x] One bounded Jev-selected follow-up investigation stage with typed evidence roles and abstention
- [x] Versioned external context snapshots with provenance through MCP and the engine boundary
- [x] Explicit no-match discovery and fail-closed bounded-investigation abstention
- [x] Stale contract, unverified-context, idempotency-collision, and webhook-boundary gates
- [x] Durable SQLite cards, metric cards, and receipt claims for a single-process deployment
- [x] Partial Superset evidence is visible and fails closed only when the affected source is required
- [x] External-input evaluation and embedding/reasoning comparison harness
- [x] Adversarial review of the public README, examples, security posture, and
      product claims
- [x] Cross-enterprise adversarial retrieval/explanation fixture with live Jev coverage

The current review is recorded in [`docs/adversarial-review.md`](docs/adversarial-review.md);
it supports a **public technical-alpha** posture while keeping the listed
production-control gaps explicit.

## Enterprise readiness: bootstrap and certify every card

The onboarding finish line is not “a card was saved.” It is “a human can see
what context the card will retrieve, replay the workflow against labeled
history, understand the evidence bundle, and approve it for shadow or push
delivery.” The current card-guided 1,000-chart trial showed better retrieval
precision than lexical selection, but final outcome accuracy remains a gap. Do
not treat the system as enterprise-ready until these checks are visible per
card and per source domain.

### Bootstrap a company

- [x] Add a portable `BootstrapManifest` and read-only `BootstrapReport` that
      checks authorized catalog coverage, native bounded search, sample
      inspection, tenant scope, and optional metadata capabilities.
- [x] Expose bootstrap assessment through the MCP boundary without adding a
      SignalWeave-owned UI or changing source permissions.
- [ ] Define an adapter onboarding manifest covering credentials, tenant scope,
      native permissions, catalog search, inspection, freshness, lineage, and
      query-cost telemetry.
- [ ] Add a guided bootstrap flow that imports catalog metadata and graph
      relationships, shows coverage and permission warnings, and helps a human
      create the first cards without requiring a new SignalWeave UI product.
- [ ] Add a card context-completeness review that checks purpose, decision
      guidance, required evidence, expected/contradictory states, delivery
      routes, owners, and freshness requirements.
- [ ] Show the candidate set and selected evidence before activation, including
      why each source was retrieved and which relevant candidates were omitted.
- [ ] Define explicit no-candidate, insufficient-data, and stale-context
      behavior so an empty retrieval cannot become a misleading alert.

### Evaluate cards and workflows

- [x] Add reusable `CardEvaluationCase`, `CardWorkflowEvaluator`, and a
      per-card/workflow promotion report with blocked/shadow/approved states.
- [x] Measure outcome accuracy, delivery exactness, evidence recall, retrieval
      precision/recall, unsafe-action rate, runtime failures, and latency while
      keeping owner labels outside Jev state.
- [x] Add a retrieval-quality evaluator that separates adapter candidate recall
      from Jev recommended-set precision/recall.
- [x] Add a reusable card-evaluation fixture format for owner labels, source
      snapshots, graph/context versions, expected evidence, expected outcome,
      and allowed delivery methods.
- [x] Support historical replay with time-split holdouts in the evaluator and
      generalized Jev trial; customer-owned holdouts remain a deployment gate.
- [ ] Support live shadow mode that records what would have been delivered
      without sending it to production destinations.
- [ ] Measure retrieval candidate recall/precision, evidence recall, decision
      exactness, useful-alert precision, missed-action rate, investigate rate,
      unsafe-action rate, and owner corrections separately.
- [ ] Measure scale economics: candidates considered, sources materialized,
      queries executed, bytes scanned, query time, Jev time, total latency, and
      estimated cost per run.
- [x] Add a generalized adversarial scenario pack for expected movement,
      missing/stale sources, no-match retrieval, multi-source evidence,
      tenant boundaries, and native large-catalog search.
- [x] Generate and durably store per-card/workflow and retrieval certification
      reports with configurable promotion thresholds and clear
      shadow/approved/blocked status.
- [ ] Add regression checks so a card, adapter, graph, or Jev-version change
      automatically replays its certification set before promotion.

### Operate and improve safely

- [ ] Version cards, source selections, graph snapshots, prompts/plans, and
      decision receipts together so every result is replayable.
- [ ] Add append-only human feedback linked to the result and context version,
      with agent-proposed changes requiring human approval.
- [ ] Detect source/schema/ownership/lineage drift and invalidate or pause
      affected cards rather than silently weakening retrieval.
- [ ] Add per-card query, payload, latency, concurrency, and Jev-cost budgets
      with visible truncation and fail-closed behavior.
- [ ] Add a company-level readiness report showing which domains, sources, and
      cards are certified, weakly covered, stale, or still relying on lexical
      fallback. The synthetic generalized trial now provides the initial report
      shape; production aggregation remains open.

## Next: prove the narrow wedge

- [x] Publish a small, reproducible labeled benchmark with documented limits and
      an apples-to-apples Jev comparison (see [`docs/evidence-brief.md`](docs/evidence-brief.md))
- [x] Add a second approved read-only source adapter for Trino-shaped data-lake queries
- [x] Document deployment patterns for an existing scheduler, agent, Trino, and
      delivery system without adding orchestration to SignalWeave
- [ ] Add a small operator-facing UI or integrate the authoring protocol with an
      existing company agent
- [ ] Add customer-owned, time-split shadow labels and result traces suitable for
      a production calibration review
- [ ] Measure top-driver acceptance and diagnostic-source recall on a real
      multi-artifact catalog with same-name assets, aliases, lineage, and the
      source's own permission boundary
- [ ] Ship read-only Looker and Hex adapters that map native dashboards,
      queries/projects, runs, and bounded result evidence to the generic contract
- [ ] Add a permission-aware, paginated catalog-search interface so large deployments
      do not load every asset into SignalWeave before Jev ranking
- [ ] Add tenant-qualified resource references and request-scoped identity/ACLs for
      shared multi-tenant service deployments
- [ ] Add aggregate evidence/context payload budgets and per-card Jev cost/latency
      limits
- [ ] Replace the single-file store with a shared transactional store before
      multi-replica production deployment

## Later: context that can improve decisions

- [x] Add a versioned knowledge-context provider boundary for definitions,
      ownership, relationships, precedents, conflicts, and provenance
- [ ] Record human feedback as append-only, provenance-bearing events linked to a
      decision and context version
- [ ] Let agents propose card or graph changes for human approval; never let raw
      feedback silently rewrite policy
- [ ] Add context-aware Jev judgments that can distinguish known explanations from
      genuinely new movement
- [ ] Add calibrated routing metrics for false alerts, missed actions, latency,
      cost, and owner corrections on real labeled history

## Explicitly out of scope

- A replacement for Temporal, Airflow, Dagster, or another durable workflow engine
- A general-purpose agent builder or open-ended agent loop
- A BI, search, Glean-like knowledge-management, or knowledge-graph product
- Arbitrary SQL, arbitrary code execution, or unrestricted source access
- External delivery side effects or a replacement for a company's delivery worker

## Public-release checklist

- [x] A new contributor can install the project and run local checks from a clean
      checkout
- [x] The README makes no claim stronger than the available evidence
- [x] Examples are clearly separated from production code and contain no secrets
- [x] Security boundaries and credential handling are documented
- [x] CI is green on the default branch
- [x] At least one independent reviewer can explain the product boundary and why
      Jev is used
