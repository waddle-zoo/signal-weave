# Enterprise readiness experiment

This is the evaluation harness for SignalWeave’s generalized insight-card
contract. It stays outside `src/`: generated catalogs, hidden labels, persona
briefs, and scoring logic are research fixtures, not product decision logic.

The numbers below are evidence ledger entries, not a single product score. The
current post-hardening rerun is recorded in
[`docs/research-rerun-2026-09-25.json`](research-rerun-2026-09-25.json).

## Portfolio

The checked-in portfolio generates three deliberately different companies:

- Northstar Commerce: 144 base dashboards across commerce, finance, marketing,
  security, and platform operations.
- Harbor Bank: 100 base dashboards across regulated financial-services domains.
- OrbitWorks SaaS: 100 base dashboards across product, growth, customer, and
  platform domains.

Across the portfolio the generator produces 344 base dashboards, 168 scenario
dashboards, 3,649 charts, 1,664 resources, 22 personas, and 144 tasks. Resources
span Superset, SQL, Airflow, table-quality, incident, and calendar adapters. The
task variants include corroborated notify, explained ignore, contradictory
investigate, definition/grain mismatch, stale escalation, missing baseline, and
source failure.

This fixture is intentionally dashboard-heavy because the first proof uses the
shipped Superset adapter. It tests cross-source composition; it is not a claim
that an enterprise must use Superset or that a monitor is limited to dashboards.

The task labels are hidden from the MCP client. Each task is a free-form card
brief with `what_to_watch`, `why_watch`, `watch_for`, `questions`, and configured
delivery outcomes. The engine receives all normalized observations; changed rows
are only prioritized for presentation.

## Reproduce the deterministic matrix

```bash
uv run python -m evaluations.enterprise_mcp_cli generate \
  --config evaluations/data/enterprise-portfolio.json \
  --output artifacts/enterprise/portfolio-fixture.json

uv run python -m evaluations.enterprise_runner \
  --fixture artifacts/enterprise/portfolio-fixture.json \
  --store artifacts/enterprise/portfolio-research-cards.json \
  --trace artifacts/enterprise/portfolio-research-trace.jsonl \
  --report artifacts/enterprise/portfolio-research-report.json \
  --markdown artifacts/enterprise/portfolio-research-report.md \
  --evaluator research
```

The current deterministic research-driver rerun completed every workflow and
preserved all provenance, but it did not achieve exact business decisions:

| Measure | Result |
| --- | ---: |
| Workflow-complete sessions | 144/144 |
| Complete cards | 144/144 |
| Provenance-complete results | 144/144 |
| Exact source selection | 144/144 |
| Exact decisions | 100/144 |
| Unsafe automatic actions | 0 |
| Trace events | 4,635 |
| Hash-chain and protocol validation | valid |

The 44 mismatches were 22 `insufficient_data -> ignore` and 22
`notify -> investigate` routes. This validates adapter composition, MCP
wiring, approval sequencing, evidence retention, and fail-closed gates. It is
not model-accuracy evidence because the research driver uses a deterministic
research judger; the mismatches are retained as a failed semantic baseline,
not converted into a success claim.

## Earlier recorded live Jev run

The portfolio was then run through the real TypeSafe Jev path with the same 144
tasks and no research-driver labels available to the service:

| Measure | Result |
| --- | ---: |
| Exact decisions | 134/144 |
| Workflow/card/provenance/source selection | 144/144 each |
| Unsafe automatic actions | 0 |
| Trace integrity | valid; 2,304 events |
| Conservative misses | 10 `notify` → `investigate` |

The 10 misses were all corroborated-notify tasks. No stale, missing-baseline,
source-failure, explained-ignore, contradictory, or definition-mismatch task
took an unsafe automatic route. This is an encouraging safety result, not a
production guarantee; the fixture is synthetic and the owner labels were
generated alongside the scenarios.

## Closure Jev run

The same matrix was rerun after adding typed tenant-aware discovery, metric
query planning, and receipt/idempotency controls. The independent report is
`artifacts/enterprise/closure-jev.report.json`.

| Measure | Result |
| --- | ---: |
| Sessions | 144 |
| Exact decisions | 130/144 |
| Workflow/card/provenance/source selection | 144/144 each |
| Unsafe automatic actions | 0 |
| Trace integrity | valid; 4,032 events |

The 14 disagreements were conservative or insufficient-evidence routes. This
is a regression and safety signal over synthetic labels, not a claim of
enterprise accuracy.

Run it with a credential explicitly:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python -m evaluations.enterprise_runner \
  --fixture artifacts/enterprise/portfolio-fixture.json \
  --store artifacts/enterprise/portfolio-jev-cards.json \
  --trace artifacts/enterprise/portfolio-jev-trace.jsonl \
  --report artifacts/enterprise/portfolio-jev-report.json \
  --markdown artifacts/enterprise/portfolio-jev-report.md \
  --evaluator jev --model jev-latest
