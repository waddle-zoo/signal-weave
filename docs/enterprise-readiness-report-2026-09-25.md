# SignalWeave enterprise readiness and product-value report

**Date:** 2026-09-25
**Branch reviewed:** `feat/decision-feedback-contract`
**Current verdict:** controlled enterprise-pilot candidate; not yet a broad autonomous production platform.

## Executive readout

SignalWeave has a real product thesis and meaningful supporting evidence, but the
claim must stay precise:

> SignalWeave turns a human-authored monitoring goal and existing analytical
> assets into an authorized, bounded evidence bundle, a typed Jev judgment, and
> a caller-owned push decision.

It is not a replacement for Superset, Looker, Hex, dbt, Cube, Glean,
OpenMetadata, Monte Carlo, Airflow, Temporal, or a general-purpose agent. Its
value is in the seam between them: deciding which existing evidence matters for
this goal now, whether the evidence supports action, and what should be pushed
to an existing agent or owner.

The evidence is strongest for:

- applying explicit English decision guidance over heterogeneous evidence;
- suppressing unsupported alerts and routing ambiguous cases to investigation;
- returning source-level provenance and typed outcomes;
- preserving tenant and authorization boundaries in the tested contracts; and
- making a reusable decision primitive available to an external agent or scheduler.

The evidence is not yet sufficient for:

- autonomous production delivery;
- universal retrieval quality across arbitrary enterprise graphs;
- measured Trino or warehouse cost savings;
- production multi-tenant operation; or
- proving that real operators save time or make better decisions.

The right public position is therefore **“open-source technical alpha for
evidence-backed push analytics”**, with a staged path to production shadow mode.

## What was evaluated

The reviewed system has this shape:

```text
Human intent/card
        |
        v
Permission-aware adapter search + graph/lineage expansion
        |
        v
Bounded source and evidence bundle
        |
        v
Jev typed judgments and probabilities
        |
        v
Deterministic freshness, authorization, delivery, and confidence gates
        |
        v
Receipt -> existing agent, scheduler, Slack, incident system, or human
```

