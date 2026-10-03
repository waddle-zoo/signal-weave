# Native onboarding: completing the revision handoff

This follows the [previous native trial](installed-onboarding-trial-2026-10-03.md).
The adoption goal remains open. No release or main-branch merge is included.

## What the deeper trace showed

The operations run in `transfer-live-06` did not remain stuck at 0.62 ignore
support. Its final two revisions passed all three historical cases, with quiet
support of 0.78 and 0.75 under the unchanged 0.70 floor. The final revision also
restored the owner's data-repair instructions. It then stopped before completing
current-card inspection, preview and independent simulated-owner review.

The failure was therefore an incomplete authoring-to-approval handoff. Passing
calibration did not authorize deployment. The original incomplete setup remains
failed; we corrected its diagnosis, not its score.
That diagnosis is based on the separately retained
[live06 trace](evidence/installed-workflow-2026-10-03/installed-workflow-transfer-live-06/trace.jsonl.gz),
not on the newer pilots below.

## Bounded changes

Commit `2c15088` changes:

- Production MCP schemas now advertise and enforce the authoring layer's existing
  `1..25` discovery/review limit. Agents previously supplied 40 to a schema that
  omitted the maximum, then encountered a deeper validation error.
- The bundled guide explicitly preserves the quiet branch and data-repair
  instructions, and tells agents to complete inspection, preview and owner review
  on the revised card ID after historical acceptance.
- The research-only simulated-owner tool returns exact missing prerequisites and
  tool arguments. It does not perform those actions or approve automatically.
  Successful review no longer suggests mutating notes after approval, which would
  invalidate its fingerprint.
- The evaluation CLI accepts and freezes an explicit transfer seed.