```

## Persona and MCP boundary

The MCP CLI exposes only the allowlisted source, discovery, card, simulation,
approval, evaluation, and readback tools. A persona session is expected to use
that surface rather than importing SignalWeave or reading the fixture directly.
The trace records calls, arguments, results, source inspections, semantic
judgments, errors, and the final decision. The current harness logs and audits
that boundary; it does not provide operating-system sandboxing. A Luna persona
can still bypass the CLI if its host process is instructed to do so, so the
recorded persona arm is tool-ergonomics evidence, not a security isolation proof.

The corrected three-session Luna cohort used one task from each enterprise. All
three completed the ordered MCP protocol and the trace was valid; however, none
produced a complete card or exact hidden-label decision:

| Persona task | Variant | Actual result | Card complete | Source set exact |
| --- | --- | --- | ---: | ---: |
| Northstar CFO | corroborated notify | investigate | no | no |
| Harbor Chief Risk Officer | definition mismatch | insufficient data | no | no |
| OrbitWorks Chief Product Officer | missing baseline | investigate | no | no |

The agents repeatedly used non-contract fields such as `summary`,
`decision_criteria`, and `delivery_options`, leaving `watch_for`, `questions`,
and delivery methods empty. This is a real onboarding failure: the MCP protocol
is usable, but the current free-form agent path does not reliably preserve the
owner’s card semantics. The cohort produced zero unsafe automatic actions, but
that safety result is partly explained by incomplete cards and conservative
abstention. It is evidence for improving the client contract, not a Luna
accuracy claim.

The first setup attempts are excluded because the agents were started in the
workspace root and could not find the repository virtualenv; they performed no
MCP calls or data access.

## Independent closure trials

The later closure work separates source discovery from decision evaluation. A
live Jev discovery trial used 48 independent tasks, 576 resources before tenant
filtering, same-name cross-tenant decoys, and two-source labels that were not sent
to Jev. It achieved:

| Measure | Result |
| --- | ---: |
| Exact top-2 source sets | 48/48 |
| All expected sources in top 10 | 48/48 |
| Wrong-tenant sources returned | 0/48 |

A separate live Jev metric-plan trial used 24 held-out metric labels and approved
Trino-shaped catalogs:

| Measure | Result |
| --- | ---: |
| Correct metric definitions | 24/24 |
| Correct dimensions | 24/24 |
| Correct time grains | 24/24 |
| Partition-bounded queries | 24/24 |
| SELECT-only, semicolon-free output | 24/24 |

These are synthetic regression gates for the typed catalog and compiler. They do
not establish production accuracy, query cost, or correctness of an arbitrary
company's metadata catalog.

The dynamic evidence-bundle trial uses the same 48-task catalog, but gives each
card one human-approved anchor and asks Jev to add related context. The expected
related source is held out from the request. It selected 48/48 expected related
sources, preserved 48/48 anchors, respected the related-source limit in 48/48
cases, and returned zero wrong-tenant resources. Run it with:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  make bundle-trial
```

This proves the retrieval boundary and tenant filtering under the fixture; it
does not prove that a company's metadata descriptions are complete or that every
related source is operationally useful.

## Smaller evaluator comparison

The five-repeat four-case comparison uses identical normalized inputs and the
same safety gates:

| Evaluator | Exact decisions | Median | p95 | Requests | Errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Jev | 15/20 (75%) | 771 ms | 990 ms | 40 | 0 |
| OpenAI embedding + reasoning | 14/20 (70%) | 2,300 ms | 2,682 ms | 40 | 0 |

This is a small synthetic comparison. It does not establish universal Jev
superiority, cost, or production latency. It does show why the relevant unit of
comparison is the final typed decision and safety behavior, not the quality of a
free-form explanation.

## What remains unproven

Before treating SignalWeave as enterprise-ready, run a shadow-mode export from
a real team with time-split labels and delivery outcomes. Measure false
automatic actions, useful-alert rate, investigation rate, owner rescue rate,
latency, usage, and whether source discovery chooses the right assets. The
current experiment still lacks process-enforced MCP isolation, independent
domain-owner labels, historical holdout data, and a real delivery sink. The
runtime now records approval identity and idempotent decision receipts, but those
receipts are not a substitute for production delivery validation.

The older 12-domain regression fixture was also rerun after the generalized
changes: 72/72 sessions completed with no provider errors, 68.1% exact overall,
zero wrong automatic actions, and 12 missed actionable cases. Its 0%
corroborated-notify and 8.3% explained-ignore class accuracy makes it a
regression signal, not a product success metric.

Generated fixtures, traces, and reports live under ignored `artifacts/enterprise/`
so credentials and large logs are not committed.
