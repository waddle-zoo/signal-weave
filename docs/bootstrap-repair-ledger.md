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
