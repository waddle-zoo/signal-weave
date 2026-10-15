# Domain-context preview evidence

Updated 2026-10-15. Feature branch: feat/domain-context-memory;
[draft PR #19](https://github.com/waddle-zoo/signal-weave/pull/19).
Main and the published rc3 download are unchanged.

## Current conclusion

The context/card API, native transports, and one scripted-owner onboarding pair
have engineering evidence. A paired report-only study completed six reports and
three live Jev calls; a later treatment-only interpretation check completed
three more reports and three Jev calls on the same supplied Pine Courier periods.
Policy outcomes and native receipts were correct, but narrative and scorer defects
remain. A further contract-repair study stopped after four of six reports;
its review packet also omitted necessary timing/execution context. No corrected
pass rate is claimed. There is no demonstrated overall cost, quality, or business advantage.
Comparative business benefit, customer SSO, interactive onboarding, and enterprise
readiness remain unproved.

The [acceptance ledger](../domain-context-plan.md#current-acceptance-ledger)
keeps the full goal open. The [immutable full snapshot](https://github.com/waddle-zoo/signal-weave/blob/0be8ae61511d408175e261231d50f89a8e62c552/docs/evidence/domain-context-preview-2026-10-14.md)
preserves the earlier chronology, negative results, costs, identities, and
reproduction details. This note condenses that record; no raw research artifact
is added to Git.

## Current engineering evidence

| Area | Result | Boundary |
| --- | --- | --- |
| Context persistence and authorization | Contract coverage plus signed native HTTP review, reuse, role, tenant, read-only, and restart checks | Synthetic issuer; not customer SSO |
| Card/context dependencies | Exact revisions, source/meaning checks, reapproval, stale-context deferral, and historical receipts | No semantic graph traversal or automatic reminder delivery |
| Same-card clarification | Owner-scoped revision preserves anchors and pins, increments version, clears approval/plan, and uses exact-snapshot compare-and-swap | JSON locking is process-local; multi-process use requires SQLite |
| Current native transports | 12 checks in 81.00 seconds: two native lifecycles and ten URL validators; zero inference | Local Superset metadata and synthetic signed issuer; not native report-quality proof |
| Full suite including report-contract/packet fidelity tests | 3,478 passed, 11 skipped, in 224.74 seconds | Software checks, not companies or an accuracy estimate; 35 focused research checks also passed |

The native stdio lifecycle took 49.23 seconds: ten MCP calls and nine Superset
metadata reads. Signed HTTP context reuse, roles, and restart took 31.30 seconds;
the ten URL validators and both lifecycles made zero provider requests.
This clean native build records Git commit
633a7393ad9404465d2cfc658f74338696c84db0, source/skill fingerprint
63a0208baeee74db8e28a18e371bb72ff8ed2c44f88cfff58b5fd903d43523ff, and binary
SHA-256 20594f212402a29b51cacf2663ca36fd19528a7e67caf9555ccd2db98f7f3328.
These checks do not exercise a real human wizard or customer deployment.

The ignored local JUnit is artifacts/optional-judgment-native-transports-v1.xml
(SHA-256 ccd25997f81593c081cd0e1e9770fd2d8555f11af6d10d086c342c0590e581ba).
Its raw contents are not committed. The
[preceding snapshot](https://github.com/waddle-zoo/signal-weave/blob/633a7393ad9404465d2cfc658f74338696c84db0/docs/evidence/domain-context-preview-2026-10-14.md)
retains the older guidance-only build and its native checks. Neither build is
the published rc3 download, despite the same package label.

## Owner setup and native decision lifecycle

The owner-handoff-v4 development pair completed both scripted handoffs and
independent synthetic policy reviews. Treatment revised the same card from draft
version 2 to approved version 3. Both first readouts correctly showed 5,220/5,800
and 10,440/11,600 as 90% attainment despite doubled volume. Treatment setup
used 755,509 input / 133,429 uncached tokens, versus baseline's 203,839 /
55,871. Across setup, both arms used 959,348 input, 770,048 cached, 189,300
uncached, and 10,249 output tokens. The original run stopped at its uncached
token limit before either recurring report; it did not test report quality,
amortization, or context reuse. The accepted setup was restored later into a
fresh local SQLite fixture, not recovered from its original home.

A separate native approved-card clarification check matched all three supplied
retail periods and exact saved routes: insufficient_data, ignore, and notify.
Changing required meaning returned source facts without a policy outcome or
another inference call. Its three Jev calls used 15,024 input and 163 output
tokens. This used a scripted owner and synthetic data, sent no messages, and
does not establish conversational onboarding or comparative usefulness.

Earlier onboarding cohorts remain terminal. They include invalid schemas,
incomplete handoffs, a rejected draft-edit dispatch, and a foreign metadata-tool
call stopped by the guard; the v2 third invocation's cost remains unknown.
These failures are not relabeled as product outcomes, and the guard was not
weakened. The immutable snapshot retains each cohort's precise trace and cost.

## Report evidence

### Earlier paired report-only study

The reviewed-setup-reports-v1 comparison completed six fresh reports and three
live Jev calls, with no retries. Both arms had the same approved policy, owner
answers, glossary, company tools, and three supplied periods. SignalWeave also
had its installed skill and native analysis tools, so this was a whole-package
comparison rather than an isolated provider test.

| Measure | Baseline | SignalWeave |
| --- | ---: | ---: |
| Correct policy outcomes | 3 of 3 | 3 of 3 |
| Agent tool calls | 15 | 7 |
| Source reads | 5 | 3 |
| Summed agent seconds | 62.36 | 51.81 |
| Agent input / uncached tokens | 227,025 / 59,345 | 252,379 / 75,483 |

The two avoided reads were handbook context, not warehouse queries. Treatment
was slower in two periods, used more agent input tokens plus Jev, and had higher
setup cost. The quieter period drove its lower summed time. The raw report score
was 2/3 in each arm. The baseline quiet report proposed the business owner for
an ignore outcome; receipt citations and the distinction between report audience
and alert recipient also made parts of the scorer ambiguous. Correct outcomes
and fewer tool calls do not establish a win.

The treatment described parcel volume as unresolved in both complete periods,
although the supplied denominator counts rose from 5,800 to 11,600. It followed
an optional watch's unknown judgment instead of clearly reporting the available
counts. The reports did not establish cross-card reuse or a useful investigation.
Combined accepted onboarding and these six agents used 1,438,752 input /
324,128 uncached / 16,585 output tokens across twelve agent responses; Jev usage
was separate.

### Treatment-only interpretation check

handoff-interpretation-v1 reused the same three Pine Courier periods, with three
SignalWeave reports and three live Jev calls. It had no baseline, used no retries,
and made no provider, policy, or numeric-analysis code change; the change was
instruction/skill guidance, built at d76de21 before the later relocation. All three policy outcomes and card receipts were
correct, with delivery disabled. The raw report score remains 0/3.

The reports contain factual positives: the quiet period correctly says 0.90
attainment was unchanged and below the notify threshold; the missing-denominator
period correctly says the prior total was 5,220/5,800 and the current numerator
was 10,440 with denominator null; and the event period correctly reports 0.90
to 0.75, a 0.15 decline, and the notify outcome. These positives do not erase
the reporting limitations below.

A review of reporter p26 found that PublicSourceAdapter.set_period shifts the
fixture's original Monday 00:00 calendar-week data to arbitrary seven-day
windows beginning Thursday at 08:45 UTC. The supplied period labels therefore
do not prove compliance with the owner's complete UTC calendar-week definition;
this harness limitation remains under investigation.

The report-specific defects are:

- In the quiet period, the source denominators doubled, but the prose calls
  volume unverified and says no volume change is claimed.
- The event-period report also leaves volume unresolved.
- In the missing-denominator period, prose preserves the counts and null
  denominator, while structured numeric claims label 5,800 and 10,440 as
  on_time_delivery rate fields with unit parcels. This is a typed mapping error;
  the raw counts were not invented.
- The raw score flags the quiet report's proposed business-owner recipient as
  wrong for an ignore outcome. The prompt's proposed-recipient field is
  ambiguous between report audience and alert recipient. Accepted owner context
  was supplied, so this is not a missing-owner-lookup failure. Receipt citations
  are valid workflow evidence, but source-only citation checks mark receipt IDs
  unknown. Preserve the raw score of 0/3 rather than silently rescoring.

Three separate blind, supplied synthetic non-native scalar, rate, and additive
reporter fixtures passed private factual rubrics. They had no old-guidance
control, no live Jev call, and no business benchmark; they do not repair or
replace the 0/3 live report score.

Six cached-packet reporters then compared the same three live-Jev handoffs
with optional result arrays inline versus separately labeled. Independent
review found the quiet-period contradiction in the current layout but not the
separated layout; both layouts preserved the missing-denominator limits and
adverse-period outcome. One separated report gave a wrong workflow field path.
No native, source or provider calls occurred; a single pair per period does not
prove a reliable quality gain. The corresponding compact presentation change
retains all values and required checks; stored reports still repeat optional
judgments, so this is not complete isolation or a proved narrative fix.
For example, the current-layout quiet report gives both parcel totals and then
says "no volume figure is available in this packet"; the separated-layout
report instead preserves the counts and qualifies only the optional watch.
The actual production transform was replayed offline against all three current
packets: every result field round-tripped, including report warnings and
measurements. It adds 134 JSON bytes per packet, not a payload-saving claim.

The new report records 233,787 agent input tokens (159,232 cached; 74,555
uncached) and 3,307 output tokens. Three Jev calls used 18,446 input and 391
output tokens. Including accepted v4 setup, the nine agent responses used
1,193,135 input, 929,280 cached, 263,855 uncached, and 13,556 output tokens;
Jev usage is separate. This treatment-only run has no comparative cost result.

The ignored local report is
artifacts/handoff-interpretation-v1-live/report.json (SHA-256
7e4f62a999b9dcb36824baa8f7db08692668205f44c342427285f31cff32d725).
Its associated trace remains ignored. An independent agent review is not
scientific peer review.

## Retained artifact identities

### Shared report-contract repair: stopped, not a new success rate

`grounded-reports-v2` exposed the previously omitted public fact definitions to
both arms, clarified policy routes versus routine audiences, and kept workflow
receipts out of structured measurement citations. All four actual prompts
contained the definitions. Production/skill fingerprints were unchanged.

The registered 600k input stop ended this study after **four of six reports**
and two live Jev calls. The adverse pair never ran; no retry or extension occurred.
All four observed policy outcomes and routes were correct. Baseline's raw
structured score was 2/2; treatment's was 1/2 because its quiet report omitted
the required typed delta despite stating it correctly in prose.

| Two completed periods | Baseline | SignalWeave |
| --- | ---: | ---: |
| Tools / primary source reads | 13 / 2 | 13 / 2 |
| Input / uncached tokens | 195,701 / 63,093 | 404,640 / 78,496 |
| Summed agent seconds | 56.68 | 61.27 |

Eleven of the 26 tool results were rejected research-submission arguments
(wrong field names, extra fields or missing fields). That formatting overhead
confounds task-cost interpretation; it is not a production connectivity failure.
The treatment's larger input is still an observed cost, not a win to discount.
Its two live Jev calls used 12,109 input / 262 output tokens. Combined new-agent
usage was 600,341 input / 458,752 cached / 141,589 uncached / 7,847 output;
including accepted onboarding: 1,559,689 input / 330,889 uncached / 18,096 output.
Reviewer/coordinator costs and older unknowns remain outside those runner totals.

Both independent reviewers' original outputs are retained, but **their overall
pass rates are unusable**. The review packet omitted per-case assigned cutoffs
and successful draft-recording events. Both reviewers then treated the cohort's
latest cutoff as every case's cutoff and confused source capture with measurement
dates. Actual report prompts assigned September 28 and October 5, with a separate
October 15 query clock; source capture matched that clock. The recorded snapshot
capture lag was zero; capture-after-period does not establish snapshot staleness
under the implemented age rule. Capture metadata does not prove metric/data freshness.
One baseline report also made an unsupported staleness claim. Both reviewers
treated treatment's volume wording as ambiguous, not absent measurements; the
coordinator's initial stronger contradiction claim is not a consensus finding.
The 5,800 and 11,600 denominators were also present in the actual Jev request;
missing counts in its input are not the explanation for this case.
No corrected review or comparative success is being substituted for these outputs.

The new research-only [packet builder](../../evaluations/report_review_packet.py)
checks the actual per-episode prompt, source-read clocks and successful report
recording in both arms. It preserves agent/native disagreements for review,
rather than requiring agreement to admit a case. Eleven focused checks cover
timing, missing clocks, current receipts, recording evidence and planned versus
unrun counts. Applying it to the retained trace produced a separately labeled
factual supplement: four completed, zero incomplete and two unrun reports, with
the assigned per-report cutoffs and zero recorded snapshot capture lag. The
original reports and model reviews were not changed or rerun. This data-quality
repair does not prove analytical correctness or underlying metric freshness.

Next fix the evidence packet and simplify the evaluation's human-report handoff
before more paid runs. Correct labels, strict schemas and reviewer agreement
are not sufficient evidence of business value when their framing is wrong.

These hashes identify local ignored files; they are not public reproduction
inputs. Raw traces, reports, credentials, and setup state remain outside Git.

| Artifact | SHA-256 |
| --- | --- |
| Accepted v4 onboarding report | e4f4cef42971fefb466ba0eb9df0c6d267dce05fc13544dae9fcb397354b5048 |
| Accepted v4 onboarding trace | e534505dfc0eb8a6072d47de408be3308489ab18619db4a681c810208975a13b |
| Earlier paired report-only report | cf0c148c5ff31c98352e8c375670045dfcdacfb3f0c2d3ff0df437c2079c275e |
| Earlier paired report-only trace | 3387a21ce9ceccd432c9c63a267ba9030c6f44ca84fbd3e9083cacfe4eb368db |
| Interpretation runner | ff157aaf5362abc2f0cacbe3026c339958104251c299a391a2d277dbdc014408 |
| Interpretation scenario | ca90a3755be866c6ffd6645c2b7ba88edb7c946a187c6e96017ad96beaaef38a |
| Current native transport JUnit | ccd25997f81593c081cd0e1e9770fd2d8555f11af6d10d086c342c0590e581ba |
| Frozen six-packet layout manifest | 2659c1d95d1be4c86f558d8360dd8bd06971652ddbce2e5055459c93415589bf |
| Calendar zero-inference preflight report | 4d189da105310691b86677d970ec736681d0080c547116e9f9921d1b1a81d8f8 |
| Shared-contract preflight report | bf74c55db27856754bfed77affe49ddc71366755a9fe541ebca3e60948363f56 |
| Stopped shared-contract live report | 1ac0c478f80e937f4989811e71190d7ad3c009a39ab33cd1b754bdb55f4ee9ed |
| Stopped shared-contract live trace | 46ad4937492974c76a5c7def2ee587ac2d0ca38acee0af20511b6e1fb5a56a6a |
| Factual review-evidence supplement | 7dadaebd825b3a60205579bff7e990bb8c531e70313120a27a78199454fad057 |

## Reproduction and remaining gates

Run make verify for the software suite. The zero-inference stdio and HTTP checks
can be rerun against the explicitly selected local synthetic Superset fixture
on port 18089 using the protocol in the plan. They do not reproduce the live
report study. An exact public rerun still requires ignored v4 accepted artifacts;
there is no public turnkey reproduction bundle.

After building the current candidate, the native checks are:

```sh
RUN_CONTEXT_CARD_INTEGRATION=1 SIGNALWEAVE_BINARY="$PWD/dist/signalweave" uv run pytest tests/test_context_native_card_integration.py -q
RUN_CONTEXT_HTTP_INTEGRATION=1 SIGNALWEAVE_BINARY="$PWD/dist/signalweave" uv run pytest tests/test_context_native_http_integration.py -q
```

No schedule or external notification is authorized. A future calendar-faithful
paired mode passed its offline tests and actual native preflight: zero agents,
zero Jev attempts, exact approved version-3 card restored, and distinct Monday
measurement cutoffs with separate capture time. No live calendar cohort started.
Next outcome gates are useful reports with correct scope and
uncertainty, cross-card context reuse and changed-meaning behavior, varied
connectors and held-out business cases with complete accounting. Interactive
human onboarding, customer SSO, actual scheduling/delivery, and enterprise
efficacy remain unestablished.
