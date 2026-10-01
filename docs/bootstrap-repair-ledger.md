# Bootstrap repair ledger — October 1, 2026

These are development regressions, not fresh holdout results or proof of an
enterprise advantage. The failed [v2 trial](codex-bootstrap-trial-2026-10-01.md)
is preserved. Each live attempt starts from empty notes/cards, uses the same
public context for both arms, and retains failures and usage. Synthetic owner
approval is not actual human usability testing.

## Regression v3-01

Frozen implementation: `6266b96`. Old holdout seed `20261001`, first company
(Juniper Trail Retail), one onboarding plus three chronological monitoring
periods per arm. Live Jev resolved to `jev-1.13.0`; both arms used the Codex
transport with `gpt-5.6-luna`, low reasoning. Eight invocations completed;
12 Jev requests, no missing token usage. This was the predeclared cheap debug
step, not the fresh-seed experiment.

| Endpoint | Luna + source tools | Luna + SignalWeave/live Jev |
| --- | ---: | ---: |
| Onboarding completed | 1/1 | 1/1 |
| Exact structured monitoring | 3/3 | 1/3 |
| Final outcome and recipients | 3/3 | 3/3 |
| Native SignalWeave outcome and recipients | — | 1/3 |
| Agent overrides of native outcome | — | 2/3 |
| Onboarding time | 22.60 s | 57.74 s |
| Monitoring total time | 91.95 s | 83.05 s |
| Source reads, including setup | 11 | 15 |
| Illustrative token-price estimate | $0.02408 | $0.04989 |

These estimates are not measured subscription charges. Slightly faster monitoring
does not offset worse exact correctness, higher setup time, or higher estimated
resource cost. No efficiency win is established. [Internal narrative review](evidence/bootstrap-codex-regression-v3-01/reviews.md)
found four supported outputs, one qualified output, and one unsupported output.

The source-selection confirmation repaired the approval dead end on this case.
It did not repair the full product:

- The adapter excluded `insufficient_data` from Jev's outcome choices, even though
  the owner explicitly requested it. Jev returned ignore on a semantic data gap;
  the agent corrected the route but still published unsupported canonical values.
- The agent copied an inapplicable mix/within-rate reporting requirement into
  required watch conditions. The evidence-completeness gate correctly blocked
  an otherwise actionable notification. The agent later overrode the outcome.
- The quiet-period answer reported 7,000 instead of 10,000. Outcome correctness
  did not imply numerical correctness.
- Repeat evaluations returned authoring history and duplicated the result inside
  the receipt. This inflated context without adding current evidence.

Repairs under test: include the missing semantic abstention option, explain
required watch-condition semantics during onboarding, and compact MCP evaluation
responses while preserving complete evidence and durable audit records. We do
not disable completeness gates or patch these companies' values into production.

[Configuration, usage, submissions and scores](evidence/bootstrap-codex-regression-v3-01/results.json)
and [blind review packet](evidence/bootstrap-codex-regression-v3-01/blind-review.json)
are retained. Full traces remain in `artifacts/bootstrap-codex-regression-v3-01/`.
The [v3 protocol](bootstrap-benchmark-v3.md) reserves seed `20261002` for a fresh
six-company run only after regression repairs and implementation freeze.

## Regression v3-02

Frozen production implementation: `158f413` (the subsequent `d0bd06c` adds tests
only). Same regression dataset and per-agent limits, separate empty state and
retained attempt. Both arms completed setup and all three monitoring cases.
Both achieved **3/3 exact structured submissions**. This small development result
does not establish a general improvement; the second run also has agent variance.

| Endpoint | Luna + source tools | Luna + SignalWeave/live Jev |
| --- | ---: | ---: |
| Native SignalWeave correct outcomes/routes | — | 1/3 |
| Agent corrections of native outcome | — | 2/3 |
| Onboarding time | 40.03 s | 73.36 s |
| Monitoring total time | 83.96 s | 67.83 s |
| Source reads, including setup | 10 | 10 |
| Agent input + output tokens, including setup | 265,449 | 822,302 |
| Agent input + output tokens, monitoring only | 169,399 | 207,107 |
| Illustrative token-price estimate, including setup | $0.02577 | $0.04592 |

