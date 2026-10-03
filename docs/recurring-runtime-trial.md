# Recurring investigations: prospective implementation trial

Status: bounded implementation and live completion checks pass; the broader
local-adoption goal is **not complete**. The transfer set has 12/12 correct
structured results and 12/12 reviewer-usable reports in both arms, after a
separately recorded completion of five missing SignalWeave runs. This is not a
clean prospective pass or a demonstrated advantage over Luna.

## What this tests

An agent reads a supplied business policy and inspected source definitions,
authors a native card, previews two setup periods, and freezes it. A synthetic
operator checks the numerical bindings against the setup policy and invokes the
production review/approval transition. This is **assisted onboarding with a
synthetic numerical reviewer**, not an autonomous substitute for human policy
approval. The reviewer never repairs a card silently.

After all setup attempts finish, each arm gets a persistent Luna session for four
author-unseen periods. Both arms receive the same authored context, source tools,
deterministic analyses and numerical checks. SignalWeave executes the approved
workflow with live Jev; Luna writes the final message. The baseline uses Luna
directly. A failed product approval does not prevent the independent baseline
from attempting the task with the original policy and returned draft, clearly
marked unapproved. Nothing is delivered externally.

Code computes the numbers. Jev interprets the bounded policy and context. The
new checks are not a Boolean rule engine, and there is no heuristic replacement
for Jev. Receipts are replayed through production MCP and must make no new source
or model calls.

## Initial prospective trial

Frozen runtime commit: `6c3c668`. Three new synthetic companies; two setup and
four holdout snapshots each. Complete
[manifest](evidence/recurring-runtime-live-01/manifest.json),
[results](evidence/recurring-runtime-live-01/report.json),
[authored artifacts](evidence/recurring-runtime-live-01/frozen-cards.json) and
[raw journal](evidence/recurring-runtime-live-01/events.jsonl.gz) are retained.

| Measure | Luna baseline | SignalWeave + Jev + Luna |
| --- | ---: | ---: |
| Intended recurring reports | 12 | 12 |
| Reports submitted | 12 | 4 |
| Correct status, outcome, routes, arithmetic and provenance | 11/12 | 4/12 |
| Strict score including authored numerical-policy checks | 7/12 | 4/12 |
| Correct outcome and recipients | 12/12 | 4/12 |
| Approved product cards | Shared setup | 1/3 |

The strict baseline score is not evidence that Luna made five wrong decisions.
It includes four failures of the incorrect numerical bindings in the shared,
unapproved Juniper draft, despite correct final business decisions. The remaining
baseline failure is Saffron's report status: it marked missing exception status
as blocked; the oracle expected a complete quantitative report with an
investigation outcome. Its outcome and recipients were correct. The original
strict scores are not rewritten.

Only Mosaic produced an approved card. Both arms passed its four recurring
cases, including incomplete coverage. SignalWeave's four exact receipt replays
made no additional calls. Whole-session time was 45.12 seconds for treatment
versus 47.20 seconds for baseline—about 4.4% lower in this one tiny paired sample,
not the predeclared 20% benefit threshold. Comparing total arm times when eight
treatment reports were never produced would be misleading.

The run used **18 Jev requests and seven Luna sessions**, including three setup
sessions. The original cap was 36 and nine; no failed authoring was rerun. API
usage is retained separately for setup and recurring work. Tokens are not a
dollar invoice or a measurement of human time saved.

### Failures and repairs

- Juniper's draft represented directional increases using `absolute=true`, even
  though its prose correctly excluded decreases. The synthetic review rejected
  it. The schema and onboarding guidance now explicitly distinguish signed
  changes in units from magnitude in either direction. This improves the
  authoring contract; it cannot guarantee semantic fidelity.
- Saffron could not create a card: generated route IDs collided when different
  outcomes shared the same recipient. The caller-owned bridge now derives
  default IDs from destination **and outcome**, preserving explicit-ID collision
  checks and the approved destination allowlist.
- An invalid evidence-requirements dictionary consumed a draft attempt. Native
  MCP and the caller bridge now expose the actual `watch:N` / `question:N` key
  grammar; slot-bound validation remains mandatory.

The approved numerical checks also fail closed when required evidence cannot be
computed, including unit mismatch. Optional semantic uncertainty is not relabeled
as a missing source. No confidence threshold was lowered and no failed source
gate was removed.

### Prose review failure

