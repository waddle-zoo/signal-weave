# SignalWeave roadmap

This is a working tracker, not a promise or a product catalog. The project stays
focused on one job: turning an approved insight card and existing operational
evidence into a bounded, explainable result that an existing system can act on.

## Current focus

- [x] Jev-only production decision path with no implicit heuristic fallback
- [x] Source-oriented insight-card and adapter contracts
- [x] Superset-backed local demo and integration tests
- [x] MCP tools for cataloging, goal-to-card discovery, free-form drafting, preview, approval, and evaluation
- [x] Webhook surface for push-triggered evaluation
- [x] Code-owned evidence, freshness, delivery-method, and confidence safety gates
- [x] Tenant-aware source catalog contracts and authorized discovery boundaries
- [x] Plain-language metric query cards with typed plans and deterministic SQL compilation
- [x] Bounded Trino execution for compiler-produced read-only queries
- [x] Idempotent push decision receipts and explicit approval identity
- [x] Jev-ranked evidence-bundle expansion that preserves human anchors and adds optional context
- [x] Durable SQLite cards, metric cards, and receipt claims for a single-process deployment
- [x] Partial Superset evidence is visible and fails closed only when the affected source is required
- [x] External-input evaluation and embedding/reasoning comparison harness
- [x] Adversarial review of the public README, examples, security posture, and
      product claims

The current review is recorded in [`docs/adversarial-review.md`](docs/adversarial-review.md);
it supports a **public technical-alpha** posture while keeping the listed
production-control gaps explicit.

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
- [ ] Replace the single-file store with a shared transactional store before
      multi-replica production deployment

## Later: context that can improve decisions

- [ ] Add a versioned knowledge-context provider for definitions, ownership,
      relationships, precedents, conflicts, and provenance
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
