# Enterprise onboarding exploration

Status: exploratory branch only (`explore/enterprise-onboarding`). Nothing in
this document is part of the production contract yet.

## Research question

Can an enterprise user start with a plain-language monitoring goal and one or
two optional seed assets, then get a complete, authorized, reviewable insight
card without knowing every dashboard ID, query name, graph schema, or adapter
detail?

This is the adoption problem. Jev is useful only after the right candidate
state has been assembled. The exploratory work therefore measures the seam
between enterprise discovery systems and Jev, not Jev in isolation.

## What the external systems imply

The surrounding products already expose most of the raw material SignalWeave
needs:

- OpenMetadata exposes search, semantic search, entity details, lineage,
  ownership, glossary, and data-quality context through its SDK and MCP tools.
  Its MCP endpoint is authenticated with a bot JWT, so discovery has to retain
  the identity and trust boundary rather than treat the catalog as anonymous
  text. See the [OpenMetadata AI SDK](https://docs.open-metadata.org/v1.12.x/api-reference/sdk/ai-sdk)
  and [MCP connection guide](https://docs.open-metadata.org/v1.12.x/how-to-guides/mcp/connect).
- Glean's knowledge graph combines content, people, activity, and permissions;
  its search documentation makes access control part of result visibility, not
  a later filtering step. See [Glean's knowledge graph overview](https://docs.glean.com/security/knowledge-graph)
  and [search permissions FAQ](https://docs.glean.com/administration/search/faq).
- Looker has separate APIs and native concepts for dashboards, Looks, Explores,
  schedules, alerts, and permissions. An adapter should preserve those native
  identities and execute under the caller's principal rather than flattening
  everything into a generic document. See [Getting started with the Looker
  API](https://cloud.google.com/looker/docs/api-getting-started).
- Hex's API exposes projects, project runs, pagination, access controls, and
  user- or workspace-bound tokens. It also has concurrency and rate limits,
  which means onboarding must describe execution capacity and not only source
  relevance. See the [Hex public API overview](https://learn.hex.tech/docs/api-integrations/api/overview).
- dbt's Semantic Layer and Catalog already own governed metric definitions and
  joins. SignalWeave should use those definitions as candidate evidence rather
  than recreate a semantic layer. See [dbt's Developer Hub](https://docs.getdbt.com/).

The generalized contract is therefore not “index everything again.” It is:

> Given an intent, a principal, and optional seed assets, retrieve a bounded
> candidate set from the systems that already know the company, expose coverage
> and trust metadata, use Jev to classify the candidates for this goal, and
> return a card draft plus explicit human review blockers.

## Proposed onboarding shape

The first exploratory API should remain MCP/API-shaped and caller-owned. It
does not require SignalWeave to ship a UI.

```text
goal + why + optional seed refs + principal
                    |
                    v
permission-aware discovery across installed adapters
                    |
                    v
candidate set with coverage, lineage, owner, freshness, and trust metadata
                    |
                    v
Jev judgments over bounded candidates
  - relevance to this intent
  - evidence role: primary / corroborates / diagnostic / quality / owner
  - definition or identity match
  - safe-to-suggest vs needs human confirmation
                    |
                    v
review envelope
  - proposed card
  - selected and omitted candidates
  - ambiguity and missing-evidence questions
  - permission/freshness/catalog warnings
                    |
                    v
human approval -> existing scheduler/agent -> evidence receipt
```

The important distinction is that Jev makes narrow judgments over candidates;
it does not retrieve omitted assets, prove catalog completeness, grant access,
execute queries, or choose a delivery destination.

## Candidate tools to test

These are the smallest useful capabilities. They are a test target, not a
commitment to add all of them to the public MCP surface immediately.

| Capability | Input | Output | Owner of the hard part |
| --- | --- | --- | --- |
| `discover_insight_sources` | Goal, optional seeds, adapter, principal, budget | Bounded candidates, cursor, coverage, trust warnings | Adapter/catalog |
| `inspect_insight_source` | Candidate ref, principal | Metadata and bounded observations | Adapter |
| `propose_insight_card` | Goal, why, questions, selected candidates | Draft card and Jev plan | SignalWeave + Jev |
| `review_insight_card` | Draft card and discovery receipt | Human questions, omissions, ambiguity, readiness | SignalWeave |
| `simulate_insight_card` | Approved-or-draft card, snapshot | Delivery-disabled evidence preview | SignalWeave |
| `evaluate_insight_card` | Approved card, scheduler event | Receipt for an existing agent/relay | SignalWeave |

The exploratory branch should first test whether the existing tools can satisfy
these contracts under messy inputs. New production tools should wait until a
failure cannot be expressed by the current result types.

## Generalized scenario matrix

The fixture in
[`evaluations/data/onboarding-scenarios.json`](../evaluations/data/onboarding-scenarios.json)
covers 30 cases across seven fictional tenants, ten domains, and five company shapes. The original
11-case baseline remains useful for comparison; the expanded cases deliberately
stress seedless onboarding, non-BI assets, workflow composition, lifecycle
changes, authorization drift, semantic aliases, quality failures, and very
large paginated catalogs.

The original baseline cases were:

| Case | Shape being tested | Expected onboarding pressure |
| --- | --- | --- |
| Single BI anchor | One dashboard and related charts | Fast happy path without raw IDs in the goal |
| Cross-dashboard executive goal | Growth, finance, and retention dashboards | Related-source expansion and evidence roles |
| BI + query + job | Dashboard, Trino query, and Airflow freshness check | Mixed adapters and different execution semantics |
| Looker semantic ambiguity | Explore, LookML model, and duplicate metric names | Definition disambiguation |
| Hex project run | Notebook/project, cached result, and run status | Published-state and run freshness context |
| Quality-first monitoring | Dashboard plus data-quality/test asset | Quality evidence before business alerting |
| Same-name tenant decoy | Identical assets in two tenants | Zero cross-tenant candidate leakage |
| Sparse catalog | Weak titles but strong lineage/owner metadata | Relationship/context recall over lexical recall |
| Stale or failed source | Relevant asset exists but is stale or unavailable | Review gate instead of silent approval |
| Bounded large catalog | 100,000 resources behind server search | No full materialization and visible incompleteness |

This is deliberately broader than Superset while keeping the first product
boundary concrete: every case is still an analytical monitoring goal that must
produce an inspectable card or abstain.

## Acceptance gates for this exploration

These are gates for a shadow/onboarding trial, not production guarantees:

1. **Candidate recall:** every labeled required asset is present in the bounded
   candidate set, or the result explicitly says coverage is incomplete.
2. **Authorization:** zero wrong-tenant or unauthorized candidates are returned;
   missing principal context fails closed.
3. **Review integrity:** ambiguity, stale/failed sources, missing anchors, and
   truncated catalogs create explicit human questions or warnings.
4. **General shape:** one card can combine artifacts from at least three adapter
   types without a source-specific branch in the core onboarding code.
5. **Human effort:** a reviewer can approve or correct a proposal using labels,
   ownership, lineage, freshness, and source links—not opaque scores alone.
6. **Reproducibility:** every recommendation can be replayed from a discovery
   receipt containing the principal, catalog cursor/version, candidate refs,
   Jev evaluator, and context version.

The first harness reports these gates separately. A blended “accuracy” number
would hide whether a failure came from retrieval, authorization, missing
metadata, Jev ranking, or the approval gate.

## First exploratory run

The branch harness is [onboarding_contract_trial.py](../evaluations/onboarding_contract_trial.py)
and is run with:

```bash
.venv/bin/python evaluations/onboarding_contract_trial.py --format markdown
```

The baseline fixture contains 11 cases. It uses a deterministic Jev-shaped
ranking double so that the run tests the onboarding contract, not live model
accuracy. The expanded 24-case fixture and live replay are documented in
[`enterprise-onboarding-expanded-replay.md`](enterprise-onboarding-expanded-replay.md).

| Measure | Result |
| --- | ---: |
| Full contract passes | 8 / 11 |
| Required-candidate recall | 1.00 mean |
| Exact recommended candidate sets | 10 / 11 |
| Wrong-tenant candidate leaks | 0 |
| Server-search full-catalog materialization | 0 |

The three failures are the important result:

- **Definition conflict:** the current recommendation boundary includes both a
  governed net-revenue definition and a competing legacy definition. The review
  surface notices duplicate identity, but it does not yet express a first-class
  “definition conflict” blocker or role-aware recommendation policy.
- **Stale source:** when the user preselects every suggested source, the current
  review can be `ready_for_approval` even though one source is marked stale. A
  stale/failed source must be a readiness condition, not just metadata in the
  candidate row.
- **Large catalog:** a server-search result correctly exposes `100000` total
  resources and `has_more`, but selecting the returned anchor can still produce
  `ready_for_approval`. The review contract needs to prevent completeness from
  being inferred from one good result.

These results are intentionally not a quality score for Jev. They show that the
current candidate retrieval and tenant filtering can express a useful
generalized shape, while the approval contract is too optimistic around trust,
definition conflicts, and completeness.

The fixture and harness are committed as exploratory evidence only. The next
change should be the smallest contract extension that makes those three
conditions explicit, followed by the same matrix plus adversarial permutations
of missing owners, stale lineage, permission changes, duplicate metric aliases,
and provider rate limits. No production merge should happen until the failures
are either fixed or intentionally downgraded to explicit human review.

## Deeper human and enterprise gap map

The person who wants the workflow and the administrator who must safely run it
have different jobs. A clean onboarding flow has to satisfy both without making
either person learn SignalWeave's internal schema.

### The human journey

| Human moment | What they naturally provide | Hidden work SignalWeave must absorb | Failure if we do not |
| --- | --- | --- | --- |
| Express the goal | “Tell me if activation is off course” | Expand business language into a bounded discovery query | The user must know asset IDs and metric vocabulary |
| Point to a starting place | A dashboard link, saved query, or nothing | Preserve the seed and search related artifacts across systems | The first result is lexical-only or misses the real driver |
| Explain what matters | A few free-form watch-outs and questions | Separate intent from source metadata and execution rules | The card becomes an accidental DSL |
| Resolve meaning | “Revenue” / “active customer” / “healthy” | Surface competing definitions, population, grain, and time windows | A plausible but wrong metric is approved |
| Resolve trust | “Only tell me when it is current” | Check freshness, run state, quality, lineage, and snapshot age | A stale or partial result becomes an alert |
| Approve the workflow | Confirm a short list of suggestions | Ask focused questions with source links and reasons | The human reviews dozens of opaque scores |
| Operate it | Correct a wrong source or recipient | Record a versioned correction without silently changing policy | The same onboarding mistake repeats forever |

The important UX pattern is not “automatically approve a card.” It is “make the
remaining human work small, explicit, and high leverage.” A reviewer should see
three to five questions such as:

```text
1. Choose the governed definition: Net revenue or Net revenue (legacy).
2. Confirm the stale Hex run is allowed to participate.
3. The catalog is paginated; confirm this search scope or add a seed.
```

The prototype readiness assessor is
[`onboarding_readiness.py`](../evaluations/onboarding_readiness.py). It turns
these into typed blockers instead of leaving them as prose warnings.

### Enterprise control-plane gaps

| Control | Current state | Generalized pattern to close it |
| --- | --- | --- |
| Identity | The local service primarily has a deployment bearer token; tenant filtering is typed but principal-level identity is not yet a universal contract. | Carry `principal`, tenant, scopes, and source authorization evidence through discovery, inspection, approval, and evaluation. Re-check authorization at approval and run time. |
| Catalog coverage | Adapters can expose bounded search, but a result can still look complete after returning one good seed. | Make `total_count`, cursor/version, completeness, and omitted-candidate warnings part of readiness—not optional metadata. |
| Meaning | Jev can rank candidates, but ranking alone cannot prove that two similar metric definitions are interchangeable. | Add separate typed judgments for identity match, definition conflict, population, grain, and time semantics. |
| Source health | `source_status` exists, but current onboarding can still be approval-ready when a selected source is stale. | Elevate stale, failed, ambiguous, and unavailable sources to explicit review blockers. |
| Ownership | Catalogs commonly expose owners, but the current proposal does not require a responsible person or team to resolve ambiguity. | Return owner candidates and an explicit “who confirms this?” question; never infer a delivery recipient from Jev text. |
| Delivery | Delivery methods are caller-owned, which preserves scope but leaves a new card without an obvious next step. | Treat missing delivery policy as a visible warning and let the calling agent/scheduler own the final sink. |
| Change lifecycle | Receipts are durable, but discovery provenance and card corrections need a stable snapshot/diff story. | Persist catalog snapshot/version, principal, candidates, judgments, corrections, and card version in a replayable onboarding receipt. |
| Operational limits | Source APIs have pagination, rate limits, and run concurrency limits; a relevance result alone does not imply it can run safely. | Let adapters publish fetch/query budgets and return a bounded execution plan for the existing scheduler. |
| Feedback | Humans can correct a card, but feedback is not yet a first-class external learning contract. | Record corrections as caller-owned feedback facts; use them as versioned context in future discovery, never as silent policy mutation. |

OpenMetadata's current API/MCP surface demonstrates why SignalWeave should
consume a rich metadata source rather than recreate one: search, semantic
search, entity details, lineage, ownership, glossary, and data-quality tools are
already separate capabilities, with authenticated access. Its documentation
also treats ownership and RBAC as part of discovery and governance
([features](https://docs.open-metadata.org/v1.12.x/features), [AI SDK](https://docs.open-metadata.org/v1.12.x/api-reference/sdk/ai-sdk)).
Glean makes the same point from the enterprise-search side: content, people,
activity, and permissions jointly determine visibility
([knowledge graph](https://docs.glean.com/security/knowledge-graph), [permissions FAQ](https://docs.glean.com/administration/search/faq)).
Looker and Hex likewise expose native asset/run/access concepts that should
remain intact in adapters ([Looker API](https://cloud.google.com/looker/docs/api-getting-started),
[Hex API](https://learn.hex.tech/docs/api-integrations/api/overview)).

For the MCP deployment itself, the same boundary applies: the protocol treats
the host as responsible for authorization and security boundaries, while the
server exposes focused capabilities. A static deployment token is useful for a
contained sidecar, but not a complete enterprise identity contract. See the
[MCP architecture](https://modelcontextprotocol.io/specification/2025-11-25/architecture)
and its [authorization guidance](https://apps.extensions.modelcontextprotocol.io/api/documents/authorization.html).

## Generalized patterns to close the gaps

### 1. Intent packet, not a larger card schema

Keep the user-facing card free-form. Wrap it in an internal onboarding request
with:

```text
intent: what + why + watch-outs + questions
seeds: optional links or known refs
principal: actor, tenant, scopes
constraints: freshness, time window, source types, cost/latency budget
mode: discover | review | simulate
```

The intent packet is a transport envelope, not a new business-language DSL.

### 2. Candidate roles, not one relevance score

Jev should answer separate questions over the same bounded state:

- Is this candidate relevant to the intent?
- What role can it play: primary, corroborating, diagnostic, quality, definition,
  owner, or unrelated?
- Does it agree with or conflict with an already selected definition?
- Is it safe to suggest under this principal and snapshot?

Code should combine those judgments into a proposal. This prevents a high
relevance score from silently turning a legacy metric into the governed metric.

### 3. Readiness envelope before approval

The caller should receive one machine-readable envelope with:

```text
status: blocked | needs_human_review | ready_for_approval
blockers: code, severity, layer, question, refs
candidate_coverage: complete | bounded | unknown
trust: authorized | stale | failed | ambiguous | unknown
selected / recommended / omitted candidates
replay identity: principal + catalog cursor/version + Jev evaluator + context version
```

This is the smallest pattern that turns “looks reasonable” into an inspectable
approval boundary.

### 4. Progressive onboarding

The first request should be cheap and forgiving:

1. Goal only: return likely sources and ask for one seed if confidence is low.
2. Goal plus one seed: return related candidates and focused questions.
3. After approval: inspect sources and simulate with delivery disabled.
4. After a shadow period: enable caller-owned delivery.

The system should not demand a catalog export, graph schema, or full card before
it can show value.

### 5. Correction loop outside the core

An agent or UI can collect feedback such as “use this definition,” “do not use
that chart,” or “send this to Operations.” SignalWeave should accept a
versioned context/feedback snapshot for the next run and show which facts were
used. It should not own the feedback database or rewrite card policy on its
own.

### 6. Execution handoff, not execution ownership

The readiness envelope can include source fetch/query budgets and compatible
parallel groups, but the existing scheduler or workflow runtime should execute
them. This keeps the product useful with Airflow, Temporal, Dagster, or a custom
agent without becoming another orchestrator.

## Hard-test plan

The next trial should expand the 11 scenarios across independent axes rather
than simply add more happy paths:

| Axis | Adversarial permutations |
| --- | --- |
| Intent | vague goal, synonym mismatch, contradictory question, no seed |
| Catalog | 100k resources, pagination, stale index, missing lineage, duplicate native IDs |
| Meaning | competing definitions, different grains, different populations, legacy aliases |
| Trust | stale, failed, partial, delayed, quality-test failure, source disappears after discovery |
| Authorization | wrong tenant, principal scope change, revoked access, service-account fallback |
| Human review | accepts recommendation, rejects recommendation, supplies seed, corrects owner, changes delivery |
| Operations | rate limit, query queue, expensive branch, adapter timeout, partial fan-out |
| Lifecycle | card version change, catalog snapshot change, replay, duplicate webhook, source retirement |

The hard gate is not one aggregate accuracy number. For each case we should
report candidate recall, wrong-tenant returns, definition-conflict detection,
trust-block detection, human-question precision, time to approval, correction
count, replay stability, and whether an automatic delivery was suppressed.

The current prototype catches the expected readiness blockers in all 11 cases,
while the existing production review status misses the stale-source and
incomplete-catalog gates. That is promising as a pattern, not proof that the
pattern belongs in the service yet. The live replay is recorded in
[`enterprise-onboarding-live-replay.md`](enterprise-onboarding-live-replay.md):
Jev produced 8/11 exact recommended sets, while the code-owned readiness
pattern caught all expected blockers. The next step is to adversarially mutate
these cases and validate the readiness envelope against operator decisions
before promoting it into `src/`.

## What this branch will not build

- A replacement for Glean, OpenMetadata, dbt, Cube, Temporal, Airflow, or a BI
  product;
- a hosted knowledge graph or universal enterprise ACL;
- autonomous graph writes or feedback learning;
- native Looker/Hex connectors before the adapter contract survives the matrix;
- a large onboarding UI; or
- an enterprise-wide correctness claim from synthetic cases.

## Work sequence

1. Run the generalized contract trial and identify failures by layer.
2. Add only the smallest result/adapter contract needed to make a failure
   explicit and reviewable.
3. Re-run the matrix with adversarial decoys, incomplete catalogs, and mixed
   source types.
4. Add a live Jev replay over the same cases if the API key is available, keeping
   provider failures in the denominator.
5. Only then decide whether a production change belongs on a future merge to
   `main`.