Two isolated Luna review sessions received arm-masked public evidence, not the
private labels or key. Both reread the six assigned cases and exhausted the
12-tool-call budget before submitting any reviews. This is an unsuccessful
review, **not adversarial approval**. Its
[report](evidence/recurring-runtime-live-01-prose-review/report.json) and
[journal](evidence/recurring-runtime-live-01-prose-review/events.jsonl.gz) remain
available. Billing usage was unavailable after termination; do not treat it as
zero cost. This reviewer helper was not committed before invocation; its prompt,
tool events and instruction digest are retained, but it lacks a clean committed
source freeze. The revised reviewer supplies cases in its prompt and only exposes
the submission tool; the next invocation will freeze that source first.

## Fresh transfer trial and execution-harness failure

The revised authoring schema was frozen at `b240c64` before testing Canyon
Freight, Helio Support and Lattice Energy. These are different numerical fixtures,
policies and thresholds using the same three supported mathematical shapes—not
proof of broad new analytical methods. Each company had a quiet and an actionable
setup period. Canyon also exposed a large negative change during setup; Lattice's
holdout contains an excluded segment with a large negative contribution.

**All three agent-authored cards passed the numerical-policy audit and production
approval.** The baseline submitted and strictly passed 12/12 reports. SignalWeave
submitted and strictly passed 7/12; five were missing when the Jev budget ran out.
Original [manifest](evidence/recurring-runtime-transfer-live-01/manifest.json),
[report](evidence/recurring-runtime-transfer-live-01/report.json), and
[journal](evidence/recurring-runtime-transfer-live-01/events.jsonl.gz) remain
unchanged. The trial used all 36 permitted Jev calls and nine Luna sessions.

This exposed a measurement bug in the evaluation harness. The public MCP approval
response intentionally omits the compiled execution plan. The harness copied that
response into separate arm stores, instead of copying the full approved card
already persisted in setup SQLite. Consequently, fresh periods recompiled a plan
unnecessarily. All three original setup databases still contain valid plans and
their execution payloads exactly match the public frozen cards.

The harness now restores the durable approved card and checks plan identity,
version and source binding. Offline full-runtime regression tests cover both sets
and require exactly three setup compiles, zero recurring compiles and exact receipt
replay. No production gate, numerical threshold or company policy was changed.

A separate completion-only protocol targeted only the five absent reports, with
the exact retained approved cards and source snapshots, at most five Jev calls
and two Luna sessions. Completed reports cannot be replaced. Its coverage is
post hoc execution repair; it cannot turn the original failed gate into a clean
prospective win or support an end-to-end latency comparison.

## Completion result and independent report review

The completion driver was frozen at `01d4914`. It recovered the original approved
cards, including their compiled plans, verified unchanged production source,
dependencies and source fixtures, and preserved the original failed trial. It
used **five Jev judgment calls, zero compile calls and two Luna sessions**. All
five missing reports passed; all intended treatment reports now have exact
receipt replay without another source or model call. The first, zero-paid-call
[preflight rejection](evidence/recurring-runtime-transfer-completion-preflight.json)
is retained separately.

| Combined transfer coverage | Luna baseline | SignalWeave + Jev + Luna |
| --- | ---: | ---: |
| Intended/submitted reports | 12/12 | 12/12 |
| Correct status, outcome, routes, numerical checks and provenance | 12/12 | 12/12 |
| Quiet periods correctly suppressed | 4/4 | 4/4 |
| Wrong recipients / false or missed notifications | 0 / 0 | 0 / 0 |
| Reports judged usable against supplied evidence | 12/12 | 12/12 |

These are proposed routes, not actual notifications. The treatment column mixes
seven original reports and five completion reports. Original failed episodes are
retained. See the [completion manifest](evidence/recurring-runtime-transfer-completion-live-01/manifest.json),
[report](evidence/recurring-runtime-transfer-completion-live-01/report.json),
[journal](evidence/recurring-runtime-transfer-completion-live-01/events.jsonl.gz),
and [checksums](evidence/recurring-runtime-transfer-completion-live-01/SHA256SUMS).
Its inherited `combined_coverage.episode_seconds` and tool counters are **not**
combined performance totals; completion episodes are recorded separately. Do not
compare those inherited counters with the baseline. The explicit
`latency_comparable: false` and `prospective_pass: false` remain authoritative.