Fourteen live Jev requests resolved to `jev-1.13.0`, with complete recorded usage.
Jev's estimate is included in the treatment estimate. Subscription billing is
not measured. Monitoring was 19.2% faster in total, but it used more agent tokens;
different cache shares affect illustrative pricing. The full resource endpoint
is not met. Do not advertise the timing observation without these qualifications.

Jev selected `insufficient_data` for the semantic gap with support 0.55; the
unchanged 0.70 policy sent it to investigation. The agent corrected that route.
For the event, Jev selected notify with support 0.82, but an unresolved required
watch condition blocked delivery. The agent's card still contained a conditional
regional-decomposition request despite no regional evidence. These native results
remain failures of the intended automated routing, even though the agent's final
answers pass the structured scorer.

The agent also passed an invalid context object during setup, recovered on retry,
and performed redundant approval checks. Tool responses repeatedly included the
same authoring review/history. Follow-up repairs expose the existing context
schema and remove duplicate authoring response fields while retaining the latest
review and plan at top level and full audit access through `get_insight_card`.
No confidence threshold or evidence-completeness gate is relaxed.

[Configuration, usage and submissions](evidence/bootstrap-codex-regression-v3-02/results.json)
and [blind review packet](evidence/bootstrap-codex-regression-v3-02/blind-review.json)
are retained. [Internal narrative review](evidence/bootstrap-codex-regression-v3-02/reviews.md)
independently checked all six final outputs against the public evidence and found
them supported, with minor wording notes. This review is imperfectly blinded and
is not external peer review. It does not validate the native decisions or establish
comparative benefit. These two
regression attempts together consumed 16 Codex invocations and 26 Jev requests;
neither is folded into a future fresh holdout or omitted from development effort.

## Fresh six-company holdout and subsequent repairs

The [frozen six-company v3-01 run](bootstrap-codex-holdout-v3-01.md) completed
at `8dde234`. Both arms onboarded 6/6 companies. Final exact answers were 15/18
for Luna/source tools versus 11/18 for Luna/SignalWeave/live Jev; final routing
was 18/18 versus 16/18. Native SignalWeave had both the right outcome and route
in only 9/18 cases. The report retains all costs and the two blind reviews.
This is failed acceptance, not a new success claim.

Post-run engineering separates required semantic evidence from advisory detail,
removes the accidental dependency on follow-up prose, rebuilds cached evidence
slots, and invalidates legacy certification for the changed admission policy.
The [adversarial admission review](evidence-admission-review.md) records the
test-first failures and a cache inconsistency found and repaired during review.
Offline passing tests isolate these contracts; they do not establish improved
live semantic performance or cure agent-authored routing mistakes.

The new window-capability declaration is absent from the measured v3 fixtures.
Their full fresh-holdout digest and older raw-data digests remain unchanged;
fixture serialization explicitly omits the newly added empty model default.
No capability was retroactively supplied to either arm. A later enriched fixture
needs its own recorded public contract and run, not revised old scores.

Ordinary `get_insight_card` reads now retain active policy, compiled plan and
latest review while omitting historical reviews/corrections. Explicit
`include_history=true` returns the unchanged full audit. Applied as a serialization
projection to the retained 19 card reads, that would reduce JSON from 370,164 to
205,078 characters. This is a retrospective payload-size calculation, not a
measured token, latency or cost improvement.

### Next bounded execution regression (declared before running)

After offline review and an implementation freeze, run the existing
`evaluations.local_investigation_trial` once into a new exclusive artifact directory.
Keep its six cases and expected outcomes unchanged: offsetting segments, hidden
movement under a flat total, Simpson reversal, mix-only movement, unchanged data,
and incomplete population. The caller uses an already-reviewed card, real
read-only SQLite queries through stdio MCP, live Jev with no retry fallback,
and persisted local receipts. Retain every outcome and replay check.

