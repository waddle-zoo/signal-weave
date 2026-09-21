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
covers these cases:

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

The fixture contains 11 cases. It uses a deterministic Jev-shaped ranking
double so this run tests the onboarding contract, not live model accuracy.

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