Two isolated Luna review sessions, with arm labels masked and no access to the
private labels or decoding key, completed all 12 reviews. They reported no
unusable candidate and preferred the baseline artifact in six cases, with six
ties and no SignalWeave wins. Each case had one reviewer, not a consensus panel.
The reviewer code was committed and clean before invocation. Complete
[reviews](evidence/recurring-runtime-transfer-completion-prose-review/report.json),
[manifest](evidence/recurring-runtime-transfer-completion-prose-review/manifest.json)
and [journal](evidence/recurring-runtime-transfer-completion-prose-review/events.jsonl.gz)
are retained. This is internal AI review, not external peer review or a human
usability study.

The preferences do not isolate prose quality. Baseline submissions included full
analysis objects; treatment submissions included compact claims and omitted
numeric claims for blocked cases. Review reasons preferred the richer objects'
rate numerators/denominators, comparison/reconciliation fields, null totals and
limitations. Both agents had the same underlying source/analysis inputs, but
their final artifact representations differed. Thus this review supports
bounded usability, **not a fair conclusion that either writer is better**. A new
comparison must distinguish the human-facing narrative from equally projected
supporting evidence. Do not retroactively replace the recorded scores.

Completion usage was 508,419 Luna input tokens (447,744 reported cached), 3,686
output tokens, and 50,400 Jev input / 616 output tokens. The two final review
sessions used 139,087 Luna input tokens (90,880 reported cached) and 4,826 output
tokens. These are additional to the original trial and failed review costs, not
an efficiency claim or dollar invoice. The completion sessions took 86.96 and
48.59 seconds; their restarted contexts prevent a fair paired speed comparison.

Final adversarial code review found three additional evaluation defects: paired
scoring recorded but did not enforce identical card digests; completion preflight
required a durable receipt but did not compare its contents to the retained
report; and the independent scorer mishandled the recorded value of an absolute
negative segment contribution. These guards and regression tests were added
after the run. A [zero-inference revalidation](evidence/recurring-runtime-transfer-offline-revalidation.json)
confirmed identical cards/catalogs/analyses for all 12 pairs and exact structured
result bindings to all 12 local durable receipts. Current transfer cards use
signed checks, so the absolute-value scorer defect did not alter their scores.
Original artifacts remain unchanged. Review keys are published for auditability
after isolated review; public readers are not blinded.

Verification: the full offline suite passed **1,970 tests**, with three opt-in
checks skipped. The final digest-guard and scorer follow-up was additionally
checked in the focused completion/trial suite. Ruff and `git diff --check` pass.
Two internal Luna code/method reviewers inspected the work; concrete integrity
findings above were repaired. Their acceptance is bounded to archiving this
evidence and these contracts, not endorsement of enterprise readiness or a
comparative product win.

### What is implemented, and what remains

- Approved numerical checks are computed from source-bound validated analyses;
  Jev selects bounded semantic outcomes rather than doing threshold arithmetic.
- Required uncomputable checks fail closed. Semantic uncertainty remains distinct
  from a missing or broken source in the evidence handoff.
- Agent authoring now exposes evidence-slot grammar, signed-versus-magnitude
  semantics, and collision-free default route IDs for shared recipients.
- Stored compiled plans survive the trial's arm-store transfer; recurring runs
  no longer pay for avoidable recompilation.
- The local rc2 native binary passes install/setup/MCP/live-evaluation and
  separate-process replay checks ([evidence](evidence/local-rc2-binary-check.json)).
  This is local macOS evidence. Public installation still points to rc1; rc2 has
  not been published, and other release targets were not certified by this check.

Still unproved: a clean fresh prospective run of the corrected end-to-end path,
comparative reporting or operating-cost benefit, real-human onboarding, and a
real team's deployment. The next evaluation should freeze equal evidence
projections before inference, then measure the final messages separately from
audit-bundle detail. Do not add new abstractions or keep rerunning known cases
until a favorable score appears.

## Acceptance and limits

The [goal document](local-adoption-goal.md) fixes the success criteria: all
intended results and replay checks, faithful final prose, then either a 20%
whole-report latency improvement or three masked quality wins with no losses.
Otherwise report failure or parity, not a product advantage.

These are small, sparse synthetic comparison snapshots with already normalized
typed exports and explicit owner policy. They do not test arbitrary connector
normalization, retrieval over thousands of assets, expensive warehouse queries,
continuous month-long operations, statistical or causal discovery, real human
onboarding, or customer adoption. Internal AI review is not external peer review.
