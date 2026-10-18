# Harbor: first answers and recurring queue handoffs

**Both live analysts produced supported first readouts. SignalWeave saved a
reviewable card with fewer tool calls in this pair, but added avoidable setup
prerequisites. Recurring value and Jev behavior were not tested in that original
cohort. The separate assisted continuation below runs both arms through three
cutoffs with live Jev; it establishes recurrence capability, not net user lift.**

The [compact record](../../evaluations/data/harbor-onboarding-v1-summary.json)
contains both exact final messages, the treatment's actual draft policy, usage,
recovered native errors, source checks and immutable local artifact hashes.
Large reports and traces stay outside Git. Earlier failures remain unchanged.

## What ran

One known fictional support company, one historical ordinary observation, two
fresh Luna 6 xhigh analysts, treatment first. Both kept the same actual company
SQL MCP, saved-query catalog, owner references and their own reusable notes.
Treatment also used the current native/default-profile SignalWeave MCP and its
installed skill. Source bridge preparation and CLI setup were scripted operator
work, not a person's successful installation. The CLI workspace was restricted
to the trial tools; this is not ordinary-workspace compatibility evidence.

The opening request was: “What open priority work needs attention today?
Please prepare a handoff the queue lead can review.” The fictional prior context
distinguished an unanswered-first-response trigger from a separate, unresolved
resolution-work policy. It did not supply numerical answers or consent.

## What the person received

Both readouts correctly separated **zero known unanswered priority tickets past
the response clock** from **81 already-responded priority tickets past the
resolution clock**, among 88 known open priority tickets. Independent raw-history
recomputation confirmed these counts and the tier breakdown. Neither claimed
causality, customer harm or a complete current company queue.

The treatment retained an aggregate-backed draft card. Its final answer also
asked the owner to add an approved ticket-detail source and resolve unsupported
comparison defaults before repetition. Those are distinct issues:

- SignalWeave's typed card/plan required at least one period-comparison window,
  so the agent's attempt to clear windows for a point-in-time check failed.
- The agent added a prerequisite that ticket detail must be included in the
  card. Its existing authorized company SQL could instead obtain that detail
  for the human handoff; native card scope does not govern every caller read.

The baseline gave a more explicit resolution-work review suggestion and saved
portable queries/notes. It also described transient exported query results as
named “fixed” sources. An `export_query` result is not registration of a durable
catalog resource; those references must not be treated as newly discoverable
assets on a later run. Its facts can still be checked against the retained SQL
and source rows.

Both messages were dense for a same-day handoff. Artifact creation alone does
not establish that the workflow is ready for unattended use or easy to operate.

## Recorded effort

| Measurement | SignalWeave agent | Plain agent |
| --- | ---: | ---: |
| Analyst response seconds | 183.83 | 229.43 |
| Whole caller-stage seconds | 197.94 | 235.95 |
| Admitted tool calls | 20 | 30 |
| CLI aggregate input tokens | 549,915 | 711,153 |
| CLI uncached input tokens | 70,555 | 72,177 |
| CLI output tokens, including reasoning | 22,308 | 33,486 |

This single treatment-first pair is descriptive, not a causal speed estimate,
cost-saving claim or representative enterprise sample. Cached-token billing and
invoices were not measured. Separate scripted preparation took 37.41 seconds;
source-bridge authoring, actual human effort and internal research-review costs
are unmeasured. Source-query counts are not compared because native inspection
also executes upstream queries.

The first actor completed below the 700,000 aggregate-input stop, admitting the
baseline. The latter completed across that **between-invocation** stop: combined
input was 1,261,068, including repeated cached context. No in-flight token cap
was claimed. The caller verified the stop and launched no further actor. Both
usage records are known; there were **zero Jev requests, approvals, recurring
observations, schedules or deliveries**. No power settings changed.

## Next action, not a repaired score

Fix explicit non-comparative cards and clarify the boundary between automatic
card retrieval and caller-owned investigation. Preserve these original messages
and failures. A later forward trial must measure whether the corrected journey
actually improves onboarding and repeated human updates; software checks cannot
rescore this pair or establish that result.

Independent internal review recomputed the consequential claims from the raw
snapshot tables and found both one-off findings supported. Its initial proposal
to require registered detail/prior-handoff state was withdrawn after checking
caller-tool rights and the owner's explicit fallback when no prior list exists.
The baseline's separate resolution-review suggestion is an allowable advisory,
not an authorized new recurring trigger. This is not external peer review, a
real-human usability panel or proof of value across businesses.

