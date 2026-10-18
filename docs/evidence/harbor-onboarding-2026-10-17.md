# Harbor onboarding: useful answers, incomplete recurring handoff

**Both live analysts produced supported first readouts. SignalWeave saved a
reviewable card with fewer tool calls in this pair, but added avoidable setup
prerequisites. Recurring value and Jev behavior were not tested.**

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
