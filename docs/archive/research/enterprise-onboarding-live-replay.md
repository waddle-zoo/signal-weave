# Historical enterprise onboarding live Jev replay

Status: superseded exploratory evidence. This was an 11-case live TypeSafe
replay, not an external or production benchmark. The current 30-case fixture
and live replay is documented in
[`enterprise-onboarding-expanded-replay.md`](enterprise-onboarding-expanded-replay.md).

Command:

```bash
.venv/bin/python evaluations/onboarding_contract_trial.py \
  --evaluator live \
  --typesafe-key-file /Users/brandonsovran/Downloads/apikey_typesafe \
  --format markdown
```

The same scenario catalog was used as the fixture run. Candidate resources,
tenant boundaries, expected labels, and source metadata were unchanged. The
only change was replacing the deterministic ranking double with the live
`JevJudger`; hidden expected labels were never sent to Jev.

## Results

| Measure | Fixture Jev-shaped ranking | Live Jev |
| --- | ---: | ---: |
| Scenarios | 11 | 11 |
| Full current contract passes | 8 / 11 | 7 / 11 |
| Prototype readiness gates satisfied | 11 / 11 | 11 / 11 |
| Mean required-candidate recall | 1.00 | 1.00 |
| Exact recommended candidate sets | 10 / 11 | 8 / 11 |
| Wrong-tenant candidates | 0 | 0 |

The candidate recall number is conditional: the harness gives the discovery
layer a fixture-backed bounded page, then measures Jev's ranking over that page.
It does not prove that a real enterprise catalog search will return every
relevant asset.

## Live failures

- **Fintech definition ambiguity:** live Jev did not reproduce the expected
  candidate set around competing net-revenue definitions. This supports keeping
  definition conflict as a separate judgment and approval blocker rather than
  relying on relevance alone.
- **Sparse lineage catalog:** live Jev found the required lineage candidate but
  also recommended an extra candidate. That is acceptable as a review suggestion
  only if its role and reason are explicit; it is not safe as silent card scope.
- **Stale source:** live Jev under-recommended one of the stale-source-related
  candidates, and the existing onboarding review still reported
  `ready_for_approval` when all anchors were selected. Source health must be a
  code-owned readiness gate, independent of the model's ranking.
- **Large catalog:** live Jev ranked the returned anchor, but the existing review
  still reported `ready_for_approval` despite `has_more=true`. Catalog
  completeness must be a code-owned readiness gate.

## Interpretation

This replay strengthens the case for a generalized onboarding contract but does
not establish a production success rate. It shows three layers behaving
differently:

1. **Adapter/authorization layer:** passed the fixture's tenant and bounded-page
   checks.
2. **Jev semantic ranking:** useful but variable on ambiguous definitions and
   sparse metadata.
3. **Approval/readiness layer:** the existing production review was too
   permissive; the exploratory typed readiness assessor caught all expected
   stale, incomplete, ambiguous, and no-match conditions.

The correct product implication is not to add a larger prompt. It is to keep
Jev's recommendations inspectable and let code own hard gates for identity,
catalog completeness, source health, definition conflicts, and delivery policy.

## Limitations and next proof

- Eleven cases are too small to estimate enterprise reliability.
- The source catalog and observations are synthetic; only the Jev ranking call
  was live.
- The run does not test principal-level OAuth, revoked access after discovery,
  real catalog pagination, live source failures, query queues, or operator time.
- The expected recommendation sets are a research fixture, not universal truth.

Next, run a time-split, operator-labeled replay with anonymized real discovery
history, then add permission revocation and source-health mutations. Keep the
readiness assessor in evaluation code until those gates are validated against
real approval decisions.
