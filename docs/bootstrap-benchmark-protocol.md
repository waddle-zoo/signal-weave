# Bootstrap benchmark: preliminary preregistration

Status: development trials in progress; held-out Codex protocol v2 below.
No performance result is asserted here. Freeze this document, source revision, full dataset
digest, prompts, model configuration and budgets before running held-out cases.
Changes after seeing a held-out result create a new benchmark version; report
the failed run, do not silently rename it development.

## Question and claim boundary

Can an agent author and validate a reusable SignalWeave card from an ordinary
business request **and supplied owner policy**, then monitor more accurately or
economically than the same agent using the same company tools directly?

This is not unaided discovery of unstated business intent. The initial request is
short and nontechnical, but the simulated owner knows precise business policy,
metric meaning and authorized routes. Those answers are intentionally helpful.
The test measures converting that supplied context into reusable operational
instructions, not whether a novice could invent a defensible statistical method.

It is also not a causal-inference test, large-catalog test, real customer case
study or proof of universal enterprise readiness. Each company has four assets.
Some sources expose reviewed rate tables; others expose raw aggregate fields or
ambiguous/incomplete metadata. Connecting and normalizing a real MCP remains a
separate integration problem.

## Independent fixture boundary

`evaluations/bootstrap_scenarios.py` owns fixtures and scoring only. It makes no
model calls and does not import SignalWeave's engine, Jev adapter, runtime
analysis solver, or benchmark runner. It uses production `ResourceDescriptor`
and `ResourceSnapshot` only to validate public source contracts.

```python
scenarios = build_scenarios(seed=20261001, split="holdout")
episode = public_episode(scenarios[0])  # onboarding only
prompt_context = agent_context(episode)
# Tools read episode["catalog"], episode["period"]["snapshots"],
# and ask_owner(episode, topic). None requires private labels.
```

Each full fixture has `scenario_id`, `public` and `private`. Private labels include
outcome, recipients, necessary evidence, numerical targets and claim constraints.
Never serialize the full fixture into a model prompt or adapter. `public_scenario`
is a full **tool-server export**, including future periods; it is not an agent
input. `public_episode(scenario, period_id)` selects only the current period.
`agent_context(episode)` further removes source payloads and owner answers from
the opening prompt. Keep evaluator labels in a separate scorer process where
practical. Checked-in synthetic code is not a cryptographically secret test set;
agent tools must not include fixture-code or repository-file access.

The public numerical vocabulary is declared from measurement schemas before any
period labels; it is not inferred from future oracle facts. Label mutation and
future-data mutation tests must leave onboarding context unchanged. Opaque
randomized resource, company, period and destination identifiers and shuffled
catalog order prevent identifier/position shortcuts. Similar titles appear on
relevant and irrelevant assets. Distractors have large movements but different
populations. Neither title nor source kind alone identifies the answer.

## Companies and held-out monitoring periods

| Company | Business request | Hard distinction | Irreducible period gap |
| --- | --- | --- | --- |
| Juniper Trail Retail | What sales do we actually keep? | Net versus gross, refunds, channel offsets | New refund timing undocumented |
| Harbor Workspace | Is retention getting worse? | Within-plan performance versus population mix | Eligibility version unavailable |
| Kindred Helpdesk | Are we letting customers down? | SLA numerator and all eligible tickets, not closed-only | Overdue-open denominator missing |
| Cinder Database Cloud | Is a slowdown customer-facing? | Joint latency, lag and regional breadth; rollout timing is association | Cluster coverage missing |
| Mosaic Exchange | Are fewer people buying? | Unique buyers versus overlapping audiences | Union export missing; overlap cannot be reconstructed |
| Lumen Freight Finance | Did collections fall? | Settled receipts versus authorizations/invoices | One bank partition 72 hours late |

Default holdout: six companies, each with a separate onboarding snapshot followed
by three scored periods: quiet, true event and data-quality/definition ambiguity.
Their chronological order is seed-randomized. There are **18 measured final
cases**, not 18 independent enterprises. Freeze an authored card and baseline
notes after onboarding; expose one monitoring snapshot at a time. Do not reveal
future snapshots or scorer feedback between periods. Both arms may retain their
own tool results and notes; record subsequent policy/card changes separately.