No Jev questions, probability thresholds, expected business outcomes, delivery
permissions or production policy decisions changed. Company-specific fixtures
remain outside `src/`. The TypeSafe skill's separation of state, judgments and
code-owned control informed this narrow scope; uncertainty is not bypassed.
See [TypeSafe state guidance](https://docs.typesafe.ai/concepts/state) and
[uncertainty guidance](https://docs.typesafe.ai/confidence).

Internal Luna review found no approval bypass: current fingerprints are still
checked before review, after the reviewer returns, and before approval. Missing
prerequisites do not spend a reviewer call. This is internal review, not external
peer review.

## Frozen experiment plan

1. One operations repair probe, original seed `20261004`, capped at 40 Jev attempts.
2. Only if setup and all three future cases pass, one complete six-business
   prospective regression using seed `20261005`, capped at 150 Jev attempts.
   Its offline plan was frozen before the pilot result.

Both use the actual rebuilt binary, stdio MCP, a read-only synthetic source MCP,
Luna card authoring, independent simulated-owner review and live Jev. There are
no expert cards, future labels in agent inputs, actual deliveries or repaired
future outcomes. Incomplete companies remain in the intended denominator.

The second seed is a new instantiation of known families, not six unseen customer
deployments. Measurements are replayed through normalized source contracts;
this does not prove arbitrary connector onboarding or fresh warehouse queries.
The endpoint is native outcome, route and required-source presence, with frozen
cards/plans and no-call receipt replay—not full narrative quality or benefit over
Luna alone. Those remain separate proof gates.

Verification before live inference: **2,301 offline tests passed, five skipped**;
**18 actual-binary/MCP checks passed** without paid inference. Ruff and diff checks
passed. Native checks required permission for loopback sockets and macOS
semaphores. The binary hash and all runner content hashes are in each protocol.

## v8 pilot: failed, retained

`transfer-live-09` spent 22 of its 40 permitted Jev attempts, with no provider
errors or budget censoring. Setup did not complete; all three intended future
cases remain unexecuted failures. The planned v8 six-business run was **not
launched** because its prerequisite failed.

The revised-card handoff reached simulated-owner approval. Historical acceptance
did not pass: quiet evidence selected ignore with 0.62 support and was downgraded
to investigation by the unchanged 0.70 floor. Separately, quiet and quality cases
reported unexpected retrieval for a Change calendar. The agent subsequently
removed the calendar, which the event case requires; `get_owner_examples` refused
the incomplete card. The agent then supplied an invalid evaluation call without
cases. These are observed failures, not passing runs repaired after the fact.

The retrieval failure exposed a contract bug in our v7/v8 research harness:
`expected_retrieval_refs` was described as minimum-required evidence, but native
acceptance requires an exact set. A static card could not both keep context
required for an event and omit it in another case. This does not explain away the
independent low-confidence quiet failure.

## v9 repair and prospective gate

Production evaluation now accepts a separate optional `allowed_retrieval_refs`
label. The default remains exact-set retrieval. An explicit allowlist must include
all expected refs: required coverage is still mandatory, unlisted retrieval still
fails, and neither label changes Jev's input or authorizes sources. Report policy
version 5 requires recertification. Tests cover missing required sources,
forbidden extras, allowed context present/absent, malformed labels, unchanged Jev
state and label-digest changes.

The research fixtures freeze the two already-approved historical context assets
as permissible before agent selection. They do not derive the allowlist from what
the agent fetched. Required refs, measurements, outcomes and destinations are
unchanged. The independent adjudicator checks the two-set contract and verifies
the frozen dataset digest. Optional retrieval does not prove retrieval efficiency.

The next gate is one v9 operations pilot, same seed, capped at 40 Jev attempts.
Only a complete setup plus all three future cases permits another full cohort.
Repeated attempts remain visible; this is a repair probe, not an unseen holdout.

The implementation is committed as `0802260`. Internal Luna review confirmed no
new source-access or card-approval bypass. It identified a useful audit gap:
reports now retain the expected and permissible refs, not just their digest.
The remaining caller-label trust limitation is explicit: the host must freeze
and independently review labels; self-authored tests are not independent proof.
An adversarial test shows that weak caller labels can pass replay while the
card remains a draft and runtime evaluation remains prohibited.

The replacement v9 six-business plan uses seed `20261005`, 18 future cases and a
150-attempt cap. A direct comparison against the unexecuted v8 plan found that
the only fixture differences are the 18 explicit historical allowlists, each
containing the same two already-available context assets. Future measurements,
policies, labels and routes are identical. The committed harness content and
rebuilt executable match the hashes recorded in the v9 protocol.

## v9 pilot: source-selection recovery still failed

`transfer-live-10` used 22 Jev attempts and stopped after 21 authoring tool calls
(116.35 seconds). It never reached historical evaluation or independent owner
review: three requests for historical examples failed because the selected card
omitted an owner-required source. Setup was **0/1**, executed futures **0/3**;
there were no provider errors or budget censoring. The v9 six-business plan was
therefore also left unexecuted. Its fixture review found no policy/label blocker,
but that does not override the failed prerequisite.

The helper's error did not identify the missing source. In `fa23b08` the
research-only `get_owner_examples` now returns exact missing refs from the
already-supplied historical labels, plus inspection actions. It does not select
or add them, release future labels, authorize a card, or change any measurements.
Optional allowlisted context does not become mandatory. Failed binding clears
any prior offered cases, and the existing unchanged-fixture gate remains intact.
This is explicitly **owner-history-assisted onboarding**, not proof that the
agent discovers every needed source unaided.

Two new tests cover precise missing-source feedback, stale-offer rejection,
unchanged card/history and optional-source behavior. The complete production
patch passed **2,321 offline tests, five skipped**, plus **18 native executable
checks**; the subsequent research-only helper patch passed its **51-test**
targeted suite. All lint/diff checks passed.

One final bounded operations probe for this repair is registered as protocol v10,
same seed and 40-attempt cap. Its conditional six-company plan has exactly the
same fixture digest as v9 and remains capped at 150 attempts.

## v10 outcome and failed placement hypothesis

`transfer-live-11` used 24 Jev attempts. Exact missing-source feedback recovered
the canonical Change calendar; retrieval precision and recall both passed in
every historical case. The event and missing-data cases passed. Quiet did not:
the first evaluated card selected insufficient-data at 0.65, and the final card
selected ignore at 0.60. Both fell below 0.70 and routed to investigation. The
final watch-item diagnostic classified the trigger as absent with 0.93 support;
that diagnostic is not permission to override the final-outcome judgment.

Independent simulated-owner review approved the final policy, but approval and
setup correctly refused the failed historical acceptance. **0/1 setups and 0/3
executed future cases.** The v10 six-company plan was not launched. No budget
censoring or provider errors occurred.

One six-call paired diagnostic then tested a specific hypothesis: the final card
put the quiet instruction in `watch_for` instead of the outcome-owning guidance.
`installed_policy_placement_probe.py` repeated that **existing text verbatim** in
`decision_guidance`, bumping only card/plan versions. It replayed the same three
historical cases in process, alternating pair order, with unchanged evidence,
questions, labels and confidence floor. This was a post-failure diagnostic, not
binary onboarding, independent holdout evidence or a new approved card.

| Historical case | Original | Existing watch prose also in guidance |
| --- | --- | --- |
| Quiet | investigate; insufficient-data support 0.68 | investigate; insufficient-data support 0.54 |
| Event | investigate, 0.91; correct | investigate, 0.92; correct |
| Missing coverage | insufficient-data, 0.99; correct | insufficient-data, 0.99; correct |

**The placement hypothesis did not resolve the failure.** No production prompt
or onboarding-guide change was made from it. One pair per case cannot estimate
model variability or prove which representation is generally better. Card/plan
version metadata is also visible to Jev, so this is not a strictly prose-only
intervention and cannot attribute a probability shift solely to placement. Source
contracts in this fixture leave several definition/population fields empty and
export the measurements as evidence values, not typed observations; whether
that ambiguity explains the quiet outcome remains unproven. Do not infer missing
definitions or completeness merely to make a test pass.

Across these three pilots: **68 Jev attempts**, no successful new setup. Including
the diagnostic: **74 attempts**. Failed runs and the three unexecuted conditional
plans are retained under
[`docs/evidence/installed-workflow-2026-10-03`](evidence/installed-workflow-2026-10-03/).
Exports were checked for the actual secret value, and compressed trial artifacts
re-adjudicate identically to originals. Six diagnostic requests were separately
checked for matching factual/question payloads within each pair.

## What remains before expansion

The demonstrated improvements are a consistent required/permitted retrieval
contract, inspectable labels, and precise recovery from missing historical source
bindings. They are not new evidence of better business accuracy or enterprise
readiness. The source feedback is supplied-owner-history assistance, not automatic
source discovery. The TypeSafe-guided boundary remains unchanged: typed judgment
from Jev, admission and authorization in code, no heuristic replacement.

The next experiment should isolate evidence sufficiency—not repeat full setup
until it happens to pass. Establish explicit, source-backed field meanings,
comparison basis and population coverage, with matched missing-definition
negative controls. Only then rerun one frozen onboarding probe. Full prospective
cohort success, useful final analytical reports and a fair same-input Luna-only
comparison remain required before claiming the adoption goal is complete.
No main-branch merge or release is supported by these results.

Final internal reviews independently checked the pilot attempt counts, zero
setups, unexecuted plans and paired diagnostic input equality. They agreed these
artifacts do not support onboarding completion or enterprise/discovery claims.
The test totals above are the implementation runner's observed outputs, not
measurements independently reproduced by those evidence reviewers. These were
internal Luna reviews, not external peer review.

Final verification after the diagnostic helper: **2,325 tests passed, five
skipped** (134.94 seconds); Ruff and `git diff --check` passed. The most recent
native executable suite passed **18/18** on the same production binary used by
v9/v10. Later changes were research helpers and documentation only.
