# Bootstrap benchmark v3: evaluator repairs and proposed fresh-seed replay

Status: two development regressions completed; see the
[repair ledger](bootstrap-repair-ledger.md), which retains adverse findings and
costs. The next fresh-seed run will use the implementation commit and content
hashes recorded in `artifacts/bootstrap-codex-holdout-v3-01/config.json`, with
seed `20261002`, all six companies, 45 calls per agent episode, and 210 global
Jev attempts. No monitored outputs from that seed have been inspected to choose
this configuration. The criteria below remain unchanged. Do not edit the
implementation, prompts, fixtures, scorer or this protocol during the run.

Development now reaches both-agent 3/3 final structured correctness on retail,
but native SignalWeave routing remains 1/3, requiring agent correction, and total
agent tokens are higher. The fresh trial is not a declaration of expected
success. Report native decisions and agent overrides separately; a successful
combined-agent answer must not be presented as proof of autonomous Jev routing.

## Preserve the failed v2 result

The [October 1 report](codex-bootstrap-trial-2026-10-01.md),
[v2 protocol](bootstrap-benchmark-protocol.md), checked-in evidence under
`docs/evidence/bootstrap-codex-holdout-v2-01/`, and original local artifacts under
`artifacts/bootstrap-codex-holdout-v2-01/` remain unchanged. V2 remains baseline
8/18 exact structured submissions and treatment 0/6 completed onboarding,
with all 18 treatment monitoring periods blocked. Evaluator repairs do not
explain away those setup failures. No adjusted v2 headline is asserted here.

V2 was frozen at `8eb70f3de81a1085cad596cf57692a8e80488c47`, with full fixture digest
`5cced07c836ccb320a75c8f438079b480665b65ca8c7291c655edc4b803daacf`.
Reproduction of its scoring or evidence export requires that frozen evaluator;
the current v3 fixture digest intentionally differs. Do not regenerate or
overwrite old reports with the new evaluator. Any later offline v3 rescore of
old submissions must be separately named regression analysis, retain the old
scores alongside it, and cannot supply a fresh comparative performance claim.

The original holdout seed, `20261001`, is now a regression set: its cases and
failure modes informed these repairs. Development cases remain available for
engineering. The next execution sequence is a cheap debug regression first,
using old seed `20261001`, `split="holdout"`, `limit=1`; retain that attempt and
its costs separately. Fix issues from regression, then freeze the implementation
before running all six companies on fresh seed `20261002`. This worker does not
execute either live run. A new seed changes identifiers, order and counts in the same six
enterprise kinds; it does not create new analytical families or independent
enterprises.

## Scorer v3 rules

`SCORER_VERSION` becomes 3; `SCHEMA_VERSION` stays 1. RNG initialization, random
draws, assets, titles, distractors, source measurements, clocks, condition order,
owner answers, destinations and outcome labels are unchanged. Frozen digest
regressions cover the original raw public fixtures at seeds `20261001` and `42`.
The only public-context change is the static finance validity policy in numeric
definitions, which is available identically to both arms from onboarding.

The buyer union export retains an optional valid historical baseline when its
current union is missing. Accepted values come from the exported baseline under
`customer_id` / `count_distinct` scope, with a finite, nonnegative integer count.
`missing_union_export` describes the unavailable current union in this fixture.
No current total or delta is inferred from the baseline, audience counts, or
latent generating values. Omitting the baseline remains valid abstention; a
wrong baseline, including an invented zero, still fails.

Finance uses a deliberately conservative, explicit rule. Its public bank-control
export is the only closure attestation. All expected partitions must be closed
and the watermark must reach the reporting cutoff (`period.as_of`). In this
point-in-time fixture a future watermark is invalid too. Both the receipts and
control export must be inspected and cited for canonical numerical claims.
There is no independently attested historical close or immutable-baseline
guarantee in the source schema. Consequently the stale/partial export validates
neither baseline, current collections nor delta, even if its printed baseline
equals a latent generating total. A historical interval is not itself proof of
historical completeness. Closure and cutoff validity are evaluated from public
control fields, not from the hidden `quality` condition. The original 72-hour
source lag remains intact; normal runtime freshness checks remain necessary.

This policy does not claim that a historical amount is necessarily wrong. It
means that its canonical validity is unestablished by the available evidence.
An independently attested historical close would justify a different rule in a
future dataset version, but none is added here. If current amounts are absent
while the control is valid, an exported finite baseline can still be accepted;
no missing value is reconstructed. Partial/exported amounts may be described
as such in a reviewed narrative, but cannot be submitted under canonical keys.

