# Mass analytical insights trial

This evaluation asks where SignalWeave helps when cached dashboard results are
cheap but a new Trino query takes about three minutes.

The comparison is between:

- a naïve general-agent arm that reasons over every workflow and issues
  uncached exploratory queries; and
- a SignalWeave-mediated arm where Jev judges whether cached evidence is enough,
  compatible query plans are deduplicated, and an existing agent receives only
  the resulting evidence bundle.

## Live Jev path sample

The trial sampled two cases from each of seven workload types:

- stable cached dashboard;
- explainable movement;
- corroborated actionable movement;
- ambiguous movement requiring diagnosis;
- stale or failed source;
- metric definition or grain conflict;
- cross-card diagnostic cluster.

The live Jev sample selected the expected path in **14/14 cases**, with 350 ms
median and 399 ms p95 latency. The decisions included `reuse`, `query`, and
`escalate`—not merely one binary alert decision.

## Modeled 10,000-workflow economics

The large population is a configurable workload model. Under the checked-in
assumptions, a three-minute Trino query, 32-way Trino concurrency, 1.4× scan
size for deduplicated groups, and 64-way agent/Jev concurrency produced:

| Measure | Naïve agent | SignalWeave-mediated agent |
| --- | ---: | ---: |
| Expensive query executions | 11,900 | 82 deduplicated groups |
| Query work | 11,900 units | 114.8 units |
| Query wall time | 1,116 minutes | 12 minutes |
| General-agent reasoning runs | 10,000 | 4,700 |
| Normalized cost units | 1,240,000 | 44,980 |

That is a modeled **99.31% reduction in expensive query executions**, **99.04%
less query work**, **53% fewer general-agent reasoning passes**, and **96.37%
lower normalized cost** under the chosen weights. If Jev is assigned 10× rather
than 1× the configured unit cost, the modeled total reduction is still 89.11%.

The result is driven by query avoidance and reuse, not by replacing a
three-minute query with a subsecond Jev call:

1. Jev judges whether the cached evidence is sufficient.
2. SignalWeave reuses one approved query result across compatible cards.
3. Only unresolved or ambiguous cases reach Trino.
4. The existing agent receives a bounded evidence bundle instead of exploring
   the catalog and issuing its own query loop.

## Limitations

The 10,000-workflow population is simulated. The general-agent arm is a
workload model, not a benchmark against a named model. Normalized cost units are
not dollars. A production proof must replace them with Trino bytes scanned,
CPU-seconds, queue time, provider usage, and actual invoices.

Query grouping must also preserve tenant, permission, metric-definition, and
time-window boundaries. The next useful test is a shadow run against real card
history where every query records its fingerprint, bytes scanned, cache hit,
agent tool calls, Jev calls, wall time, and eventual usefulness.

Run it with:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
PYTHONPATH=src:. \
.venv/bin/python -m evaluations.mass_analytical_trial \
  --evaluator jev
```

The editable workload and cost assumptions are in
[`evaluations/data/mass-analytical-scenarios.json`](../evaluations/data/mass-analytical-scenarios.json).
The generated report is
[`artifacts/mass-analytical-trial.md`](../artifacts/mass-analytical-trial.md).
