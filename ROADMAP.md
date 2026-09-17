# SignalWeave roadmap

This is a working tracker, not a promise or a product catalog. The project stays
focused on one job: turning approved operational evidence into a bounded,
explainable decision that an existing system can act on.

## Current focus

- [x] Jev-only production decision path with no implicit heuristic fallback
- [x] Source-oriented workflow and adapter contracts
- [x] Superset-backed local demo and integration tests
- [x] MCP tools for cataloging, inspection, drafting, and evaluation
- [x] Webhook surface for push-triggered evaluation
- [x] Code-owned evidence, freshness, recipient, and confidence safety gates
- [x] External-input evaluation and embedding/reasoning comparison harness
- [ ] Adversarial review of the public README, examples, security posture, and
      product claims

The current review is recorded in [`docs/adversarial-review.md`](docs/adversarial-review.md);
it intentionally remains a **not public-ready** verdict until the listed safety
gaps have tests or deployment controls.

## Next: prove the narrow wedge

- [ ] Publish a small, reproducible labeled benchmark with documented limits and
      an apples-to-apples Jev comparison
- [ ] Make workflow authoring easy for a non-technical dashboard owner without
      weakening the explicit source and action boundaries
- [ ] Add durable workflow versioning and decision traces suitable for review
- [ ] Add one second approved read-only source adapter to prove the contract is
      useful beyond a single BI system
- [ ] Document deployment patterns for an existing scheduler, agent, and delivery
      system without adding orchestration to SignalWeave

## Later: context that can improve decisions

- [ ] Add a versioned knowledge-context provider for definitions, ownership,
      relationships, precedents, conflicts, and provenance
- [ ] Record human feedback as append-only, provenance-bearing events linked to a
      decision and context version
- [ ] Let agents propose workflow or graph changes for human approval; never let
      raw feedback silently rewrite policy
- [ ] Add context-aware Jev judgments that can distinguish known explanations from
      genuinely new movement
- [ ] Add calibrated routing metrics for false alerts, missed actions, latency,
      cost, and owner corrections

## Explicitly out of scope

- A replacement for Temporal, Airflow, Dagster, or another durable workflow engine
- A general-purpose agent builder or open-ended agent loop
- A BI, search, Glean-like knowledge-management, or knowledge-graph product
- Arbitrary SQL, arbitrary code execution, or unrestricted source access
- Delivery, retries, idempotency, or side effects owned by SignalWeave

## Public-release checklist

- [ ] A new contributor can install the project and run local checks from a clean
      checkout
- [ ] The README makes no claim stronger than the available evidence
- [ ] Examples are clearly separated from production code and contain no secrets
- [ ] Security boundaries and credential handling are documented
- [ ] CI is green on the default branch
- [ ] At least one independent reviewer can explain the product boundary and why
      Jev is used