The numerical vocabulary, units, tolerances, required numerical explanations,
exact destinations, owner-policy lookup and causal restrictions remain binding.
Aliases, appended values in keys, partial canonical metrics and unknown encoded
as zero get no credit. Finance numerical citations now include its indispensable
bank control. A repeated fact is flagged even when an earlier occurrence was
wrong; it cannot be repaired by appending a contradictory duplicate. An
unlisted numeric citation receives no numeric credit as well as failing exact
provenance. These are explicit contract tightenings, not score relaxations.

## Separate diagnostics, one strict exact result

`unsupported_numeric_facts` remains the compatibility list of failed assertions.
`numeric_precision` still measures fully supported structured numerical claims,
not arithmetic accuracy in isolation. V3 also returns:

| Field / reason | Meaning |
| --- | --- |
| `numeric_diagnostics` | Claim index, exact submitted fact key and all applicable failure reasons. |
| `unknown_identifier` | Key is absent from the static public vocabulary; no alias matching. |
| `unavailable_scope` | Recognized key has no validated target for this period's evidence. |
| `wrong_value` | Available target exists and a finite number is outside its unchanged tolerance. |
| `wrong_unit` | Available target exists but the submitted unit differs. |
| `nonfinite_value` | NaN, infinity or a number unrepresentable by the numerical checks. |
| `duplicate_fact` | A prior assertion used the same exact key, whether correct or incorrect. |
| `invalid_citations` | Numerical dependencies or citation provenance are invalid. |
| `missing_numeric_facts` | Required targets without a credited assertion. |
| `citation_diagnostics` | Citation location and separate unknown, uninspected, unlisted, and missing-required reference lists. |

Citation diagnostics cover top-level evidence, numerical assertions, and typed
narrative claims. Unknown references are distinct from known but uninspected
resources. Multiple defects can apply to one claim, so diagnostic counts are
not mutually exclusive case counts. Unavailable quantities are not classified
as wrong arithmetic by comparing them with a hidden value. Invalid schemas
remain invalid, nonexact and safety-unassessed; diagnostics are not a substitute
for schema validation.

Typed causal claims still fail in every company and condition. The scorer
continues to set `narrative_review_required=true` and checks structured fields
only. It cannot detect a causal overclaim disguised as an `association` or
hidden in the summary. Exact structured scoring must never earn narrative or
safety credit by itself. Blind review must assess causal language, unsupported
totals, misleading scope/completeness claims and proposed actions before any
claim about correct actionable explanations. Unreviewed narratives remain
unassessed; reviewers' disagreements and adverse findings must be retained.

## Predeclared fresh-seed replay

Use one proposed fresh seed, **`20261002`**, `split="holdout"`, all six companies,
with their existing four assets and three monitoring conditions. This seed is
declared without generating or screening its results during these repairs.
Do not search seeds, alter RNG/assets, select favorable companies or discard
failed setups. There are 48 scheduled episode records: two arms times six
companies times one setup plus three monitoring periods. Monitoring has 18
paired cases, clustered within six companies. Keep blocked and failed episodes
in those denominators with unavailable monitoring safety marked unassessed.

Use the runner's existing `config.json`, report and `trace.jsonl` as the freeze
record; no new manifest schema is required. Configuration records seed/split,
the full fixture digest, source revision/content fingerprints, model/effort,
budgets, CLI version and clock policy. The main agent's runner changes add the
public-context digest and include this v3 document and production onboarding/
models in source fingerprints. Tool schemas, prompts, calls and resource reads
are already retained in traces. Preserve requested model and observed resolution
where available; unavailable resolution remains unknown. Validate the production
approval repairs separately before the fresh run. This evaluator change does
not implement or certify those repairs. A changed implementation or protocol
after fresh-seed results requires a new version, retained attempt and fresh
preregistration.

Use the same requested `gpt-5.6-luna`, low reasoning effort and Codex transport
for both arms; record observed resolution and abort comparison on asymmetric
availability. Use the same 45 MCP-call and 360-second per-agent episode bounds
as v2 and the same 210-request global Jev emergency ceiling. The ceiling bounds
treatment provider attempts; it is not a dollar budget or a matched number of
Codex inference requests. All retries and failures count. Budget-censored runs
cannot establish comparative benefit. Do not top up an exhausted run after
seeing results or give a failed arm an uncounted retry. Pre-agent Jev work and
transport startup remain included in full wall time even though the Codex
process deadline does not cover them.

Use the existing seeded runner scheduling: companies run in fixed spec order;
`random.Random(seed)` shuffles each company's initial arm order, then that order
is reversed for each chronological episode, including onboarding. Execute both
arms for the current episode before advancing to the next period. States remain
isolated. Start with empty notes and no persisted cards
for each company/arm; do not carry v2 traces, answers or artifacts into replay.
No scorer feedback or future measurements reach either arm
between periods. Freeze cards and baseline policy notes after onboarding;
record any later changes and their costs as deviations rather than silently
rewriting the initial setup. Both arms may retain permitted evidence and notes.

