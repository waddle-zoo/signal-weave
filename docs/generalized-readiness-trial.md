# Generalized Jev readiness trial

The repository includes a reproducible, data-driven trial for the core
SignalWeave path:

```text
native catalog bootstrap -> bounded candidate retrieval -> Jev judgment ->
typed evidence bundle -> durable certification report
```

It is deliberately not a Superset-only test. The fixture covers four synthetic
enterprise shapes and five workflows across Superset, Looker, Hex, dbt, Trino,
and Airflow. The workflows include cross-dashboard monitoring, a governed
metric, a data-quality/freshness dependency, normal variation, a no-match
request, stale evidence, and a failed source.

## Reproduce it

The trial requires a TypeSafe key and uses Jev for the product path:

```bash
export TYPESAFE_API_KEY_FILE=/path/to/typesafe-key
.venv/bin/python evaluations/generalized_readiness_trial.py \
  --output artifacts/generalized-readiness-jev.json
.venv/bin/python evaluations/generalized_readiness_adversarial_review.py \
  artifacts/generalized-readiness-jev.json \
  --output artifacts/generalized-readiness-adversarial.json
```

The fixture is in
[`evaluations/data/generalized-readiness-workflows.json`](../evaluations/data/generalized-readiness-workflows.json).
The adversarial review is an independent deterministic gate in
[`evaluations/generalized_readiness_adversarial_review.py`](../evaluations/generalized_readiness_adversarial_review.py).

## Latest live result

Run on 2026-09-21/22 from the checked-out branch with Jev:

| Gate | Result |
| --- | ---: |
| Bootstrap manifests ready | 5 / 5 |
| Retrieval candidate recall | 100% |
| Retrieval recommended precision | 100% |
| Retrieval recommended recall | 100% |
| No-match accuracy | 100% |
| Unauthorized returned refs | 0 |
| Workflow cases | 14 / 14 exact outcomes |
| Workflow evidence recall | 100% |
| Workflow retrieval recall | 100% |
| Unsafe actions | 0 |
| Runtime errors | 0 |
| Jev requests | 20 |
| Native catalog full scans | 0 |

The adversarial review returned `pass` across Jev-only execution, tenant
isolation, no-match behavior, label-boundary checks, digest presence, train /
holdout / adversarial partitions, and the zero-unsafe-action gate.

The workflow cases are owner-labeled synthetic snapshots; the labels stay in
the evaluator and are not part of the Jev state. The trial proves that the
SignalWeave contracts compose over these messy shapes. It does not prove a
connector's real credentials, query economics, or a company's semantic labels.
Those still require a customer-owned shadow replay before production push.

## Why the result is meaningful

The catalog adapters advertise 100,000-item virtual catalogs, implement native
bounded search, and intentionally raise if SignalWeave tries to call
`list_resources`. The trial therefore checks the important scaling boundary:
Jev receives a bounded candidate set, not a raw catalog dump. Each source is
authorized and inspected through a tenant-scoped lookup before evidence is
used.

The evidence is also split into separate gates. A pass requires the adapter to
surface the relevant assets, Jev to recommend them, and the card judgment to
produce the owner-labeled outcome with complete evidence. A high Jev
confidence by itself is not treated as proof.

## Remaining external proof

This is a strong synthetic readiness gate, not a claim of universal enterprise
readiness. The next proof requires real, independently maintained labels from
one company's historical snapshots, real adapter permissions, source query
latency/bytes/cost telemetry, and a live shadow period with delivery disabled.