Development split: Cedar Meal Kits and Pine Courier, six development periods.
They have different business language and company identities but deliberately
reuse additive and rate mathematical families. This is modest transfer, not
unseen-method generalization. Different seeds randomize identifiers, ordering and
counts; repeated seeds do not constitute new analytical families or independent
trials. Effects are designed test conditions, not an estimate of incident
prevalence in real businesses.

The simulated clock is each episode's `period.as_of`. Inject that clock into
evaluation, or apply one common timestamp offset to **all** relevant timestamps.
Do not disable freshness or move stale source timestamps independently. Preserve
finance's 72-hour gap and normal freshness requirements. Record the clock policy.
The runner now uses one scenario-relative offset, preserving chronological spacing,
and injects the fixed period clock into engine freshness checks. Both prompts receive
that period ID and clock. Wall-clock time spent running other episodes cannot age a
snapshot. This tests repeated independent snapshots, not continuous operational time.

## Paired arms and fairness

- Baseline: the configured Luna model using raw company catalog, inspection and
  bounded query tools, owner clarification, and persistent notes/caching.
- Treatment: the same model, same source context, same tools and owner answers,
  plus production SignalWeave onboarding, draft/review/simulation/approval and
  repeated evaluation with **live Jev**. No heuristic Jev substitute counts.
- Both see identical public measurements in each period. An agent may calculate
  over returned rows; do not withhold denominator, decomposition method,
  standard calculation facilities or source metadata from the baseline to make
  the treatment win. Any additional calculation tool must be documented.
- `ask_owner` answers topic keys for metric scope, materiality, routing and data
  gaps. It does not supply a period's correct outcome, unseen measurements,
  reconstructed missing rows or an expert-authored card. Free-form questions may
  be mapped to topics, but use the same mapping for both arms and log it.
- The opening context already supplies metric scope in the glossary and the
  authorized destination identities labeled `Business owner` and `Data operations`.
  Do not require redundant scope or routing questions for correctness. Materiality
  lookup supplies the otherwise-unknown thresholds and when to use each destination;
  it is the only required owner topic. Routing lookup remains optional clarification.
  Unknown questions receive unknown, not invented business policy. Count questions
  and simulated owner effort separately.
- Same model identifier, generation parameters, context/tool budgets, retry
  policy and total opportunities. Record all setup and repeated-run calls for
  both arms. No secret notes, hidden correct card or oracle-selected sources.
- Record human approval distinctly. Do not report auto-approval by a harness as
  successful real-human review. Notifications are dry-run handoffs; nobody is
  paged and no operational action is executed.

Cached facts are reusable only under the same company, resource, definition and
snapshot. Cached metadata or plans may persist; stale measurements cannot pass as
new evidence. Runner-observed successful current-period source reads determine
provenance; a model's assertion that it inspected a source is not evidence.

## Structured submission and independent scoring

```json
{
  "outcome": "notify",
  "recipients": ["team-opaque"],
  "evidence_refs": ["company_mcp|resource-opaque"],
  "numeric_claims": [
    {"fact": "net_sales.delta", "value": -300, "unit": "USD",
     "evidence_refs": ["company_mcp|resource-opaque"]}
  ],
  "claims": [
    {"claim_type": "accounting_decomposition",
     "evidence_refs": ["company_mcp|resource-opaque"], "statement": "..."}
  ],
  "summary": "..."
}
```

The example is a schema illustration, not a fixture target. Claim types are
`observation`, `accounting_decomposition`, `association`, `hypothesis`, and
`causal`. These observational cases never support the last type. An operations
event needs an explicit association explanation, not a proven rollout cause.

The scorer reports exact **structured-field** correctness, outcome correctness,
recipient exactness, false alerts, missed events, unsafe suppression of missing
data, wrong destinations, required-evidence recall, actual-inspection provenance,
numerical precision/recall and unsupported typed claims. Incorrect, duplicate,
nonfinite or unprovenanced numerical assertions prevent an exact pass. Omitting
all required numerical explanation cannot earn full credit. Quality cases expect
abstention/data-owner repair, not fabricated current totals.

Numerical targets come from source-generating quantities, not a model or the
production solver. Net amounts use gross minus refunds; rate labels use an
independent four-standardized-total oracle averaging the two update orders.
Fixtures check these against explicit rational examples. Exact numbers are not
proof of the asserted completeness of a real dataset.