The common opening context, numerical definitions, destinations, owner policies,
source catalog, inspection/query tools, arithmetic facilities and each period's
source snapshots must be identical. Verify equality before dispatch. Both arms
get the same exact public fact vocabulary and schema guidance: the runner exposes
the numeric-fact enum equally in `common_tools` and validates it in `call`.
Do not offer one arm a secret correction or a specially repaired submission. Treatment alone
adds normal production SignalWeave tools, persisted cards and live Jev. No
expert-authored card, oracle-selected source, hidden policy note or heuristic
replacement for live Jev is allowed. Approval remains explicitly recorded as
scripted owner review, not real-human review. Delivery is disabled.

Apply one scenario-relative clock offset to every relevant timestamp and inject
the same period clock in both arms; preserve staleness and spacing. Cache only
under matching company/resource/definition/snapshot. Metadata and plans may
persist, but old measurements cannot supply current-period inspection evidence.
Exclude fixture code, repository access, private labels, future snapshots and
scorer output from agent tools/context. `public_scenario` is a tool-server export
containing future periods, not an agent input; use `public_episode` and
`agent_context`. The scorer runs after submissions are sealed. Hashes and private
labels belong in evaluation records, not the model prompt.

## Endpoints and complete resource accounting

Keep the v2 engineering quality gates: 6/6 reviewable, persisted treatment setups;
at least 17/18 exact structured monitoring cases; all six event routes and six
quality cases correctly handled; zero wrong recipients, typed causal claims or
harness/runtime failures. Report quiet false alerts separately and require the
blind narrative review for broader explanation/safety claims. Report each
company/condition pair and setup failures before aggregate scores. New diagnosis
fields explain failures without changing the exact denominator. These gates are
engineering targets, not statistical evidence about enterprise deployment risk.

For this Codex replay, predeclare a descriptive resource endpoint: a candidate
efficiency signal needs no fewer exact cases, no extra safety failures, all
quality gates met, and at least 20% fewer total recorded agent tokens across
setup plus all three periods. Total means aggregate `input_tokens + output_tokens`
over all recorded invocations, including retries and failed attempts. Cached
input is included within input tokens, not subtracted as free or added twice;
report its subset separately when available. Report Jev tokens/requests/cost alongside agent
tokens; fewer agent tokens alone is not an overall cost win. Missing token
usage makes this endpoint unassessable. Report timing and token trade-offs even
when no threshold is met. Do not pick between tokens, latency, model dollars
or a favorable subset after seeing results. This endpoint cannot establish
measured-dollar savings through a subscription transport.

For each arm record onboarding, owner clarification, catalog/search/inspect/query
calls, bytes or rows returned when available, source errors and retries, cache
hits versus actual source reads, and monitoring separately. Count reads performed
inside SignalWeave as well as direct agent reads. Count card discovery, drafting,
edits, ambiguity resolution, review, simulations, approval, repeated evaluation,
and all Jev attempts; baseline note maintenance and review work count too. Shared
source results can be reused under the same cache policy; do not count a cache
hit as a new warehouse read or hide internal reads behind one card invocation.

Report measured wall time with dependency/concurrency order, Codex invocations,
token usage and missing usage, Jev provider requests/tokens and known costs, plus
simulated owner questions/effort. Include unsuccessful setup, retries, and
development/regression tuning costs in a separate retained ledger. Summarize
setup cost, marginal monitoring cost and cumulative setup-plus-three-period cost;
do not assume arbitrary future amortization to create a win.

Synthetic in-process source tools do not measure warehouse latency or billing.
Source cost is unknown unless actually instrumented and priced; zero billed
synthetic reads is not evidence that sources are free. Any separately modeled
source/card or owner cost schedule must be declared in retained configuration before the
run and displayed as a sensitivity analysis, never measured savings. Use dated
provider rates for known usage; Codex API-equivalent dollars are illustrative,
not subscription bills. Use existing resource-read and tool-call traces for
source/internal-card accounting and existing common-context checks; disclose
unobserved resource costs instead of treating them as zero. This patch adds no
telemetry to the runner.

Fresh-seed success would support a further shadow pilot. It would not establish
new-enterprise generalization, large-catalog retrieval, real-human usability,
continuous production operation, causal inference or universal safety. A tie,
regression, exhausted budget or unavailable resource endpoint is a valid outcome.

## Offline checks

Run `make verify` and `git diff --check`. The focused evaluator suite covers
visible buyer baselines, malformed/missing values, finance cutoff/closure
validity, numerical/citation diagnostic separation, duplicate contradictions,
unsupported canonical zeroes across families, typed causal restrictions, static
public policy/no-oracle isolation, and raw-fixture digest preservation. Runner
and review-packet tests exercise shared-context and export compatibility without
live model calls. These checks establish evaluator contracts, not live model
quality or a comparative performance result.
