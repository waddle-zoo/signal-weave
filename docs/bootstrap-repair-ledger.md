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
