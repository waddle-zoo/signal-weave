# Expanded enterprise onboarding replay

Status: exploratory branch evidence only (`explore/enterprise-onboarding`). The
scenario catalog is synthetic; the Jev comparison used the live TypeSafe API.
Nothing here is a production reliability claim.

## Why the matrix grew

The first 11 cases were useful but biased toward a Northstar-style dashboard
happy path. This replay adds cases where the user has no seed asset, the best
evidence is not a dashboard, metadata is sparse, a source is retired or
revoked, multiple cards form a workflow, and the catalog is too large to scan.

The expanded matrix contains 30 cases across seven fictional tenants, ten
domains, and five company shapes:

| Pressure | Cases |
| --- | --- |
| Seedless and non-Superset onboarding | `saas-single-bi-anchor`, `seedless-executive-pulse`, `tableau-service-health`, `airflow-only-freshness` |
| Cross-source workflow composition | `saas-cross-dashboard-goal`, `retail-bi-query-job`, `support-root-cause`, `multi-card-growth-cluster`, `notebook-query-quality-chain` |
| Meaning and semantic ambiguity | `fintech-definition-ambiguity`, `fiscal-calendar-definition-conflict`, `sparse-lineage-catalog`, `sparse-semantic-alias` |
| Trust and lifecycle | `hex-published-run-freshness`, `logistics-quality-first`, `quality-failure-blocks-alert`, `stale-source-review`, `retired-source`, `stable-no-change` |
| Authorization and catalog scale | `tenant-decoy`, `permission-revoked-after-card-draft`, `no-match-abstention`, `large-bounded-catalog`, `paginated-catalog-resume` |
| Multi-enterprise transfer | `acme-health-quality-seedless`, `meridian-bank-competing-risk`, `brightline-retail-dashboardless`, `orbit-logistics-revoked`, `cobalt-media-paginated`, `redwood-manufacturing-no-match` |

The full fixtures remain in
[`evaluations/data/onboarding-scenarios.json`](../evaluations/data/onboarding-scenarios.json).
They are data, not production branches or demo logic.

## Results before and after the readiness hardening

The fixture replay uses opaque, deterministic Jev-shaped scores to isolate the
onboarding contract. The live replay changes only the ranking evaluator; hidden
expected labels are not sent to Jev.

| Measure | Original 24: before hardening | Expanded 30: fixture | Expanded 30: live Jev |
| --- | ---: | ---: | ---: |
| Current contract passes | 16 / 24 live | 29 / 30 | 26 / 30 |
| Typed readiness gates satisfied | 24 / 24 | 30 / 30 | 30 / 30 |
| Safe onboarding outcomes | — | 30 / 30 | 30 / 30 |
| Mean required-candidate recall | 1.00 | 1.00 | 1.00 |
| Exact recommended candidate sets | 20 / 24 live | 29 / 30 | 25 / 30 |
| Wrong-tenant candidate leaks | 0 | 0 | 0 |
| Governed role labels preserved | — | 39 / 39 | 39 / 39 |

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

The original result is the live 24-case replay captured before typed readiness
hardening. The expanded rows include typed blockers in the review response, a
fail-closed approval check, and six new tenants. Live Jev is nondeterministic
across runs; the latest replay is the authoritative expanded row, while
recommendation-set misses remain visible for review.

“Safe onboarding outcome” is the product-level gate: required candidates were
retained, authorization was clean, completeness warnings were surfaced, and the
typed readiness status matched the expected human action. “Exact recommended
candidate set” is a stricter research-label metric; a miss can still be safe
when the card is visibly blocked for human review.
Expected blocker labels are minimum safety conditions. A scenario may also emit
an additive review blocker when Jev surfaces a different uncertainty; the replay
records that as safe only when the card remains non-approval-ready.

## What the new cases exposed

1. **Retrieval is not the largest remaining risk.** Across the 30-case
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

6. **Role evidence is now explicit, but not autonomous policy.** Thirty-nine
   fixture-governed source roles across primary, corroborating, diagnostic, and
   quality evidence were preserved in both fixture and live Jev replays with no
   disagreement. Jev also returns a bounded role probability for ungoverned
   candidates. Those probabilities help a client-owned UI or agent explain a
   candidate; they do not authorize selection or replace operator labels.

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
The fixture reviewer retains one warning for a competing definition, while the
live reviewer retains one warning for a raw events candidate in the sparse
lineage case. Both scenarios emit typed review blockers, so neither warning is
a silent-approval failure.

## Gaps to close next

The remaining implementation slice should stay narrow:

- replace the deployment-scoped principal with request-scoped identity/OAuth
  evidence when the service is used by a shared multi-tenant gateway;
- add a stable card-version and correction diff around the persisted discovery
  receipt so operators can audit what changed between onboarding attempts;
- add time-split, operator-labeled role and selection cases rather than
  inflating synthetic scenario count;
- measure review time and correction rate, not only retrieval metrics.

## Promotion checklist

The exploratory contract is ready for a larger shadow trial, not an
autonomous-production claim. Promote it only when each item has evidence:

- [x] 30 synthetic cases across seven tenants, ten domains, and five company
  shapes.
- [x] Fixture and live Jev adversarial reviews pass correctness, scope, and
  generalization with no unsafe approval-ready recommendation.
- [x] Required-candidate recall, tenant isolation, abstention, catalog
  completeness, source health, semantic ambiguity, and principal evidence are
  typed and reproducible.
- [x] Approval re-checks onboarding blockers and fails closed.
- [x] Discovery receipts preserve principal, authorization source, catalog
  page, candidate refs, evaluator, and truncation state, and are persisted on
  the proposed/approved card.
- [x] Candidate reviews preserve governed evidence roles and bounded Jev role
  probabilities without using them as authorization or approval policy.
- [x] A trusted request principal can be injected into MCP and is propagated
  through discovery, inspection, approval review, bounded investigation, and
  evaluation; shared-catalog collision tests pass.
- [ ] Request-scoped identity/OAuth is verified through a shared gateway.
- [ ] Role-aware candidate judgments are validated against operator labels.
- [ ] Time-split replay and real reviewer time/correction measurements exist.
- [ ] Provider outage, permission revocation, and catalog drift are tested in a
  staging deployment with real adapter contracts.

The core safety blockers and replay receipt are now in the production review
contract. Keep the remaining evaluation-only policy work—especially role
classification and correction learning—out of `src/` until it has the same
cross-enterprise evidence.
