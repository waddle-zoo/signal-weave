# Enterprise closure evidence

> Historical closure snapshot. The current authoritative evidence is in
> [`adversarial-v1-review-2026-09-25.md`](adversarial-v1-review-2026-09-25.md)
> and [`enterprise-readiness-report-2026-09-25.md`](enterprise-readiness-report-2026-09-25.md).
> The current deterministic research rerun is 100/144 exact with zero unsafe
> automatic actions; historical 144/144 or 74-test figures below are retained
> for provenance only.

This page records the current boundary of what SignalWeave has proved locally.
It is intentionally explicit about synthetic evidence versus production proof.

## Verified locally

| Surface | Evidence | Result |
| --- | --- | ---: |
| Python contract suite | `.venv/bin/python -m pytest -q` | 74 passed, 1 skipped |
| Static checks | `ruff check src tests evaluations` | passed |
| Decision matrix | Live Jev, 3 companies, 144 hidden-label tasks | 130/144 exact |
| Decision safety | Same Jev run | 0 unsafe automatic actions |
| Contract completeness | Same Jev run | 144/144 workflow, card, provenance, source selection |
| Trace integrity | 4,032-event closure trace | valid hash chain and protocol |
| Source discovery | Live Jev, 48 held-out tasks, 576 pre-filter resources | 48/48 exact top-2; 0 wrong tenant |
| Evidence-bundle retrieval | Live Jev, 48 human-anchor tasks, 576 pre-filter resources | 48/48 expected related sources; 48/48 anchors; 0 wrong tenant |
| Metric planning | Live Jev, 24 held-out metric labels | 24/24 metric, dimension, and grain selections |
| SQL safety | Same metric trial | 24/24 partition-bounded, SELECT-only, semicolon-free |
| Receipt durability | SQLite restart and two-store claim tests | persisted cards and one atomic claim per key |
| Operator feedback contract | MCP receipt-linked labels, tenant scoping, SQLite restart test | append-only labels survive restart; no automatic card/Jev mutation |
| Company context provider | Trusted graph double, related-source expansion, receipt/feedback assertions | graph version reaches Jev bundle, receipt, and feedback; provider failure is unverified |
| Real-row shadow replay | Northstar Superset seed rows, six counterfactual cases | Jev 4/6, 0 false notifications, 0 missed notifications; shadow only |

## Post-fix general-agent trial

The live MCP-only Luna trial is documented in
[`postfix-agent-trial.md`](postfix-agent-trial.md). Across 20 available
enterprise/scenario combinations it achieved 3/20 exact outcome-plus-source
decisions and 4/20 exact source sets. It had 0 wrong-tenant leaks and 0 catalog
leaks, but produced 3 would-be unsafe automatic routes with delivery disabled.
This is evidence that server-side isolation works while autonomous source
onboarding remains the open product problem.

The discovery and metric labels were generated independently of the Jev
requests and were not sent to Jev. The deterministic compiler—not Jev—owns
relations, columns, aggregation syntax, time bounds, and query safety.

## Supported claim

SignalWeave is a bounded technical alpha for turning approved, typed analytical-
artifact metadata and owner-written monitoring intent into inspectable Jev
judgments, deterministic metric plans, and caller-owned push results. Superset
and the typed Trino-shaped data-lake path are the shipped proofs today; the
decision layer is intended to sit across any installed artifact adapters rather
than above one BI vendor.

## Not yet proved

- Accuracy on independent domain-owner labels from a real company.
- Time-split or historical holdout performance.
- Real production deployments and native connectors beyond the current Superset
  and Trino proofs, including Looker and Hex adapters.
- Query cost, freshness, and scale for a real multi-tenant catalog.
- A shared transactional receipt store for multi-replica deployments and an external delivery sink.
- OS-level sandboxing for agents that are supposed to use MCP only.
- Broad superiority over a well-tuned model/RAG system.
- Reliable autonomous onboarding by a general-purpose MCP agent.
- Independent operator labels from a real operating team, including time-split
  replay and agreement on what counts as useful, late, incomplete, or unsafe.
- A production graph provider with real authorization, freshness, completeness,
  and provenance guarantees; the injectable contract is proven locally only.

## Next closure gate

Run SignalWeave in shadow mode for one real team. Export card versions, source
metadata, evidence shown, expected outcome, expected delivery method, human
correction, operator feedback, latency, and eventual operational result. Use
the receipt-linked feedback contract to collect labels without mutating the
running card, split labels by time, measure false automatic actions and
useful-alert rate, and require the same tenant/source/query safety gates before
enabling delivery. Until that gate is passed, public language should say
“technical alpha,” not “enterprise-ready.”

Generated traces and reports remain in ignored `artifacts/` and must never
contain the TypeSafe API key.