Scorer v2 corrects two defects found by independent review of development data:
required citations represent indispensable evidence, not a blanket quota of two
sources; a corroborating document is not mandatory when an inspected primary
source already supplies the definition or quality fact. Numerical availability is
per fact: an explicitly available, valid baseline can survive missing current
data, but current totals, deltas and decompositions cannot be reconstructed from
missing denominators. Public fact definitions and units clarify that a channel's
contribution means contribution to the **change**, not its current revenue level.
These rules apply to both arms. Original development scores are retained under
their original protocol/hash; no retrospective win is claimed. Exact citation
identities, current-measurement inspection, undefined scope and unavailable
quantities continue to fail. Catalog metadata alone does not qualify as an
inspected measurement source under this trial's contract.

**This scorer does not validate prose meaning.** A model could attach
`association` to text claiming a proven cause, or propose a destructive action in
its summary. The scorer deliberately flags every result
`narrative_review_required=true`; `exact=true` is never narrative safety. Before
any claim of correct actionable explanations, obtain a separate blind review of
all final narratives, with arm identity hidden. Review causality, unsupported
claims, misleading omissions and proposed actions against the same public
evidence. Publish reviewer disagreements and failures. Do not substitute an LLM
grader's opinion for the independent numerical score or call an internal agent
review external peer review. Until this review happens, narrative quality is
**unmeasured**.

## Preliminary acceptance and comparative endpoints

These are proposed small-pilot gates, to be frozen before the first measured
holdout run—not promised results:

1. All six treatment onboarding episodes produce a reviewable persisted draft,
   sourced metric/population rules, authorized routes and a reproducible preview;
   retain human approval and unresolvable-gap handling. Report each gap, not just
   a combined success count.
2. At least 17/18 exact structured cases; 6/6 true events identified; 6/6 quality
   cases handled without a business notification or a false all-clear; zero wrong
   recipients, unsupported causal claim types or harness/runtime failures. Report
   quiet false alerts separately. Narrative review is an additional required gate
   for any broader safety claim.
3. A treatment advantage requires quality and safety not to deteriorate. Report
   quality/cost/latency trade-offs even if no advantage exists. For an initial
   adoption signal, preregister either at least three additional exact cases at
   comparable measured total cost, or at least 20% lower measured total model
   cost with no fewer exact cases and no additional safety failures. These are
   engineering targets, not statistical proof with six companies.

Cost must include onboarding, clarification, review/previews, Luna calls, Jev
calls, retries and repeated execution. Report onboarding separately, per-period
marginal cost and cumulative cost over the three measured periods. Use actual
provider usage and dated prices; unknown prices remain unknown. Do not describe
a modeled 3-minute query or hypothetical amortized future savings as measured.
Give observed wall time separately from modeled warehouse latency, preserving
actual dependency order and concurrency. Both arms may cache and parallelize.

Report paired results per company and condition, not just a headline percentage.
The three periods within a company are correlated. Do not use 18 independent
Bernoulli observations to claim population certainty, invent a meaningful p95
from a tiny sample, or extrapolate four-source retrieval to thousands of charts.
With zero incidents among 18 cases, enterprise risk is still not zero. A good
result justifies a real-team shadow pilot; a tie or regression is a valid result.

## Freeze and reproduction requirements

Record `dataset_digest(build_scenarios(...))`, seed, split, repository revision,
scorer revision, clock policy, both arms' tool schemas/prompts, exact model IDs,
live-Jev confirmation, cache scope, clarification logs, call budget and stop
conditions. The runner's `source_fingerprint` must include content hashes for
the harness, scorer, prompts, production runtime files, and dependency lock;
the independent comparative reviewer fails closed when that fingerprint is
missing or differs from the current checkout. Historical inspection is an
explicit `--allow-historical` mode and is never current proof. Keep all attempts
and errors. Run only the two development companies
while tuning. The parent runner owns execution and telemetry; this module does
not execute a model, query engine, MCP server, notification or benchmark.

Offline fixture/scorer checks:

```sh
uv run pytest tests/test_bootstrap_scenarios.py
uv run ruff check evaluations/bootstrap_scenarios.py tests/test_bootstrap_scenarios.py
```

Passing those tests validates fixture boundaries and the scorer's behavior. It
does not show that onboarding, Jev, Luna or SignalWeave wins the live trial.

## Run the live development trial

Use private credentials through the environment or explicit local files. Never
put keys in command arguments or commit the dotenv file. Check configuration
before making paid calls:

```sh
uv run python -m evaluations.bootstrap_agent_trial --preflight \
  --openai-env /absolute/path/to/private.env \
  --jev-key-file /absolute/path/to/typesafe.key \
  --output artifacts/bootstrap-dev-01
```

