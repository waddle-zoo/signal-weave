# Harbor: historical source validation

This is a **source and native-transport checkpoint**, not a new business-agent
benchmark. It prepares one known development company for the
[workflow study](../workflow-research-plan.md). No new acting analyst, real human,
card evaluation, Jev judgment or notification ran in this checkpoint.

## What ran

| Check | Observed result | Scope |
| --- | --- | --- |
| Independent raw-history reconciliation | Three seeds × 12 historical cutoffs: 36 SQLite snapshots matched the independent reference | Ticket state, resolution/response populations, backlog, coverage and orphans; not 36 companies or agent workflows |
| Focused source/reference tests | 26 passed in 129.06s | Includes hand-worked boundaries, actual read-only stdio MCP, late data, corrections, retractions and future-data exclusion |
| Native preflight v1 | Failed at all three cutoffs | A research assertion confused an inspection alias with an upstream registration key; retained, not rescored |
| Separate native preflight v2 | All nine exports matched direct SQL at three cutoffs; twelve evidence rows | Current fingerprint-checked native candidate, private noninteractive setup, default agent tool profile, actual source subprocess |
| Provider activity in both preflights | Zero attempts; zero provider request budget | Dummy key only; this is deliberately not live-Jev evidence |
| Final `make verify` | Lint clean; 4,287 passed, 12 opt-in skips in 279.51s on Python 3.12.10 | Full software regression suite, not business observations |
| Python 3.11.6 compatibility slice | 19 reference/preflight tests passed in 11.08s | Separate focused check, not the full suite or a second native run |

The second preflight used byte-identical source snapshots and the same SQL
definitions as the first. The repair checks that each evidence row carries the
inspection alias assigned by the normal API. It does not bypass the production
bridge's prior validation of the upstream source identity. SDK-wrapped failures
now retain meaningful leaf diagnostics rather than only “TaskGroup” errors.

The historical cutoffs were February 23, March 16 and April 6, 2026, at 06:00 UTC.
They exercise ordinary source state, delayed ticket creation records, then
backfilled creation records alongside a still-unknown recent partition manifest.
Unknown expected volume remains null rather than silently becoming zero.

## Why the history is different

The old Harbor fixture contains final retrospective state. Filtering that state
by creation week would expose resolutions that were not yet known at the time.
It remains unchanged, along with its stopped paid cohort.

The new [contract](../../evaluations/data/harbor-history-contract.md) uses event
time and availability time, with revisions and retractions. Each snapshot stores
only knowable versions. A SQL caller receives the snapshot, not private future
history or grader labels. The default synthetic profile has eighteen creation
weeks: six warmup weeks and twelve observation cutoffs, with long-tail unresolved
work, late arrivals and corrections. Those are authored simulation choices, not
empirical customer distributions or twelve independent trials.

The [reference](../../evaluations/harbor_history_reference.py) independently
reconstructs state and arithmetic from raw revisions. It does not import the
generator, projector, SQL views or production normalizers. Manual boundary tests
supplement agreement between implementations. Initial reference-contract and MCP
structured-output errors were caught and repaired before native admission;
agreement alone is not independent proof that a business definition is useful.

## Important analytical limit

The latest and preceding **creation cohorts have unequal ages**. Their
already-resolved-ticket miss rates are descriptive, not an age-matched measure
of service deterioration. The exports explicitly retain `age_matched=0` and
show current open backlog separately. Warmup history does not fix this bias.

An operational-performance workflow needs an owner/expert-confirmed population
and comparison—such as a common observation horizon—not an alert rule attached
to this descriptive delta. The next onboarding experiment must test whether the
agent recognizes this distinction and obtains the missing intent. Adding a
warning to an invalid comparison is not a completed analytical solution.

This boundary does not prevent supported partial facts or urgent warnings about
independently established backlog. Such messages still need an agreed policy,
appropriate recipient and a useful final agent explanation.

## Reproduce

From a development checkout with dependencies installed:

```sh
uv run pytest -q tests/test_harbor_history.py tests/test_harbor_history_reference.py tests/test_harbor_history_preflight.py
```

With a locally built native executable whose production fingerprint matches the
checkout, run the actual zero-inference transport check into a **new** directory:

```sh
.venv/bin/python -m evaluations.harbor_history_preflight --binary dist/signalweave --output artifacts/harbor-history-new-preflight
```

The runner refuses an existing output. It uses temporary private setup homes,
does not register with a personal agent, checks the exact default MCP inventory,
and retains snapshot, query and method hashes. Prepared fixed SQL is researcher
work, not automatic onboarding; both future arms must receive the same assets.
This is an actual local SQLite/company-MCP boundary, not Preset, Superset, Hex,
Looker, a fresh download/install, hosted deployment or a human usability session.

## Evidence identity and remaining gate

Native candidate: version `0.2.0rc3`, embedded commit `2a9b852`, Python 3.12.10.
Its production fingerprint matched the current checkout; no production source
or build inputs changed in this checkpoint. The binary reports a dirty tree and
an older embedded commit, so this is matching production/build inputs, not exact
clean-HEAD provenance or a new published release.

- Native SHA-256: `d6b997a9f91fd960be7957783af2c21d5e377cd2f37e52ff46a61c7e01305c34`
- Production source fingerprint: `2af23f36d0e5894dfc3c804a915209d63c69db0930b893c93eaf4eb5e7496972`
- Failed v1 local report: `7c167ae3b12a45c6e4af178b37123b47c7087a515b0e80cefd80a8d9cfa8dbbd`
- Separate v2 local report: `fbd4a787ad53ab504f29f850f7be2da37a312c1f78adf4a4182624da53f5e2c4`
- Focused long-tail test log: `32f472cd40a7b6b2f6303d18dbf02902a1fcc98e5469496118bd8e05b852585c`
- Final full verification log: `e73efd752f53aba8e565099177235f3abe939fd122a287315c2262acdfa61c15`
- Python 3.11 focused log: `5d9e7575a31655df9c5836e419181a1b13f0adc3779628b4bba499a7adcfb300`

Reports, databases and transcripts stay in ignored local artifacts rather than
growing the public evidence tree. The executable and method files were hashed
before and after the successful preflight. Independent Luna-xhigh DE/code review
inspected the actual reports and identity-validation path and cleared this
source/native checkpoint only. Its audit noted that the report does not retain
the returned alias value or hash all imported transport/budget helpers. Those
helpers were inspected and unchanged from the embedded commit; the omissions
remain audit-coverage limits, not a new rerun or an observed identity bypass.
This is internal review, not external peer review or business acceptance.

Still required: frozen business definitions and owner interaction, a complete
fresh-onboarding/recurring workflow pair with live Jev and a strong equally
equipped agent baseline, useful final messages, cost accounting, other company
domains/connectors, and actual human sessions. No comparative business lift or
enterprise-readiness claim follows from the checks above.