## Forward repair verification

Commit `0b9ff58` allows explicit `comparison_windows=[]` while retaining omitted
window defaults and explicit comparison requirements. Current-only plans omit
period-change calculations; cross-source current checks remain possible. Current
totals carried inside comparison tables are retained as source-reported inputs,
not validated decompositions. Empty current values remain unknown, not zero.
The skill and MCP guide distinguish caller investigation from native card scope.

The rebuilt native candidate at that commit passed actual default-profile
draft → revision to `[]` → review → fixture-operator approval, followed by source
inspection, behind a zero-request provider proxy. Separate isolated source/native
skill installation controls passed for Codex and Claude. These are software and
transport controls—not new analyst journeys or actual owner approval of the
Harbor card above. Its original draft and outputs remain unchanged.

The full suite passed 4,418 checks with 13 opt-in skips; the native opt-in run
passed three software cases, including a source-CLI control. A Python 3.11 subset
passed 82 checks. An independent internal code reviewer found a current-data
loss in the first patch, then cleared the corrected projection/primary-slot
handling. None of these checks requested Jev inference or proves improved agent
behavior. New business evidence is still required.

Reproduce the forward native control after building the current source:

```sh
SIGNALWEAVE_TEST_BINARY="$PWD/dist/signalweave" .venv/bin/python -m pytest -q tests/test_native_point_card_journey.py tests/test_native_skill_journey.py
```

The tested native source fingerprint was
`ef31d0bafb0b3a1bab1903015302bc1ac4b43810611828709ad51ce3349be1c4`;
its binary SHA-256 was
`561d39c9427de8c849c90cac3c6bfa96da46e305ffd436fd06ddc3c9a1c712bc`.
This is a source candidate, not a new published release.

## Separate expert-assisted continuation

The original capped onboarding cohort remains closed. The follow-on method in
`evaluations/harbor_workflow_continuation.py` imports the actual authored card
into a fresh private store on the corrected native candidate. It clears invented
period windows and the invented companion-detail registration prerequisite.
It disables wall-clock freshness rejection **only for these retrospective
snapshots**; that is not a production freshness recommendation. The same expert
clarification goes to both arms, including that exported aliases are transient,
authorized SQL remains available, and unknown prior handoffs do not block a
known-record handoff. Each agent retains its own original notes verbatim.

A delegated simulated data expert reviews the actual repaired draft, source
scope and both saved artifacts before local shadow approval. This is assisted
setup, not a fresh human installation or new onboarding pass. Two fresh analyst
contexts then receive successive ordinary, changed and recovery observations;
future cutoffs are revealed only after the current brief is saved. Baseline runs
first in this continuation. Both retain the same raw company tools and owner
context. No messages are sent, no schedules start, and no customer harm or
incident cause can be inferred from this source.

The prospective allowance includes the parent: four total analyst invocations,
at most six live Jev requests, 60 admitted tool calls and 420 response seconds per
new actor. The new between-actor stops are 2,500,000 aggregate input tokens or
300,000 uncached input tokens **including the completed parent pair**. They are
not in-flight caps or a dollar estimate. No failed actor is retried. Operator
repair and expert-review effort remain unmeasured and cannot be amortized away
in a claimed saving. This is a known development workflow with three dependent
states, not three independent companies or a superiority study.

### Completed continuation: what the person would receive

Both fresh analysts completed their single attempt, saving three unsent briefs.
Only the changed state selected the Support queue lead and duty manager as
intended reviewers; ordinary and subsequent zero-trigger briefs had no alert
recipients. The treatment exercised three distinct current native receipts and
three live `jev-1.13.0` judgments: `ignore`, `investigate`, `ignore`.

| Historical cutoff | Known open priority tickets | Unanswered past response clock | Past resolution clock |
| --- | ---: | ---: | ---: |
| February 23 | 88 | 0 | 81 |
| March 2 | 184 | 80 | 171 |
| March 9 | 117 | 0 | 104 |

An independent internal data reviewer recomputed these claims from raw tickets,
tier clocks and snapshot markers. The treatment's 80 handoff IDs exactly matched
the qualifying raw set, including five groups of 16 at 68, 92, 116, 140 and 164
rounded hours beyond the enterprise two-hour clock. Both arms separated already-
responded resolution work from this unanswered-only policy and avoided claiming
customer harm or incident cause. No delivery or recipient action was tested.