Preflight checks credential presence, not whether either provider will accept
the key or whether the account can access Luna. Then run only development cases:

```sh
uv run python -m evaluations.bootstrap_agent_trial \
  --openai-env /absolute/path/to/private.env \
  --jev-key-file /absolute/path/to/typesafe.key \
  --split dev --limit 2 --max-api-requests 120 \
  --output artifacts/bootstrap-dev-01
```

The limit counts combined Luna and Jev attempts, including failures; it is not a
dollar spending cap. Existing output directories are never overwritten. Preserve
partial runs and their costs. A budget-censored run cannot support a comparative
claim. Review development traces and freeze the protocol, code, and an adequate
budget before selecting `--split holdout --limit 6`; do not tune on that run.

The runner exercises production SignalWeave MCP handlers and schemas with a
synthetic, in-process source adapter. It does not measure remote BI MCP transport,
warehouse query latency, or installation against a live company BI provider.
`trace.jsonl` records requests, usage, source reads, and tool results; `report.json`
separates cold setup, repeat monitoring, structured scores, and known token costs.
Narrative review remains a separate gate.

## Codex login transport (v2, before held-out execution)

Use the existing local Codex login instead of supplying an OpenAI API key:

```sh
uv run python -m evaluations.bootstrap_agent_trial --agent-transport codex \
  --jev-key-file /absolute/path/to/typesafe.key --split dev --limit 2 \
  --max-api-requests 70 --max-tool-calls 45 \
  --output artifacts/bootstrap-codex-dev
```

This is the same Luna model through `codex exec`, not the direct Responses API
agent loop. Each episode gets an ephemeral CLI session in an empty temporary
directory, saved notes, current-period context, and an exclusive loopback HTTP MCP.
The MCP exposes the same common functions to both arms and production SignalWeave
schemas/handlers to the treatment. Notifications remain disabled. Tool mutations
are serialized; first successful submission is latched; later mutations are rejected.
Only this synthetic server's tools are preapproved. Shell, web, plugins, other
MCPs, subagents, host skill discovery, project instructions and memory use/generation
are disabled. The tool execution host remains enabled because Codex requires it
for MCP calls. Credentials and private labels stay in the parent process; no OAuth
credentials are extracted or copied. The child receives only login/runtime environment
variables, not the Jev key. Record foreign-tool events as invalidating the run.

The owner is a scripted `ask_owner` tool, not a person waiting to answer chat.
Both agents are explicitly instructed to consult it. This is a trial mechanic,
not a product shortcut or a claim that onboarding succeeds without human context.
Both agents may reuse established policy notes and any already-provided fresh
evidence; neither is required to repeat onboarding questions or refetch a source
whose current snapshot is already available. Public destination URLs configure
delivery methods; final recipient submissions use the corresponding authorized
keys. Raw system routing is normalized through that same public mapping, not
through expected answers.

Codex controls its internal inference loop/retries. In this mode `--max-turns` and
`--max-output-tokens` do not apply; the actual bounds are 45 MCP calls and 360 seconds
per Codex process. This deadline excludes MCP startup/shutdown and pre-agent Jev
evaluation, whose own provider timeouts apply; full wall time includes all of them.
`--max-api-requests` caps **Jev requests only**. A CLI invocation is
not an API request. `codex_invocations`, token usage, Jev attempts and elapsed time
are reported separately. Missing terminal usage is unknown, never free. CLI/MCP
startup is included in wall time. A global budget stop makes the run ineligible
for comparative conclusions. Failed onboarding leaves all planned monitoring
periods in the denominator and marks safety unassessed rather than safe.

OpenAI dollar amounts are **illustrative API-equivalent token estimates**, not
measured ChatGPT subscription charges. The measured-dollar advantage gate above
cannot be established by this transport. Report tokens and wall time as resource
endpoints instead; do not retrofit a winning threshold after seeing results.
Jev usage/cost estimates remain separately identified. Preserve all development
failures and their resource use; exclude them from held-out estimates only with
that tuning cost disclosed. Freeze transport, protocol, production engine/MCP/Jev
files, fixture/scorer, dependency lock, CLI version, model, effort and budgets.
Holdout will use all six companies, 45 calls/360 seconds per episode and a global
210-request Jev emergency cap, with no per-case coaching or tuning after results.
