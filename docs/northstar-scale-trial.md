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

The gate requires Jev, all seven messy workflow variants, all four time splits,
ready source bootstrap, full primary-anchor and related-source-group recall, at
least 90% recommended precision/recall, zero unauthorized references, zero
unsafe automatic actions, zero workflow errors, full evidence/retrieval recall,
no owner-label leakage, and zero native full-catalog scans. A related-source
group is an owner-approved set of equivalent cross-system assets—for example,
the SQL, Airflow, table, incident, or calendar representation of one business
context. The workflow path still evaluates the exact human-selected sources.

## Evidence and current gap

The completed live Jev run on 2026-09-22 exercised the full population before
the bounded overfetch and related-source-group scorer changes:

| Layer | Result |
| --- | --- |
| Bootstrap | 6/6 adapters ready; six native authorization calls; zero full-catalog scans |
| Workflows | 168 cases; 96.43% exact outcome accuracy; 100% evidence and exact-source retrieval recall; 0 unsafe actions; 0 errors |
| Retrieval | 169 cases; 99.41% candidate recall; 96.47% approved-bundle precision; 94.05% primary-anchor recall; 29.17% exact secondary-source recall |
| Scale | 40 role agents; 24 owner personas; 12 domains; 1860 materialized descriptors over six virtual 100k-resource catalogs |
| Jev usage | 505 calls: 169 retrieval and 336 workflow judgments; median retrieval latency about 651 ms; median workflow latency about 853 ms |

The independent adversarial gate correctly failed this run because exact
cross-system retrieval was not reliable enough. Investigation found two gaps:
the old scorer treated one arbitrary adapter as the only valid representation
of a cross-system context, and the multi-adapter search frontier could drop a
relevant seventh result before Jev saw it. The branch now models owner-approved
related-source groups and overfetches by the number of adapters while keeping
the Jev candidate budget at 40. The fix has passing unit tests and local
candidate-bound checks, but it still needs a fresh live Jev run after TypeSafe
credits are restored. The attempted rerun returned HTTP 402 before any Jev
judgment, so this branch does not claim the retrieval gate is proven yet.

## What success means

Passing this trial means the current SignalWeave contracts survive a larger
Northstar-shaped shadow workload with bounded Jev retrieval and typed workflow
decisions. It gives us evidence for a staged real-company shadow deployment.

It does not prove that the generated Northstar labels represent real operators,
that delivery systems work, or that every company can automate every analytical
task. A production case study still needs owner-labeled historical or shadow
data, real adapter authorization, and delivery-disabled observation before any
automatic push is enabled.