The zero after the exception is **not proof of response recovery**. The same 80
records are present as resolved, still without a visible first response. Neither
agent followed that cohort through to this supported status explanation. Both
reported the count movement without inventing its cause; the baseline's claim
that snapshots could not establish individual status movement was too broad.
This is a useful analytical follow-through gap, not a reason to erase their
correct queue findings.

### Whole-workflow effort and usefulness

| Recurring measurement, all three states | SignalWeave agent | Plain agent |
| --- | ---: | ---: |
| Analyst response seconds | 182.05 | 169.66 |
| Whole caller-stage seconds | 190.09 | 170.28 |
| Admitted tool calls | 12 | 22 |
| CLI aggregate input tokens | 670,719 | 532,064 |
| CLI uncached input tokens | 86,271 | 68,448 |
| CLI output tokens, including reasoning | 22,784 | 20,837 |
| Changed-state human brief characters | 3,915 | 1,402 |

Jev separately consumed 11,985 input and 371 output tokens across three requests,
taking 0.65, 0.30 and 0.31 seconds. Those are policy-call timings, not the agent's
total work. There was no token overflow, retry or heuristic provider fallback.
Fewer admitted tools do not prove fewer upstream queries or better human value.

Including each arm's original onboarding, treatment used 1,220,634 CLI input
tokens versus 1,243,217 for baseline, but 156,826 uncached tokens versus 140,625.
Summed caller-stage time was 388.04 versus 406.23 seconds. These exclude source-
bridge authoring, manual repair, expert review and actual human effort; they do
not establish a net saving. All four analyst invocations together used 2,463,851
input, 297,451 uncached input and 99,415 output tokens. The continuation stopped
after the prescribed four total analysts; the closed parent was not reopened.

The independent product reviewer found **no clear human advantage yet**. The
treatment included every qualifying ID in its human message; baseline referred
to captured detail results. This is a real output difference, but the restricted
workspace supplied no recipient-facing attachment path. Trace-backed exports
are inspectable research evidence, not proof that an eventual recipient can
open them. Do not attribute this solely to Jev or infer ordinary-user harm from
that caller limitation. Both treatments need a realistic, accessible detail path
before testing delivered-message usefulness.

The next improvement is not a new analytical abstraction: keep the human message
focused, make supporting detail reachable through the caller's ordinary files or
delivery tools, and follow a flagged cohort into the next observation. Preserve
these results; a forward check must test those changes rather than rescore them.
This simple clock-threshold case demonstrates a reusable workflow, not why a
typed English policy is better than SQL or a frontier agent with durable notes.

Local terminal reports remain under `artifacts/harbor-expert-recurrence-v1/`;
large traces and all 80 identifiers are not copied into Git. Report SHA-256:

- Treatment: `08a6c1e473563b521050c98f4bfa0914f9cf9460d147feb111542a7a1e1b00d4`
- Baseline: `bb70673d668c3ca1d09ee154fd6fc18c3d352f2bfbb3135eb53fa9826facf9e9`
- Prepared continuation: `4fb7c9046aa5d53f9390fba5d5653d82b9124bf978d5ad3724a923a21c0aba4c`

The method is public; exact analyst replay requires the retained local parent
reports and private provider access. A fresh onboarding rerun creates a new
cohort, not byte-identical reproduction of these model outputs. The full offline
suite passed 4,424 checks with 13 opt-in skips, including six new continuation
accounting controls. Those are software checks, not additional business trials.

### Forward readout guidance, not a revised result

After closing the continuation, commit `65a07c1` adds conditional guidance to
the bundled skill: summarize with supporting detail only when the recipient can
actually open it; otherwise include required identifiers without claiming a
nonexistent attachment. An issue follow-up should inspect the previously
affected group's status when possible, not infer recovery from an aggregate.
An independent internal product reviewer checked this guidance's scope.

The completed analyst runs used the retained `0b9ff58` native candidate, now
also preserved locally as `artifacts/harbor-recurrence-native-0b9ff58`. The newer
guidance has not run in a new analyst cohort. Packaging or software checks on a
newer candidate cannot establish that it improves the final messages above.

The clean `65a07c1` candidate passed three isolated native controls (75.73s),
including actual bundled-skill installation for Codex/Claude and the current-
state card journey, without inference. The final full offline suite also passed
4,424 checks with 13 opt-in skips (317.77s). Its source fingerprint is
`eedd8011a4d34d43a02c71208576e4fa27bb77f637c60e2432c7cbbbbaa2cbe5`;
binary SHA-256 is
`1a939be6257ae2ca13ca188452c4b38da8e77c0e45d48dcf0e935b1b1e1bd267`.
It remains a local source candidate, not a new published release.
