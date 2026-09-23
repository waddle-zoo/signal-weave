# Enterprise gap analysis

SignalWeave should stay small. It is not a catalog, semantic layer, workflow
engine, BI product, or agent builder. Its useful boundary is narrower:

> Given a human-authored goal over a set of analytical artifacts, retrieve an
> authorized and sufficiently fresh evidence set from existing enterprise
> systems, use Jev to make bounded typed decisions over that evidence, and
> return an inspectable receipt that another system or agent can act on.

The product promise is operational: people should not have to open a series of
dashboards, notebooks, and query results every morning to decide whether
anything important changed. A card names the outcome, the artifacts or search
scope, what to look for, and what should happen for each outcome. SignalWeave
connects those artifacts, evaluates the current evidence, and pushes a bounded
result to the system that already handles delivery or action.

This boundary matters because the adjacent products are already good at the
parts they own:

| Adjacent system | What it already does well | What it does not provide to SignalWeave's caller |
| --- | --- | --- |
| BI and notebook systems (Superset, Looker, Hex, and others) | Each system owns its dashboards, charts, queries, notebooks, runs, and native access model. | A cross-artifact, goal-specific evidence bundle and a typed decision about what matters now. |
| Data catalogs / metadata graphs | Search, ownership, glossary, lineage, quality, and entity relationships. OpenMetadata exposes these both through APIs and MCP tools. | A bounded investigation plan tied to a particular user goal and current observations. |
| Glean-like enterprise search | Permission-aware indexing and relevance over enterprise content, people, and activity. | A deterministic application contract for selecting evidence, abstaining, and routing an operational outcome. |
| dbt Semantic Layer / Cube | Governed metric definitions, joins, dimensions, access policies, and refresh semantics. | The choice of which governed assets matter for an open-ended monitoring or investigation goal. |
| Temporal / Airflow | Durable execution and scheduling. | The semantic retrieval and decision that should happen inside a workflow. |
| Jev | Fast typed judgments, probabilities, and confidence over supplied state. | It cannot retrieve omitted candidates, enforce source permissions, or execute a workflow. |

The research supports two conclusions:

1. “RAG is dead” is too broad. Vector or graph retrieval remains useful, but
   enterprise retrieval has to account for permissions, freshness, lineage,
   multiple data shapes, and global or multi-hop questions. Microsoft’s GraphRAG
   documentation explicitly separates local entity retrieval from global,
   corpus-level search; the enterprise-RAG literature calls out security,
   accuracy, scalability, and integration as distinct problems.
2. Jev is valuable after candidate generation, not as a replacement for it.
   TypeSafe describes Jev as a typed probabilistic decision primitive; its own
   guidance says the model cannot choose an omitted candidate. Therefore the
   hard product problem is the contract between an enterprise catalog/graph and
   Jev: completeness, authorization, freshness, and bounded context.

## Readiness status after the latest proof

The branch now has a production-shaped retrieval path for the highest-risk
omission case: an important artifact can be related to a card without sharing
its words, so an adapter can expose that neighborhood directly to SignalWeave
before Jev ranks it. The path is bounded, tenant-filtered, receipt-visible, and
does not fall back to a full catalog scan.

The focused Northstar trial recovered all six hidden Fulfillment projections
from a 100,000-resource-per-adapter virtual catalog with zero full scans and one
Jev request. That is meaningful progress, but it is not a claim that SignalWeave
can infer every workflow's required bundle. The trial selected one of the six
projections because the fixture declared one context obligation. Distinct
diagnostic, quality, owner, or delivery obligations still need to be declared by
the card or trusted graph and checked independently.

| Readiness area | Status | Evidence or remaining gate |
| --- | --- | --- |
| Bounded catalog search | Implemented | Adapter-owned search, cursor/total metadata, bounded Jev state, 100k virtual-catalog proof. |
| Relationship-aware candidate coverage | Implemented in the branch | Hidden cross-domain candidates recovered 6/6 without a full scan; needs connector replay against real enterprise graph indexes. |
| Authorization isolation | Local contract proven | Tenant filtering and request principal propagation exist; production gate is an OIDC/shared-gateway replay with real adapter credentials. |
| Trusted context | Runtime-injectable contract proven locally | A deployment-owned provider can expand/rank with trusted context; provider/version are recorded on receipts and feedback, while unverified context cannot widen retrieval. A real graph provider still must publish freshness, completeness, and provenance. |
| Workflow bundle completeness | Deliberately bounded | Explicit `requires_*` relationships preserve at least one candidate per obligation; role-level completeness needs human/graph labels, not a guessed global threshold. |
| Cost and latency budgets | Remaining P1 | Candidate, payload, source-fetch, and follow-up budgets need one shared receipt and abstention proof. |
| Outcome quality | Remaining P1 | Needs operator-labeled historical replay or shadow traffic; synthetic Jev labels are not enough. |

## Highest-confidence gaps

### 1. Candidate coverage at enterprise scale — P0

This was the largest omission risk, and the branch now has the smallest useful
fix: an adapter-owned search boundary plus an optional relationship-expansion
boundary:

- adapters may implement server-side, permission-aware search;
- graph- or lineage-aware adapters may expand a bounded neighborhood from
  approved anchors and trusted context endpoints;
- the registry returns `total_count`, `has_more`, a cursor, and warnings;
- the engine records whether Jev saw a complete catalog or a bounded result;
- legacy adapters retain a clearly marked local fallback rather than pretending
  to solve scale.

