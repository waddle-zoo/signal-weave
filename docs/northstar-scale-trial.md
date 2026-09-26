# Northstar Outfitters scaled mock trial

This is the larger Jev-only trial for the Northstar Outfitters case study. It is
evaluation code, not a production scenario or a claim that generated labels are
customer truth.

The trial is built from the editable Northstar domain and company configuration.
It does not put expected answers into `src/`, and it does not ask Jev to invent
actions, SQL, permissions, or recipients.

## What runs

- 12 analytical domains from `evaluations/data/northstar-company.json`.
- 24 generated owner personas, plus the existing 40-agent role graph: domain
  curators, domain analysts, enterprise operators, executives, and communications
  partners.
- 168 owner-authored workflow cards: seven states across the 24 personas,
  including corroborated notification, explainable suppression, contradictory
  investigation, stale-data escalation, definition mismatch, missing baseline,
  and source failure.
- 169 Jev retrieval cases (including a no-match control) and 168 Jev workflow cases across four disjoint time
  splits: train, validation, holdout, and adversarial.
- Six source adapters shaped like the Northstar environment: Superset, SQL,
  Airflow, tables, incidents, and calendars.
- A native adapter boundary reporting 100,000 virtual resources per adapter.
  Only a bounded candidate set is materialized for Jev; the trial fails if an
  adapter is full-scanned.

The expected outcomes and required evidence are held by the evaluation harness.
The production evaluation path receives only the card, authorized candidate
resources or snapshots, context, and dataset identity. A recording wrapper
checks that label-shaped keys do not enter Jev state.

## Run the live trial

Keep the TypeSafe credential in a file. The command below writes outputs under
`artifacts/`, which is generated trial data and is ignored by Git.

```bash
TYPESAFE_API_KEY_FILE=/path/to/apikey_typesafe \
PYTHONPATH=src:. \
.venv/bin/python -m evaluations.northstar_scale_trial \
  --output artifacts/northstar-scale/report.json \
  --fixture-dir artifacts/northstar-scale/fixtures
```

Then run the independent report-only gate:

```bash
PYTHONPATH=src:. \
.venv/bin/python -m evaluations.northstar_scale_adversarial_review \
  artifacts/northstar-scale/report.json \
  --output artifacts/northstar-scale/adversarial-review.json
```

If a full run has already completed and only retrieval changed, do not pay for
the 336 workflow judgments again. The retrieval-only retry below runs the 169
anchor-discovery cases and 168 graph-assisted bundle cases live with Jev, then
reuses the prior workflow report only after checking the generated cards,
dataset IDs, role roster, variants, source adapters, and approval status match
exactly:

```bash
TYPESAFE_API_KEY_FILE=/path/to/apikey_typesafe \
PYTHONPATH=src:. \
.venv/bin/python -m evaluations.northstar_scale_trial \
  --retrieval-only \
  --reuse-workflow-report /path/to/prior-full-run/report.json \
  --output artifacts/northstar-scale/retrieval-retry/report.json \
  --fixture-dir artifacts/northstar-scale/retrieval-retry/fixtures
```

This is still a Jev-only trial: both retrieval stages are live, while the
workflow section is explicitly marked as reused approved Jev evidence. It is
not a fresh workflow benchmark.

The gate requires Jev, all seven messy workflow variants, all four time splits,
ready source bootstrap, full primary-anchor and graph-assisted related-source
group recall, at least 90% recommended precision/recall, zero unauthorized
references, zero unsafe automatic actions, zero workflow errors, full
evidence/retrieval recall, no owner-label leakage, and zero native full-catalog
scans. A related-source group is an owner-approved set of equivalent
cross-system assets—for example, the SQL, Airflow, table, incident, or calendar
representation of one business context. The workflow path still evaluates the
exact human-selected sources.

## Evidence and current gap

The final credit-conserving live run on 2026-09-26 exercised the two retrieval
stages with Jev. It reused the previously completed 168-case workflow replay
only after strict fixture, card, dataset, roster, variant, and source-boundary
identity checks. The independent report-only adversarial gate passed:

| Layer | Result |
| --- | --- |
| Bootstrap | 6/6 tenant-aware adapters ready; six native authorization calls; zero full-catalog scans |
| Workflows | 168 cases; 96.43% exact outcome accuracy; 100% evidence and exact-source retrieval recall; 0 unsafe actions; 0 errors |
| Anchor discovery | 169 cases; 100% candidate recall; 93.80% recommended precision; 100% recommended recall; 100% primary-anchor recall; 100% no-match accuracy; 476 ms median Jev latency |
| Graph-assisted bundles | 168 cases; 100% candidate group recall; 100% selected group recall; 100% selected precision; 0 unauthorized refs; 0 errors; 569 ms median Jev latency; 35 cases retained an explicit low-confidence review warning |
| Scale | 40 role agents; 24 owner personas; 12 domains; 1860 materialized descriptors over six virtual 100k-resource catalogs |
| Jev usage | 337 live retrieval calls plus 336 reused workflow calls; 8,385,520 live/reused input tokens and 314,544 output tokens recorded in the final report |

The result exposes an important product boundary. Seedless goal-only discovery
still recovered only 53.25% of owner-labeled related-context groups. That is a
real warning, not a hidden score: a free-form goal does not contain enough
information to identify every cross-system relationship in a large catalog.
The approved production path is therefore a human-approved card anchor plus a
trusted context/relationship snapshot. Jev ranks the bounded projections, while
SignalWeave requires one projection per explicit graph obligation, preserves
low-confidence selections as review warnings, and does not fill the bundle
with unrelated eligible sources. That graph-assisted path reached 100% group
recall and 100% selected precision in all 168 cases.

The branch also records a retrieval-only retry mode so future runs do not pay
for another 336 workflow judgments when only retrieval changes. It refuses to
reuse workflow evidence unless the fixture and approval identity checks match,
and the TypeSafe adapter retries bounded transport failures without retrying
validation or model errors.

## What success means

Passing this trial means the current SignalWeave contracts survive a larger
Northstar-shaped shadow workload with bounded Jev retrieval and typed workflow
decisions. It gives us evidence for a staged real-company shadow deployment.

It does not prove that the generated Northstar labels represent real operators,
that delivery systems work, or that every company can automate every analytical
task. A production case study still needs owner-labeled historical or shadow
data, real adapter authorization, and delivery-disabled observation before any
automatic push is enabled.
