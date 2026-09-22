# AWS DocumentDB performance trial

This small Jev-only trial tests the operational pattern where CloudWatch
metrics need to be interpreted alongside deployment history, incidents,
runbooks, and the ownership graph. It is evaluation code and synthetic data,
not an AWS integration or a production claim.

## Card shape

The card is intentionally human-authored and keeps one CloudWatch metric-group
anchor. Its free-form intent says to watch latency, replication lag,
throttling, storage pressure, regional concentration, deployment timing, and
isolated CPU noise. It asks which owner should receive the result and says not
to page on CPU alone.

The fixture lives in
[`documentdb-performance.json`](../evaluations/data/documentdb-performance.json).
The adapter and trial runner live in
[`documentdb_performance_trial.py`](../evaluations/documentdb_performance_trial.py).

## Execution path

1. A native-style CloudWatch adapter exposes bounded metric candidates.
2. Jev ranks the bounded expansion bundle.
3. SignalWeave resolves the selected deployment, incident, runbook, and owner
   sources through tenant authorization.
4. Jev compiles the card and judges the normalized observations and evidence.
5. The result is typed: outcome, probabilities, evidence, source keys, and
   delivery method. External delivery remains disabled in the trial.

Run it with the TypeSafe key file:

```bash
TYPESAFE_API_KEY_FILE=/path/to/apikey_typesafe \
PYTHONPATH=src:. \
.venv/bin/python -m evaluations.documentdb_performance_trial \
  --output artifacts/documentdb-performance/report.json
```

## Live result

The live run on 2026-09-22 used three Jev calls: related-source ranking, card
plan compilation, and the final typed judgment.

| Check | Result |
| --- | --- |
| Related-source recall | 100%: deployment, incident, runbook, and owner were selected |
| Evidence | 4 CloudWatch observations across 5 sources; 11 evidence items after context enrichment |
| Jev judgment | `notify`, confidence `0.99` |
| Authorization | Tenant-scoped inspection only |
| Native catalog scans | 0 |
| Label leakage | None |

The evaluator label in the fixture is `investigate`, matching the illustrative
message in the product example. Jev chose `notify` because the card's current
policy describes three affected regions, eight clusters, correlated latency,
lag, throttling, storage pressure, a recent deployment, and a prior matching
incident as enough evidence to contact the owner. That is the exact kind of
human-policy calibration the card is meant to expose.

If the intended policy is “investigate first unless direct customer-impact
evidence exists,” the card should say that explicitly—for example, require a
customer error-rate or availability signal before choosing `notify`. The
retrieval and evidence path already supports that additional source; this
trial shows that the remaining decision is card policy, not an LLM prompt or a
dashboard-specific implementation.

The trial does not claim that the synthetic values match AWS semantics, that a
deployment caused the regression, or that an external owner was contacted.