The application owns source contracts, calculations, safety gates, receipts,
and routing. Jev supplies narrow semantic judgments; it does not generate the
workflow, execute SQL, enforce permissions, or invent missing business intent.
That division matches TypeSafe's programming model: System One evaluates a
structured state and returns typed answers and probabilities, while application
code combines those answers into behavior. [TypeSafe System One](https://docs.typesafe.ai/concepts/system-one)
and [state](https://docs.typesafe.ai/concepts/state) describe this boundary.

## Evidence ledger

The repository contains several generations of trials. They should not be
collapsed into one headline number.

| Evidence | Result | What it supports | Important limitation |
| --- | ---: | --- | --- |
| Full regression suite | **191 passed, 1 skipped** | The current contracts, adapters, auth boundary, onboarding packet, gates, receipts, and evaluation harness remain internally consistent. | Unit tests are not production evidence. |
| Live Jev enterprise matrix | **130/144 exact outcomes**, 0 unsafe automatic actions, complete workflow/card/provenance/source-selection contracts | Jev can apply explicit card rules across 3 synthetic companies, 22 personas, and 1,664 heterogeneous resources. | The runner supplied hidden source refs, so this is not a discovery benchmark. The 14 misses were conservative `notify -> investigate` routes. |
| Live Jev large-scale matrix | **144/144 exact**, 0 wrong actions, 288 requests, median 856 ms, p95 1,111 ms | Stable execution across 72 generated cases, 12 domains, and six decision classes. | Historical pre-refactor baseline; synthetic labels and repeated fixture structure. |
| Northstar corporation Jev run | **48/48 exact**, 0 unsafe actions, 48/48 provenance-complete, 36/48 fully automatable | A multi-role, multi-domain organization-shaped workflow can run through the same MCP path. | 40 role agents, cards, labels, and handoffs are simulated; delivery was disabled. |
| Live source discovery | **48/48 exact top-2**, 48/48 top-10 coverage, 0 wrong-tenant returns | Adapter-owned bounded search plus Jev ranking can select labeled sources in the tested catalog. | 48 synthetic cases; not a real enterprise catalog or identity provider. |
| Live evidence-bundle retrieval | **48/48 related sources**, 48/48 anchors preserved, 0 wrong-tenant sources | Human anchors and bounded related-source expansion can feed a multi-source decision. | The graph/context obligations are fixture-defined; this does not prove universal graph completeness. |
| Live metric planning | **24/24 metric, dimension, and grain selections**; all SQL bounded and `SELECT`-only | Natural-language metric intent can select from approved definitions without asking Jev to generate executable SQL. | Small held-out catalog; no proof over a real 100k-table lake. |
| Current onboarding matrix | **30/30 safe**, required-candidate recall 1.00, 0 tenant leaks, 29/30 exact recommended sets | The onboarding contract preserves authorization boundaries and does not silently approve unsafe or under-specified cards. | Fixture-backed; one definition ambiguity is intentionally surfaced for human review. |
| Northstar real-row replay | Current artifact: **5/6 Jev**, fixed comparator 6/6; older committed narrative reports 4/6 | Jev can process real local Northstar row distributions and fail closed on unavailable data. | Six counterfactual cases, not independent operator labels. The fixed comparator winning is evidence that simple rules should remain challengers. |
| Paired agent replay | **89.3% vs 46.4% exact** for SignalWeave-mediated vs agent-only; unsafe actions **5.4% vs 53.6%** | In this synthetic Northstar workload, Jev preflight materially improved the same agent's decision quality and reduced unsupported actions. | 55 complete pairs in the pooled denominator, synthetic fixture-clustered observations, not a production reliability estimate. |
| Timing-corrected paired replay | **85.7% vs 42.9% exact**; median 6.89s vs 7.38s; p95 9.82s vs 10.14s | The treatment did not add a large end-to-end latency penalty in this run. | One 28-pair replay; it made more logical diagnostic queries. It does not prove cost savings. |
| 10,000-workflow mass model | **99.31% modeled expensive-query reduction**, 96.37% modeled normalized-cost reduction | Query avoidance, deduplication, and bounded follow-up could be economically important when many cards share expensive work. | A workload model, not 10,000 live workflows, real Trino bills, or a named-agent benchmark. |

### Reading the evidence correctly

The strongest value signal is not “Jev is 700 ms.” The stronger signal is that a
typed preflight can prevent an agent from turning ambiguous or contradictory
evidence into an unsupported push action while preserving the evidence needed to
investigate. The paired trial showed that effect in the tested fixture.

The weakest claim in the current narrative is cost reduction. The 10,000-case
report models query reuse and avoidance. The paired replay actually made more
logical diagnostic requests in the treatment arm, even though cache reuse kept
physical executions close. Until real query bytes, CPU, queue time, cache hits,
and invoices are captured, cost savings must remain a hypothesis.

## Does this create real value?

Yes, for a specific class of company and workflow.

### The valuable user problem

An analytics or operations team already has dashboards, saved queries, notebook
runs, data-quality checks, pipeline status, ownership metadata, and a Slack or
incident path. The recurring burden is not producing another chart. It is:

1. opening several artifacts;
2. deciding whether a movement is meaningful or expected;
3. checking corroborating or contradictory signals;
4. finding the responsible owner; and
5. writing a useful message with enough evidence for somebody else to act.

Native BI alerting solves a simpler problem. Superset alerts fire when a SQL
condition is met and reports send scheduled dashboard or chart output; Looker
alerts are configured on dashboard tiles with threshold conditions; Hex scheduled
runs can execute published apps and send conditional notifications. These are
valuable primitives, but they do not by themselves express a cross-dashboard,
cross-source operating story. [Superset alerts](https://superset.apache.org/admin-docs/configuration/alerts-reports/),
[Looker alerts](https://docs.cloud.google.com/looker/docs/alerts-overview), and
[Hex scheduled runs](https://learn.hex.tech/docs/share-insights/scheduled-runs)
document those native boundaries.

SignalWeave is valuable when the rule is closer to:

> “Tell the growth owner only if conversion moved materially, the supporting
> activation signal corroborates it, the data is fresh, and the movement is not
> explained by the current campaign mix. If the sources disagree, send an
> investigation packet instead.”

That is too nuanced for a single tile threshold, but small enough for a human to
write as a card and for Jev to apply over bounded evidence.

### Who benefits first

| Persona | Current pain | SignalWeave value | Proof still needed |
| --- | --- | --- | --- |
| Analytics/BI lead | Owns many dashboards and receives noisy questions or alerts. | Writes one free-form monitoring card over approved artifacts and gets a reusable push decision. | Real onboarding completion time and card-revision rate. |
| RevOps, finance, product, or operations lead | Checks several dashboards and asks “is this important, why, and who owns it?” | Receives a compact evidence bundle with the relevant movement, corroboration, trust status, and route. | Human useful-alert precision and time saved. |
| Agent engineer | Builds retrieval, tool loops, alert suppression, and routing repeatedly. | Calls one MCP surface and receives typed context, outcome, confidence, provenance, and abstention. | Integration with a real agent and measurement of avoided tool/query loops. |
| Data platform team | Has metadata, lineage, definitions, and ownership trapped in separate systems. | Exposes those systems through source contracts without replacing the catalog or scheduler. | Real adapters, identity propagation, and permission audits. |
| Open-source contributor | Wants an interoperable layer rather than another closed agent product. | Can add a read-only adapter or evaluation case without adopting a new BI or workflow stack. | A smaller, clearer public API and at least one external adopter. |

### When it is not valuable

SignalWeave should not be inserted where a deterministic rule already solves the
problem. The Northstar real-row replay is a useful warning: the fixed comparator
was perfect on that six-case rubric while Jev had one false notification in the
current artifact. For a single metric, fixed threshold, one owner, and one
source, native BI alerts or SQL are cheaper and easier.

The product earns its complexity only when at least two of these are true:

- the decision needs multiple artifacts or source types;
- the meaning depends on human business context, not just a threshold;
- source freshness, quality, or definition conflicts matter;
- the owner depends on an ownership or relationship graph; or
- many cards can reuse the same expensive evidence work.

## Competitive and adjacent landscape

The research does not show an empty market. It shows a narrow integration seam.

| System category | Already good at | SignalWeave must not pretend to replace | Remaining seam |
| --- | --- | --- | --- |
| Superset, Looker, Hex, other BI tools | Chart/dashboard execution, native permissions, schedules, tile-level alerts, report delivery | BI and dashboard infrastructure | Cross-artifact interpretation of a human operating goal. |
| dbt Semantic Layer, Cube | Governed metric definitions, joins, dimensions, and query generation | Metric governance and semantic modeling | Selecting which governed assets matter for an open-ended monitoring goal and combining them with non-metric evidence. |
| Glean | Permission-aware enterprise search, people/context graph, agent/MCP access | Enterprise search and broad knowledge indexing | A small, inspectable operational decision contract over analytical evidence. |
| OpenMetadata | Open metadata catalog, lineage, glossary, quality context, MCP tools, and metadata actions | The catalog and knowledge graph | Using catalog/graph context to construct a bounded decision bundle without owning the graph. |
| Monte Carlo and data observability tools | Data health monitoring, lineage, incidents, and root-cause hints | Data observability and pipeline health | Arbitrary business-goal monitoring that combines healthy data with product, finance, growth, or operational evidence. |
| Airflow, Dagster, Temporal | Scheduling and durable workflow execution | Workflow runtime and retries | The semantic decision inside a scheduled workflow. |
| General LLM/RAG agents | Open-ended search, explanation, and flexible tool use | General reasoning or agent ownership | Deterministic, typed, cheaper preflight and fail-closed routing over a human-defined state. |

This is why “RAG is dead” is the wrong framing. Retrieval is still necessary;
the hard part is permission-aware, fresh, relationship-aware candidate coverage.
TypeSafe's own reranking guidance separates fast shortlist creation from semantic
reranking and explicitly notes that reranking cannot recover an omitted
candidate. [TypeSafe reranking](https://docs.typesafe.ai/cookbooks/rerank_typesafe)
supports SignalWeave's architecture, but it also defines its limit: SignalWeave
needs adapters or graph providers that can produce a good candidate pool first.

OpenMetadata already exposes metadata search, lineage, semantic search, and
quality tools through MCP; Glean similarly offers permission-aware graph access
and MCP for agents. [OpenMetadata MCP](https://docs.open-metadata.org/v1.12.x/how-to-guides/mcp)
and [Glean MCP](https://docs.glean.com/administration/platform/mcp/about) make it
clear that “give agents enterprise context” is already a real product category.
SignalWeave is only differentiated if it stays focused on the decision seam
after those systems return context.

## Enterprise-readiness scorecard

These statuses mean “how far the repository has proved the contract,” not a
vendor certification or a guarantee for arbitrary deployments.

| Capability | Status | Assessment |
| --- | --- | --- |
| Jev-backed typed judgment | **Strong alpha** | Live runs show fast, structured decisions over explicit card state, with probabilities, provenance, and conservative fallback. |
| Cross-source evidence composition | **Strong alpha** | Superset, SQL, Airflow, table, and synthetic Looker/Hex-shaped resources are exercised. |
| Bounded retrieval and related expansion | **Promising, not production-proven** | 48-task live discovery and 100k-resource virtual omission proof passed, but connector indexes and graph completeness are synthetic. |
| Card onboarding | **Controlled-pilot ready** | Free-form cards, one-call onboarding, explicit anchors, review questions, bounded candidate review, and stale-certification gates exist. No first-class user UI or real operator onboarding study exists. |
| Workflow certification | **Good local contract** | Owner labels remain outside Jev; card version, context version, and receipts are recorded. Real labels and time-split replay are missing. |
| Tenant and source authorization | **OIDC contract implemented; staging proof pending** | Signed JWT validation, request-scoped principal propagation, tenant filtering, and fail-closed source resolution are tested. A customer IdP, gateway, and real connector credentials still need replay. |
| Data freshness and source failure | **Strong local safety** | Stale, unavailable, empty, oversized, or unauthorized evidence does not become an `ignore` or unsupported action. |
| Persistence and idempotency | **Single-deployment alpha** | SQLite restart and idempotency tests pass. Shared multi-replica transactional storage and delivery claims are not delivered. |
| Delivery and operations | **Not production-proven** | Delivery is caller-owned and disabled in trials. Retries, dead letters, recipient authorization, and sink reliability need a real integration. |
| Cost and latency | **Jev promising; workflow economics unproven** | Jev is roughly sub-second in the measured fixtures. Query avoidance and reuse remain modeled, and the paired replay did not prove cost savings. |
| Feedback loop | **Contract exists** | Feedback is append-only, receipt-linked, tenant-scoped, and does not silently mutate policy. A real operator-label loop has not run. |
| General enterprise readiness | **No-go for autonomous production** | Ready for controlled shadow deployments, not for broad autonomous delivery. |

## The gaps that actually block enterprise adoption

### P0 — real identity and connector boundary

The repository now includes a signed OIDC JWT resource-server path with explicit
tenant and subject claims, scope enforcement through MCP's native middleware,
JWKS caching, and fail-closed principal derivation. A real deployment must still
provide the issuer or approved gateway, adapter-enforced authorization, and a
staging replay with colliding resource names across tenants. MCP's current
ecosystem is actively hardening enterprise authorization, which reinforces that
this is not a detail to defer. [MCP 2026 authorization changes](https://blog.modelcontextprotocol.io/posts/2026-07-28/)

SignalWeave should define and test the contract, not become an identity provider.

### P0 — real shadow labels and business outcomes

The synthetic evaluator knows the expected label by construction. A real team
must label whether a result was useful, noisy, late, incomplete, or unsafe; what
route was correct; and what action actually followed. The existing append-only
feedback contract is the right foundation, but no real operator history has
closed this loop.

This is the central proof gap. Without it, the project demonstrates that the
system behaves correctly according to its fixture, not that it creates value for
people.

### P0 — shared production state and delivery

The current JSON/SQLite paths are appropriate for local evaluation and a single
deployment. Enterprise use needs shared transactional storage, card/version
claims, receipt retention, replay semantics, delivery idempotency, retries,
dead-letter handling, and destination authorization. The caller-owned boundary
is correct, but an integration package or reference implementation is needed to
make the platform usable.

### P1 — retrieval completeness and graph freshness

The latest retrieval work protects the most obvious omission failure: a valid
human anchor can be omitted from a bounded search page and is now revalidated
through authorization. That is necessary but not sufficient. A production graph
provider must expose:

- tenant and principal scope;
- freshness timestamp and version;
- completeness or truncation status;
- lineage/relationship provenance;
- source health and ownership; and
- explicit obligations such as primary, corroborating, diagnostic, quality, or
  owner evidence.

Jev cannot infer a missing business obligation from an omitted graph edge. The
card or trusted graph must say what kinds of context are required.

### P1 — onboarding quality and time-to-value

The current free-form card shape is directionally right. The minimal useful
prompt is still:

- what to watch;
- why it matters;
- things to look out for;
- questions to answer; and
- delivery methods based on outcomes.

The product currently proves that incomplete cards can be held for review. It
does not prove that a non-technical owner can create a good card in ten minutes,
understand the selected sources, correct a missing context obligation, and reach
a trusted shadow run without an engineer. A lightweight bring-your-own UI or
agent is fine, but the MCP contract needs a polished authoring walkthrough and
machine-readable review questions.

### P1 — distinguish simple rules from semantic workflows

The engine should support a deterministic challenger for every card family:

- if a threshold or SQL rule is sufficient, use it;
- if several sources and human semantics matter, use Jev;
- if context is insufficient or risk is high, investigate or abstain.

This is both an adoption benefit and a credibility test. SignalWeave should never
claim that Jev is better than code when code is enough.

### P1 — real economics and query suppression

The current mass model assumes compatible query groups and assigns normalized
cost units. The paired trial showed that semantic preflight can improve quality
without making end-to-end latency worse, but it also increased logical diagnostic
queries. The next test must measure:

- query fingerprints and reuse;
- cache hit/miss rate;
- bytes scanned and CPU seconds;
- queue time;
- Jev requests and tokens;
- agent tool calls;
- source fetch time; and
- human usefulness per delivered result.

Only then can the project claim that it makes expensive analytics faster or
cheaper. The credible benefit may be fewer expensive investigations, not merely
a faster model call.

### P1 — drift and recertification

Cards, dashboards, metric definitions, owners, permissions, and graph edges all
change. The branch now blocks stale workflow certifications when the card
version changes. Enterprise operation also needs source-schema drift detection,
ownership changes, removed dashboards, changed metric grain, graph-version
replay, and automatic downgrade to shadow when a certification no longer covers
the current state.

## Recommended product boundary

The most defensible open-source positioning is:

> **SignalWeave is a push-analytics decision layer for existing BI and data
> assets. Write what matters in plain English; it retrieves the authorized
> evidence, applies a typed Jev judgment, and gives your agent or scheduler a
> compact, inspectable result.**

The first use case should be a recurring “what changed and does it matter?”
workflow over multiple dashboards or analytical artifacts. Superset remains the
best demonstrator because it is locally runnable, but the contract should keep
the source-neutral shape.

The project should not promise:

- “automate all BI”;
- “replace RAG”;
- “Jev finds the truth in the graph”;
- “zero human input”; or
- “99% cost savings” based on the modeled workload.

## Promotion plan

### Gate 1 — one real team, shadow only

Use one real team and one source pair, preferably the existing Superset plus
warehouse path. Start with 20–50 owner-reviewed cards. Delivery stays disabled.
Capture card version, source refs, evidence shown, Jev probabilities, route,
latency, query telemetry, and operator feedback.

### Gate 2 — time-split replay

Freeze a historical period, label it with the domain owners, and hold out a later
period. Compare SignalWeave with the team's current threshold/SQL process and a
same-input agent baseline. Report exact outcome, useful-alert precision, missed
action rate, investigation rate, evidence recall, wrong-recipient rate, query
work, and cost.

### Gate 3 — low-risk delivery

Enable only read-only notifications for a single owner group. Keep all state
changes and operational actions outside SignalWeave. Require zero authorization
leaks, zero unsupported automatic routes, complete evidence for every delivery,
and an agreed useful-alert rate over a meaningful time window.

### Gate 4 — connector expansion

Add one new connector family, such as Looker or Hex, and one cross-system case.
Do not generalize from synthetic adapter shapes. Repeat the identity, freshness,
retrieval, and shadow-label gates.

## Final assessment

SignalWeave is no longer just a demo. The repo contains a credible, tested
technical core and multiple live Jev demonstrations showing that typed
decision-making over human-defined context can outperform an unconstrained agent
on decision quality and unsafe-action rate in the tested synthetic workflows.

It is also not yet an enterprise product in the ordinary sense. The missing
pieces are not another agent framework or more dashboard-specific logic. They
are the operational proof layer: real identity, real connectors, real shared
state, real delivery reliability, real operator labels, and measured business
outcomes.

The thesis is worth continuing if the team is willing to stay disciplined about
that boundary. The next milestone should be **one real shadow deployment that
proves fewer noisy checks and better evidence-backed escalation for a real team**.
If that trial does not show operator time saved or decision quality improved
against the team's current process, the broader enterprise promise is not yet
earned.

## Research references

- [TypeSafe System One](https://docs.typesafe.ai/concepts/system-one), [state](https://docs.typesafe.ai/concepts/state), [confidence](https://docs.typesafe.ai/confidence), and [reranking](https://docs.typesafe.ai/cookbooks/rerank_typesafe)
- [Superset alerts and reports](https://superset.apache.org/admin-docs/configuration/alerts-reports/)
- [Looker alerts overview](https://docs.cloud.google.com/looker/docs/alerts-overview)
- [Hex scheduled runs](https://learn.hex.tech/docs/share-insights/scheduled-runs)
- [dbt Semantic Layer](https://docs.getdbt.com/blog/product-analytics-pipeline-with-dbt-semantic-layer)
- [Glean Knowledge Graph](https://docs.glean.com/security/knowledge-graph) and [Glean MCP](https://docs.glean.com/administration/platform/mcp/about)
- [OpenMetadata MCP](https://docs.open-metadata.org/v1.12.x/how-to-guides/mcp) and [OpenMetadata AI SDK](https://docs.open-metadata.org/v1.12.x/api-reference/sdk/ai-sdk)
- [Monte Carlo data observability](https://docs.getmontecarlo.com/docs/monte-carlo-at-a-glance) and [RCA insights](https://docs.getmontecarlo.com/docs/rca-detections)
- [MCP 2026-07-28 specification update](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework) and [Playbook](https://www.nist.gov/itl/ai-risk-management-framework/nist-ai-rmf-playbook)

## Repository evidence

- [`docs/enterprise-closure.md`](enterprise-closure.md)
- [`docs/enterprise-gap-analysis.md`](enterprise-gap-analysis.md)
- [`docs/paired-agent-trial-results.md`](paired-agent-trial-results.md)
- [`docs/everything-tracking-llm-benchmark.md`](everything-tracking-llm-benchmark.md)
- [`docs/northstar-shadow-trial.md`](northstar-shadow-trial.md)
- [`docs/northstar-corporation-trial.md`](northstar-corporation-trial.md)
- [`docs/mass-analytical-trial.md`](mass-analytical-trial.md)
- [`docs/bootstrap-and-certification.md`](bootstrap-and-certification.md)