This cheap check validates post-approval execution after the admission changes.
It is not a fresh bootstrap comparison, six new companies, longitudinal evidence,
or proof that the failed comparative gates are now met. No second large agent
trial is warranted merely because these code contracts pass.

Pre-live freeze verification: `make verify` passed Ruff and **1,382 tests**, with
3 opt-in tests skipped (91.89 seconds). Whitespace checks passed. This includes
the new admission/migration/window contracts and unchanged fixture-digest checks.

### Post-approval execution result

Frozen implementation `3387916154e8fb98f4dd981249d816e598b4a7b3`: the declared
six-case live regression passed every recorded check. Four movement cases
returned notify, unchanged returned ignore, and incomplete population returned
insufficient_data with unknown watch evidence and a blocked evidence plan.
All six saved-receipt replays added zero Jev calls. Twelve live Jev requests
consumed 48,068 input and 1,780 output tokens; summed case execution was 5.59
seconds, excluding separate source preflight reads. No LLM-agent comparison or
external notification was performed. The harness's noncausal check verifies the
typed analysis method, not an independently reviewed causal narrative.

[Retained results, analyses and telemetry](evidence/local-investigation-admission-v1-01.json)
omit only local absolute artifact paths. Original local report SHA-256:
`97774d413575fb7c256fc35d61543615e5857af813334419ba157199f9bf3a29`.
This confirms bounded execution still works; it does not repair the failed
novice-bootstrap headline by substitution.

### Targeted bootstrap regression v3-03 (declared before running)

Run only the two previously failed operational-route companies from seed
`20261002`, holdout fixture split: Kindred Helpdesk
(`company-4468fde576db47408a2e`) and Cinder Database Cloud
(`company-9e23313593edcc9dbcae`). This seed and both failures are already known:
the run is retrospective development, not a fresh holdout or a representative
subset chosen to estimate success. Keep the raw v3 dataset unchanged and its
undeclared window capabilities visible. Do not inject a repaired source
descriptor, expert card, owner answer, expected outcome, or corrected mapping.

Use Codex Luna at low effort and live Jev, empty per-arm state, both arms and all
three periods: 16 scheduled episodes. Retain failures, retries, source reads,
timings, native routes and agent overrides. Bounds: 45 tools and 360 seconds per
agent episode, 60 global Jev attempts, no post-exhaustion top-up. Save a separate
exclusive `artifacts/bootstrap-codex-regression-v3-03` directory with recorded
implementation fingerprints. Freeze code, schemas and this declaration before
execution; do not inspect intermediate scores or patch an active run.

The narrow question is whether reviewed API/contract repairs reduce these two
observed onboarding failures in actual agent behavior. Check persisted window
and comparison identifiers and fidelity to owner routing, not just completion.
Report all six monitoring cases and both comparators, even if a previous failure
recurs or a new one appears. The overall enterprise/value goal remains open.

