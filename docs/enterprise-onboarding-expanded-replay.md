# Expanded enterprise onboarding replay

Status: exploratory branch evidence only (`explore/enterprise-onboarding`). The
scenario catalog is synthetic; the Jev comparison used the live TypeSafe API.
Nothing here is a production reliability claim.

## Why the matrix grew

The first 11 cases were useful but biased toward a Northstar-style dashboard
happy path. This replay adds cases where the user has no seed asset, the best
evidence is not a dashboard, metadata is sparse, a source is retired or
revoked, multiple cards form a workflow, and the catalog is too large to scan.

The 24 cases cover nine domains and five company shapes:

| Pressure | Cases |
| --- | --- |
| Seedless and non-Superset onboarding | `saas-single-bi-anchor`, `seedless-executive-pulse`, `tableau-service-health`, `airflow-only-freshness` |
| Cross-source workflow composition | `saas-cross-dashboard-goal`, `retail-bi-query-job`, `support-root-cause`, `multi-card-growth-cluster`, `notebook-query-quality-chain` |
| Meaning and semantic ambiguity | `fintech-definition-ambiguity`, `fiscal-calendar-definition-conflict`, `sparse-lineage-catalog`, `sparse-semantic-alias` |
| Trust and lifecycle | `hex-published-run-freshness`, `logistics-quality-first`, `quality-failure-blocks-alert`, `stale-source-review`, `retired-source`, `stable-no-change` |
| Authorization and catalog scale | `tenant-decoy`, `permission-revoked-after-card-draft`, `no-match-abstention`, `large-bounded-catalog`, `paginated-catalog-resume` |

The full fixtures remain in
[`evaluations/data/onboarding-scenarios.json`](../evaluations/data/onboarding-scenarios.json).
They are data, not production branches or demo logic.

## Results before and after the readiness hardening

The fixture replay uses opaque, deterministic Jev-shaped scores to isolate the
onboarding contract. The live replay changes only the ranking evaluator; hidden
expected labels are not sent to Jev.

| Measure | Before: fixture | Before: live Jev | After: fixture | After: live Jev |
| --- | ---: | ---: | ---: | ---: |
| Scenarios | 24 | 24 | 24 | 24 |
| Current contract passes | 18 / 24 | 16 / 24 | 23 / 24 | 22 / 24 |
| Typed readiness gates satisfied | 24 / 24 | 24 / 24 | 24 / 24 | 24 / 24 |
| Mean required-candidate recall | 1.00 | 1.00 | 1.00 | 1.00 |
| Exact recommended candidate sets | 23 / 24 | 20 / 24 | 23 / 24 | 22 / 24 |
| Wrong-tenant candidate leaks | 0 | 0 | 0 | 0 |

Commands:

```bash
.venv/bin/python evaluations/onboarding_contract_trial.py --format markdown

.venv/bin/python evaluations/onboarding_contract_trial.py \
  --evaluator live \
  --typesafe-key-file /path/to/typesafe-key \
  --format markdown
```

The recall result is conditional: the harness supplies a fixture-backed bounded
candidate page and evaluates ranking over that page. It does not prove that a
real enterprise catalog will return every relevant asset.

The “before” columns are the replay captured before the typed readiness
hardening. The “after” columns include typed blockers in the review response and
a fail-closed approval check. Live Jev is nondeterministic across runs; the
latest replay is the authoritative “after” row, while the earlier row remains
useful as a variability observation.

## What the new cases exposed

1. **Retrieval is not the largest remaining risk.** Across the 24 fixture
   candidates, live Jev retained every labeled required asset in the bounded
   result and leaked no tenant. That is encouraging for a retrieval layer, but
   it is not enough to approve a workflow.

2. **Recommendations are useful suggestions, not scope.** Live Jev produced
   the exact expected recommendation set in 20/24 cases. The misses cluster
   around competing definitions, sparse lineage, and unhealthy sources. The
   card must show candidate roles, reasons, and omissions so an agent or human
   can accept, reject, or downgrade each one.

3. **The original review contract was too optimistic.** It marked stale,
   failed, retired, and paginated cases `ready_for_approval` in several
   permutations. The hardened review now emits typed source-health and
   catalog-completeness blockers and approval re-runs the review before changing
   card state. All known unsafe approval cases are now blocked in the matrix.

4. **Seedless onboarding is viable but not approval-free.** A goal can find a
   useful candidate without a seed. The prototype correctly blocks approval
   until a human chooses an authorized anchor.

5. **The generalized boundary is holding.** The matrix includes Superset-like
   BI assets, Looker, Tableau, Hex, Trino, Airflow, DataHub-style quality
   checks, catalog assets, and multi-source chains without adding adapter-specific
   branches to the core onboarding service.

## Adversarial review

The independent reviewer is
[`evaluations/onboarding_adversarial_review.py`](../evaluations/onboarding_adversarial_review.py).
It does not use the readiness implementation to decide whether the fixture has
coverage. It separately audits:

- correctness: required-candidate recall, recommendation scope, and explicit
  blockers for unsafe approval;
- scope: tenant and authorization isolation plus catalog completeness warnings;
- generalization: schema coverage, adapter/domain/company-shape diversity,
  multi-adapter composition, and absence of vendor- or scenario-specific
  branches in production onboarding.

The fixture and latest live Jev runs both pass all three reviewer dimensions.
The fixture reviewer retains one warning for a competing definition being
recommended as a review candidate; because the scenario also emits a typed
`definition-conflict` blocker, this is not a silent-approval failure.

## Gaps to close next

The remaining implementation slice should stay narrow:

- return role-aware recommendations (`primary`, `corroborates`, `diagnostic`,
  `quality`, `owner`) with a reason and source provenance;
- replace the deployment-scoped principal with request-scoped identity/OAuth
  evidence when the service is used by a shared multi-tenant gateway;
- carry a discovery receipt containing principal, cursor/version, candidate set,
  Jev evaluator, and card version into later runs;
- add time-split, operator-labeled cases rather than inflating synthetic
  scenario count;
- measure review time and correction rate, not only retrieval metrics.

Do not move the readiness prototype into `src/` yet. The matrix shows which
contracts are worth promoting; it does not establish that the current API
shape is the right public surface.