The focused proof is complete for the omission case: a 100,000-resource-per-
adapter fake environment made one bounded lexical call plus one bounded
relationship call, recovered all six hidden related candidates, and never
materialized the catalog. The remaining gate is connector replay: Superset,
Looker, Hex, Trino/catalog, and company graph integrations must expose the same
contract without SignalWeave knowing their internal schemas.

### 2. Connector authorization is explicit — P0

SignalWeave must not assume that every enterprise uses Superset RBAC or that
every source has the same permission model. The current service can be deployed
safely behind a trusted gateway, and each adapter can enforce its own credential
or principal boundary, but shared deployments still need request-scoped identity
and card/receipt isolation.

The service now accepts a trusted request principal from the deployment boundary
through `principal_resolver` and propagates it through catalog search, source
inspection, approval, bounded investigation, and evaluation. It still does not
invent an identity provider or universal ACL: a shared deployment must verify
the principal at its gateway, and adapters must return only resources visible to
that principal. The remaining proof target is an actual OIDC/shared-gateway
staging replay rather than the local resolver double.

Proof target: two tenants with colliding resource names cannot discover, inspect,
or reuse each other’s cards or receipts, including through bounded investigation.

### 3. Context must be a retrieval contract, not caller-supplied decoration — P1

The current context provider is intentionally small, but an MCP caller can still
pass an unverified snapshot. That is useful for experiments and unsafe as a trust
boundary. The branch now treats that distinction explicitly: trusted snapshots
can seed relationship expansion and Jev ranking; unverified snapshots remain in
the receipt but cannot widen retrieval, create required bundle coverage, or
change the Jev request. A production graph connector should answer a versioned
query with authorization, freshness, completeness, and provenance status;
SignalWeave should consume that result and abstain when required graph context is
unavailable.

SignalWeave should define the interface and receipt, not own a new knowledge
graph. This is the differentiator: making graph facts operationally usable by a
decision layer without turning the project into another catalog.

### 4. Evidence and cost budgets — P1

Jev is fast and inexpensive, but speed does not remove the need for bounded state.
Large cards, catalogs, context graphs, and source payloads can still create slow
or expensive requests and obscure what the decision used. The engine needs
explicit limits for candidate count, evidence count, serialized bytes, source
fetch time, and optional follow-up depth, with visible truncation and abstention.

### 5. Outcome quality needs counterfactual evaluation — P1

Current trials prove routing, selection, provenance, and safety behavior on
synthetic enterprise portfolios. They do not yet prove that an explanation is the
right explanation, that an alert reached the right owner, or that a human would
have taken the recommended action. Those labels must come from real operators or
replayable historical incidents; they cannot be manufactured by the same Jev
workflow being evaluated.

## What not to build

- A replacement for Superset, a data catalog, Glean, dbt, Cube, Temporal, or
  Airflow.
- A universal graph schema or hosted knowledge graph.
- A free-form agent runtime that can execute arbitrary tools.
- A claim that Jev makes a result true because it returned a high probability.

## Sequence

Completed on this branch:

1. Bounded catalog search, relationship expansion, tenant filtering, and the
   100k-artifact omission proof.
2. Request-scoped principal propagation and cross-source isolation tests.
3. Trusted-context gating, an injectable company-owned provider, explicit
   `requires_*` coverage, receipt-linked graph versions, and an unverified-
   context adversarial test.

Remaining enterprise gates:

4. Replay the contract through real OIDC/shared-gateway and connector adapters.
5. Add one shared set of payload, source-fetch, wall-clock, and follow-up
   budgets, with explicit abstention and receipt fields.
6. Add operator-labeled historical replay or shadow traffic to measure whether
   the selected evidence and route would have produced the right business
   outcome.
7. Only then make automatic delivery a production recommendation for a given
   connector and card family.

## Sources

- [TypeSafe: Introducing System One Models and Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- [Jev model reference](https://systemonemodels.org/models/jev/)
- [Superset dashboard API](https://superset.apache.org/developer-docs/api/get-a-list-of-dashboards/)
- [Superset MCP deployment, pagination, and RBAC](https://superset.apache.org/admin-docs/configuration/mcp-server/)
- [Looker API getting started](https://cloud.google.com/looker/docs/api-getting-started)
- [Looker run query API](https://cloud.google.com/looker/docs/reference/looker-api/latest/methods/Query/run_query)
- [Hex public API overview](https://learn.hex.tech/docs/api-integrations/api/overview)
- [Hex public API reference](https://learn.hex.tech/docs/api-integrations/api/reference)
- [Glean knowledge graph and permissions](https://docs.glean.com/security/knowledge-graph)
- [OpenMetadata AI SDK and MCP tools](https://docs.open-metadata.org/v1.12.x/api-reference/sdk/ai-sdk)
- [dbt Developer Hub and Semantic Layer](https://docs.getdbt.com/)
- [Cube data modeling and access policies](https://docs.cube.dev/reference/data-modeling/cube)
- [Microsoft GraphRAG global search](https://github.com/microsoft/graphrag/blob/main/docs/query/global_search.md)
- [From Local to Global: A Graph RAG Approach to Query-Focused Summarization](https://arxiv.org/abs/2404.16130)
- [RAG Does Not Work for Enterprises](https://arxiv.org/abs/2406.04369)