Pre-run review found no selection/exporter blockers; 203 targeted offline tests
passed, including old-config reconstruction and frozen dataset checks. Both
failure cases were selected explicitly before dispatch, not filtered after scoring.
Native build [36891227344](https://github.com/waddle-zoo/signal-weave/actions/runs/36891227344)
passed macOS Intel, macOS ARM64 and Linux x64 for the production repair commit;
the publication job was skipped. These are feature-branch artifacts, not a new
release or a main merge.

### Targeted regression v3-03 result

The declared run completed at `7f2d73b`: both setups and all six monitoring
episodes per arm, 29 live Jev attempts, no provider failure or budget censoring.
Final routing was 6/6 for both arms; native treatment routing was jointly 3/6.
Frozen exact results were baseline 5/6, treatment 4/6. Treatment monitoring took
150.19 versus 163.16 seconds but used 523,974 versus 331,419 agent tokens;
including setup, treatment used 1,470,835 versus 476,999. No cost/value win.

[Full result and failure analysis](bootstrap-codex-regression-v3-03.md) retains
the independent blind review's disagreement with strict scoring. Missing public
requirements are a benchmark defect, not permission to rewrite old results.
Persisted card prose/route disagreement, recurring setup questions, and mandatory
ambiguous watch items remain onboarding defects. The enterprise goal stays open.

### Three-way watch evidence repair and bounded live plan

Post-run inspection found a binary watch question whose false option explicitly
combined absence and insufficient evidence. It could not distinguish those two
meanings in code. Sixteen corrected test fixtures failed at the real SDK question
construction boundary before the repair. Watch judgments now use a single
present/absent/unknown Choice in the existing batched call, preserving the full
distribution and unchanged 0.70 item threshold. Unknown required evidence still
blocks automatic notify/escalate; optional unknown remains visible.

Adversarial review reproduced two additional failures (2 failed, 18 controls
passed): a loose distribution tolerance accepted sum 1.019, and a context fact's
slot tag fulfilled an unknown semantic slot. Both were fixed: distribution sums
must match 1 within 1e-6, and context tags retain provenance but do not override
watch/question judgments. Policy version 2 requires new certification; older
reports are retained, not upgraded. These are code-contract proofs, not live
accuracy claims or solutions to arbitrary topic-only watch definitions.

After offline verification and review, freeze this repair and run
`evaluations.watch_evidence_trial` once, in an exclusive output directory.
Twelve synthetic cases: commerce approvals, deployment maintenance windows, and
renewal ownership; each has affirmative, negative, missing, and conflicting
evidence. Sources remain healthy so missing meaning cannot hide behind a source
error. Expectations stay outside inference state. Use the actual engine and
live Jev with a hard twelve-attempt ceiling, no retry, no external delivery,
no threshold changes, and retain every request shape, result and provider error.
This is a development regression of evidence semantics, not a bootstrap trial,
LLM comparison, connector proof, scalability test, or enterprise acceptance.

Pre-live verification: full `make verify` passed 1,412 tests with 3 opt-in skips
(92.57 seconds), Ruff and whitespace checks passed. A subsequent harness-only
interruption test also passed; it proves that an otherwise-green 1/12 partial
report remains `running` and `passed=false`. The independent reviewer closed
all identified blockers after 149 focused offline tests. Existing offline Preset
transport doubles were updated to return normalized distributions; evidence-plan
positive fixtures now supply explicit supported judgments instead of depending
on a context-tag bypass. Their expected decisions were not relaxed. Historical
live evidence remains unchanged and does not certify this policy version.

### Live three-way watch result

Frozen `d1ab074`: all 12 declared cases passed watch-state, outcome, exact route,
distribution-retention and single-request checks. All six missing/conflicting
cases remained unknown/incomplete and routed insufficient_data, not absence or
business notification. Three affirmative cases notified and three supported
negative cases ignored. Twelve successful live `jev-1.13.0` requests, no retries,
31,542 input and 1,119 output tokens, 2.54 seconds summed execution.
[Full requests, results and hashes](evidence/watch-evidence-v2-01.json) are retained.
This proves the bounded semantic cases, not arbitrary topic interpretation,
bootstrap quality, long-document robustness or benefit over an LLM baseline.

Before further code changes, repeat the unchanged six-case
`evaluations.local_investigation_trial` into a new
`artifacts/local-investigation-admission-v2-01` directory. This checks whether the
new watch semantics preserve real SQLite/MCP arithmetic and replay behavior
across additive, rate, mix, stable and incomplete evidence. It remains a
post-approval regression with an existing reviewed card, not a bootstrap win.
The harness performs at most two Jev requests per case with retries disabled;
save all outcomes without a success-only rerun.

That unchanged regression passed all six cases at frozen `b7f6438` (production
`d1ab074`): correct numerical decompositions, outcomes, incomplete-population
abstention and receipt replay, with zero additional Jev calls on all six replays.
Twelve live requests consumed 48,535 input and 1,901 output tokens; summed case
execution was 5.34 seconds, excluding separate source preflight. The harness did
not record the resolved model version. [Complete retained checks/analyses](evidence/local-investigation-admission-v2-01.json)
omit only local absolute artifact paths. Original report SHA-256:
`e26bbb607ffe8e89b26f679c4fb12bb6baf141453100b05ffd17c9a14f555f41`.

### Authoring clarification and targeted bootstrap regression v3-04

The v3-03 persisted cards mixed one-time owner questions with recurring evidence
checks and left investigation routing in prose without its executable mapping.
The next small repair exposes those distinctions in all three authoring MCP
schemas and the card schema, using the same free-form arrays and existing
100-item limits. It adds no mandatory form, inferred route, semantic rewrite,
waiver, model call or approval bypass. Tests first showed 3 schema failures and
3 unchanged-value controls passing; all six pass after the clarification.

After full verification and independent review, freeze and rerun the same two
known-failure companies/seed, all periods and both arms, into exclusive
`artifacts/bootstrap-codex-regression-v3-04`. Keep v3 labels, raw fixtures,
45-tool/360-second limits, Luna low effort and 60 total live Jev attempts.
No field/default/context enrichment is injected into fixtures and no expert
cards are supplied. Retain complete outputs, costs, native outcome AND recipient
correctness, final corrections and uncertainty. Inspect no intermediate scores
and make no changes while the run is active.

This is a development rerun of the combined watch repair and authoring guidance,
not a fresh confirmatory dataset or isolation of either change. Compare stored
questions, conditions and routes with owner instructions, not just a successful
approval transition. Preserve frozen scoring disagreements from v3-03 rather
than treating its ambiguous explanation requirements as new public instructions.
No success threshold is lowered and no repeat is scheduled merely to obtain a
more flattering stochastic result.

Pre-run verification passed 1,419 tests with 3 opt-in skips (92.94 seconds),
Ruff and whitespace checks. The independent reviewer found no runtime/protocol
blocker and checked six focused schema/preservation cases. One wording correction
clarified that empty delivery methods mean no configured routes and no notify/
escalate option; execution is caller-owned regardless. The focused tests were
rerun after that wording correction. This is guidance, not a guarantee that an
agent will preserve owner policy correctly.

The frozen run completed all 16 episodes using 29 live Jev requests, observed
`jev-1.13.0`, without failed requests or budget censoring. [v3-04 results](bootstrap-codex-regression-v3-04.md)
remain negative: baseline final routing 6/6, treatment 5/6, treatment native
outcome AND recipients 4/6. Helpdesk is native 3/3; the database card still rewrites
investigate into notify and omits its investigation route. Independent blind
review confirms that policy violation. Guidance alone did not solve onboarding,
and procedural approval is not owner-policy validation. No broader run or repeated
retry is justified until that failure is addressed.

### Owner-policy verification research probe v1

Before adding another production gate, test whether a bounded Jev verification
call can identify a draft that changes the supplied owner's policy. This is a
development probe under `evaluations/`, not an approval feature or a new bootstrap
benchmark. It does not authenticate the provenance of the supplied statement.

`evaluations.owner_policy_review_trial` sends two independent Choice questions
together: fidelity of prose decision rules, and fidelity of actual outcome/route
entries. Twelve synthetic pairs span database operations, finance approval and
support SLA. Four faithful controls include a paraphrase; eight negative controls
cover omitted routes, an extra recipient, outcome broadening, changed threshold,
underspecification and conflicting owner instructions. No hidden expected labels
enter the state. These are deliberate development mutations, not fresh enterprise
holdouts, and they do not test source selection or mandatory-watch semantics.

Freeze after reviewer preflight. Run once into exclusive
`artifacts/owner-policy-probe-v1-01`, at most 12 live requests, no transport retry,
no external notification. Retain full synthetic inputs, questions, distributions,
resolved model, durations, token usage and errors. The experimental acceptance
rule requires both valid distributions to select consistent at probability ≥.80.
No threshold tuning or repeated run to obtain a passing result. Record exact
judgment matches separately from false acceptance and false blocking. Malformed,
missing and failed answers do not accept; partial execution cannot pass.

Even perfect results here would only justify exploring a production integration.
That would need persistent original requirements, provenance, current-card binding,
non-waivable failures, host-owned human approval and stale/race tests. An optional
transient review argument would be insufficient because later approval could lose
the original statement. Do not silently replace procedural approval in the frozen
v3 benchmark with this check or describe it as human validation.

Preflight review caught overlapping unclear/inconsistent criteria, ambiguous
approval-record wording, and extra specificity in a purported paraphrase.
All were repaired before live dispatch: unclear owner dimensions take precedence;
explicitly recorded nonapproval differs from missing records; both sides now use
the same defined latency/lag scope. Pending-attempt persistence and JSON-safe raw
answer diagnostics were also added. Fourteen offline probe tests pass. The
independent reviewer cleared the frozen probe SHA-256
`42df7f4924d0103027499fa169ad1ff23591a25032ddf67e68258305e06e9418`
for one 12-request development run, not production use.

### Delivery certification gate repair

Independent code review found `delivery_exact` was recorded but omitted from
the promotion predicate. Test-first reproduction produced seven failures and
five positive controls. The fix requires every successful case's explicit route
label to match before promotion; no averaging or lowered outcome threshold can
waive it. Missing labels remain unconstrained, not verified. Explicit empty labels
still require no route. The existing outcome-only safety metric is not renamed
into a broader claim. Policy version 3 makes earlier reports stale for readiness;
historical evidence is not rewritten. This repairs certification, not the failed
agent's authored card, nor the authenticity of simulated human approval.

Final full verification after the fix: 1,450 passed, 3 opt-in skips in 93.31s,
Ruff and whitespace checks clean. A second reviewer independently ran 61 focused
delivery/version tests and found no scoped blocker. An earlier suite had imported
the old evaluator while the test-first patch was being applied and reproduced
seven delivery failures; it is not the final verification result. The probe and
gate are frozen together before the one permitted research dispatch.

The [12-request live policy probe](evidence/owner-policy-probe-v1-01.json) completed
at `6529214d7525d110ac2aabc9674058d0b7bd6c1f`, observed `jev-1.13.0`, using
12,106 input and 984 output tokens in 2.676 seconds summed request wall time.
No retries/errors/malformed responses. Exact paired judgments matched 10/12;
21/24 individual judgments matched. All four faithful controls accepted and all
eight negative/unclear cases refused experimental acceptance at the frozen .80
threshold, but this is not eight correct semantic detections. Missing support
routing was mislabeled consistent at .58; the investigate-to-notify broadening
was called consistent on rules at .94 and routes at .79. Its .01 margin below
acceptance is not robust evidence. The exact-match requirement failed. No threshold
was adjusted and no repeat was run. Full inputs, raw distributions and timing are
retained. This broad fidelity classifier is not being installed as an approval gate.

The next [v4 development protocol](bootstrap-owner-reviewed-v4.md) instead models
an independent caller-owned reasoning review against original owner answers in
both arms, with bounded explicit correction and all additional work counted.
It does not replace the failed v3 results or pretend a model is an actual human.

V4 preflight review blocked dispatch on mutable post-approval notes, lost review/
tool counts after failures, and overly broad timeout wording. Five owner-gate
tests reproduced the first two gaps before repair. Both arms now freeze policy
notes during monitoring and verify their binding before each run; review attempts
are reserved before dispatch and survive cancellation and binding-fetch failure.
Role-tagged tool audit records preserve author/reviewer counts, including malformed
stdout. Response timeouts explicitly exclude startup/cleanup; full wall time and
overrun are retained. A separate reviewer cleared the bounded experiment after
running 85 targeted tests. This is process/code clearance, not semantic or
enterprise-performance evidence.

Final v4 pre-dispatch verification: 1,509 tests passed, 3 opt-in skips in 94.04s,
Ruff and whitespace checks clean. Credential/configuration preflight made zero
requests. Reviewed code hashes match the final files; freeze this revision and
run the one preregistered two-company trial, without editing its implementation,
prompts, fixtures or scoring while active.

### Owner-reviewed v4-01 result: goal not met

The [frozen run](bootstrap-owner-reviewed-v4-01.md) completed all 16 episodes and
six model-owner reviews with 46 live Jev requests. Native joint outcome/recipient
keys remain 4/6; final treatment 5/6 versus baseline 6/6. One unnecessary evidence
requirement was corrected, but answerability/coverage uncertainty and agent
overrides persist. Independent blind review: baseline 5 supported/1 qualified;
treatment 3 supported/2 qualified/1 unsupported. Full failure evidence retained.

Post-run audit also found accepted bare destination keys where supplied directory
entries require slack:// addresses. The frozen scorer checks keys, not endpoints;
no delivery success follows from that score. Keep this limitation explicit and
test exact directory lookup separately. Next isolate the answerability predicate
with a bounded paired probe rather than rerunning the full experiment or tuning
thresholds. No production approval or enterprise-readiness claim is justified.

Exact-directory lookup now rejects mismatched endpoint strings before a paid
synthetic-owner review. Five negative tests failed before the repair, with an
opaque-endpoint positive control. Independent review cleared the fix and its 25
owner-gate tests. It is research admission, not a universal URI requirement or a
retroactive scorer correction.

The [paired answerability probe](question-answerability-probe-v1.md) received
independent preflight review. Review caught a reporting mismatch that required
both templates to pass instead of the preregistered candidate gate; this was
corrected and tested before dispatch. Forty-two isolated offline harness tests
passed with network/credentials blocked. Final unchanged-tree `make verify`:
1,557 passed, 3 opt-in skips in 95.24 seconds; Ruff and diff checks clean.
Freeze the reviewed source and run the single capped 20-request probe. No
production question template has been changed yet.

The [live paired probe](evidence/question-answerability-v1-01.json) ran once at
`f14012b`, using 20 requests, 16,346 input and 720 output tokens; resolved model
`jev-1.13.0`; summed request wall time 3.924 seconds. Both templates scored
19/20 exact with nine answerable cases accepted, zero false support, zero known-no
refusals, and one uncertain answer. No errors, malformed answers or retries.
Both are uncertain on the partial compound question (rollback known, authorizer
missing): old .31, candidate .36. That is safe refusal, not an exact negative
classification. The preregistered 20/20 candidate gate failed; no comparative
improvement was demonstrated. Do not install the candidate as a proven fix, lower
thresholds, repeat for a favorable result or conflate this probe with full runtime
quality. The existing production question template remains unchanged.

### Truthful evidence handoff repair (policy version 4)

Separate from the failed prompt probe, code inspection established two reporting
defects: low answerability was labeled a contradiction, and the rationale assigned
the original selected probability to the code's fallback outcome. Six targeted
tests reproduced these defects before repair. Unanswered questions now remain
pending/missing, while required-source failure keeps unavailable precedence;
automatic notify/escalate remains blocked by unresolved required evidence.
Rationales distinguish Jev selection from confidence fallback without changing
thresholds, probabilities or routing control. The compiler completion text changes
serialized model state, so no identical-output or accuracy-improvement claim is made.

Six offline replays of retained v4 live judgments validate the changed handoff
without new API calls or rewriting historical evidence. Plan status remains
unchanged in all six. An independent reviewer passed 144 focused contract tests
and the seven matrix/replay tests. Full verification initially caught the old
offline matrix's erroneous not_supported→conflicting expectation; that case now
asserts missing AND not conflicting, with its original conservative outcome and
handoff unchanged. Final `make verify`: 1,569 passed, 3 opt-in skips in 94.59 seconds,
Ruff and diff checks clean. Policy version 4 requires recertification instead of
silently upgrading previous reports.

The adoption goal remains unmet. The next onboarding gap is empirical review:
the current model owner checks policy prose, not whether the actual preview and
selected source contracts can execute that policy. Use the existing simulation
and labeled workflow-evaluation boundaries to test that, with source coverage
defined explicitly and equally for both arms. Keep future snapshots and expected
answers out of setup, count extra review/correction costs, and retain original
failed trials. Do not add another agent framework or call an accepted draft a
certified recurring investigation.
