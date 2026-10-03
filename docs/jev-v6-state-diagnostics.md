# State sensitivity diagnostic after the v6 cohort

Prospective component experiment, not an acceptance trial. The frozen v6 cohort
failed native routing on database and finance quiet periods. A read-only internal
Luna reviewer identified missing temporal context, blank optional annotations,
zero-versus-missing semantics, and overbroad watch questions as hypotheses, not
established causes. The finance quiet result also fell below the unchanged 0.70
action threshold. No threshold or card is changed here.

Replay request 38 (database) and 74 (finance) from the retained remaining-company
trace. The plan in `evaluations/protocols/jev-v6-state-diagnostics.json` declares
14 configurations, three seeded interleaved repetitions each: 42 attempts,
including failures, no retries. Preserve the original questions and policy.
Database probes omit blank annotations, distinguish zero from one or missing
affected regions, remove population, add the supplied simulation clock, and
isolate each original judgment. Finance probes omit blank annotations, add its
supplied simulation clock, and remove the source watermark. The originals are
included unchanged. Added clock text explicitly does not assert measurement
intervals, reporting cutoffs, or population completeness.

All mutations are diagnostics, not corrected business facts. Missing-value
controls are not scored against the original private labels. Compare raw answer
distributions and item support; do not select a winner from noisy calls or claim
that an outcome flip fixes required evidence completion. Retain resolved models,
tokens, failures, request hashes, full edited states, and every response. These
are known failing examples, not independent generalization evidence. Any proposed
repair must subsequently pass unchanged quiet/event/gap contexts across companies
and the end-to-end onboarding/reporting gates.

## First results and second bounded hypothesis

All 42 attempts returned. None of the interventions repaired database quiet
routing: the original, annotation omission, one-region control, explicit clock,
and isolated outcome all preferred insufficient_data. Missing population raised
its support to 0.88–0.91. Removing region count paradoxically made the availability
watch more positive; a listed cluster population is not necessarily a count of
affected regions. This question needs clearer meaning at authoring time.

Finance ignore support was 0.68–0.72 on fresh originals, 0.73–0.77 with blank
annotations omitted, and 0.63–0.64 with the explicit clock. The required watch
still lacked 0.70 support. No variant is a proven repair. Probabilities varied
across repeated requests; deterministic execution must not be confused with
identical model scores.

Next predeclared hypothesis: add the same generic state-semantics explanation
to both unchanged failing requests, distinguishing optional metadata from
observed data, zero from missing, and population completeness from health.
Retain unchanged originals plus missing population, region count, and watermark
controls with that explanation. Seven configurations × three repetitions = 21
attempts, no retries. Exact text/edits are frozen in
`evaluations/protocols/jev-v6-semantic-diagnostics.json`. This is hypothesis
development, not an independent acceptance set. Do not promote the text to
production merely because routing changes; missing-data controls and required
watch support must also remain defensible.

## Completed diagnostic findings

Both experiments finished with every planned attempt retained: 42/42 state
calls and 21/21 semantic calls, 63 paired Jev requests/responses in total, zero
failed rows or recorded API errors. All responses resolved to `jev-1.13.0`.
The state run used 198,891 input and 4,578 output tokens; the semantic run used
107,826 input and 2,759 output tokens (combined 306,717 input / 7,337 output).
There were three repeats per configuration, with no retries. These counts are
component calls in addition to the v6 cohort, not new onboarding/report records.

Here, **support** means the probability assigned to the selected answer in
`response.answers[...].probabilities`, not the separate raw `confidence` field.
Ranges below are observed minima and maxima across three repeats. Comparing
support with the unchanged 0.70 threshold is descriptive: these replay results
do not run the full engine or establish a final route after required-watch gates.

### State experiment: all 14 configurations

Each outcome in the table was selected in all three repeats.

| Request | Variant | Raw outcome | Selected-answer support |
| --- | --- | --- | ---: |
| Database 38 | original | insufficient_data | 0.59–0.67 |
| Database 38 | omit_blank_annotations | insufficient_data | 0.55–0.57 |
| Database 38 | one_affected_region | insufficient_data | 0.52–0.60 |
| Database 38 | missing_regions | insufficient_data | 0.60–0.63 |
| Database 38 | explicit_clock | insufficient_data | 0.56–0.68 |
| Database 38 | isolated_outcome | insufficient_data | 0.55–0.68 |
| Database 38 | missing_population | insufficient_data | 0.88–0.91 |
| Finance 74 | original | ignore | 0.68–0.72 |
| Finance 74 | omit_blank_annotations | ignore | 0.73–0.77 |
| Finance 74 | explicit_clock | ignore | 0.63–0.64 |
| Finance 74 | missing_watermark | insufficient_data | 0.52–0.61 |

The other three configurations asked only one database watch, without an outcome
question. `isolated_watch_0` selected unknown at 0.77–0.80;
`isolated_watch_1` selected present at 0.44–0.47; `isolated_watch_2` selected
unknown at 0.76–0.79. Each choice occurred in 3/3 repeats. Across the whole state
experiment, 24 calls selected insufficient_data, nine selected ignore and nine
had no outcome question.

Database watch 0 asks whether latency and lag share a population/reporting period;
watch 1 asks whether regional breadth is available; watch 2 asks whether gaps
limit the conclusion. In the original state, watch 1's present probability was
0.45–0.50; changing zero affected regions to one raised it to 0.61–0.65, while
removing the count raised it further to 0.83–0.85. Watches 0 and 2 still selected
unknown. This counterintuitive availability response does not prove that missing
regional data is acceptable.

Finance's required partition/cutoff watch never reached 0.70 present support:
0.49–0.61 on originals, 0.54–0.63 without blank annotations, 0.41–0.48 with the
clock, and 0.05–0.06 without the watermark. The explicit clock did not fix either
quiet case; source capture time still does not establish a reporting cutoff.

### Semantic experiment: all seven configurations

| Request | Variant | Raw selections | Outcome support |
| --- | --- | --- | ---: |
| Database 38 | original | insufficient_data 3/3 | 0.56–0.69 |
| Database 38 | state_semantics | ignore 3/3 | 0.72–0.78 |
| Database 38 | semantics_missing_population | ignore 3/3 | 0.61–0.64 |
| Database 38 | semantics_missing_regions | ignore 3/3 | 0.64–0.71 |
| Finance 74 | original | ignore 3/3 | 0.68–0.76 |
| Finance 74 | state_semantics | ignore 3/3 | 0.78–0.84 |
| Finance 74 | semantics_missing_watermark | ignore 1/3; insufficient_data 2/3 | ignore 0.52; insufficient_data 0.51–0.56 |

The semantic explanation improved both quiet outcome judgments: database changed
to ignore, and finance's ignore support exceeded 0.70 in all three repeats.
Required watches did not recover. Database watch 0 remained unknown with
0.68–0.74 unknown support and watch 2 remained unknown at 0.54–0.62; only watch 1
became present above threshold (0.72–0.75). Finance selected present for its
required watch, but its present support was only 0.51–0.58, below 0.70 in 3/3.
Thus an improved raw outcome is not a repaired evidence-completion path.

The missing-data controls are adverse evidence for promoting this explanation:

- Removing database population with semantics selected ignore in 3/3 repeats,
  at 0.61–0.64 (0/3 at or above 0.70), despite the owner's missing-coverage rule.
  Watch 0 still selected unknown at 0.88–0.89.
- Removing database regions with semantics selected ignore at 0.71, 0.64 and
  0.70 in repeat order (2/3 at or above 0.70). The regional-availability watch
  selected present at 0.86–0.90 even though the region count was removed.
  Other required watches remained unknown; these are not observed final ignores.
- Removing the finance watermark with semantics split the raw outcome as shown
  above; all selected outcomes were below 0.70. The required watch remained
  unknown at 0.86–0.88. In the first experiment, removing the watermark had
  selected insufficient_data in 3/3 repeats, with unknown watch support 0.88–0.89.

The semantic run selected ignore in 16 calls and insufficient_data in five;
these are response counts, not an accuracy score. Unchanged originals varied
between runs: database insufficient_data support was 0.59–0.67 then 0.56–0.69;
finance ignore was 0.68–0.72 then 0.68–0.76. A seeded, interleaved request order
does not make raw model distributions identical across repeated calls.

## Evidence and disposition

The [state archive audit](evidence/jev-v6-state-diagnostics-01/audit.json) and
[semantic archive audit](evidence/jev-v6-semantic-diagnostics-01/audit.json)
record source and archive SHA-256 hashes for each verbatim config/result and
compressed trace. The traces retain full edited states, questions, responses,
usage and request identifiers. Every result was matched to its trace response,
and each planned configuration/repeat was retained exactly once. Both configs
reference the same original v6 remaining-run trace hash and runner hash.

These are known-family component diagnostics on two already-failed requests.
The semantic experiment followed inspection of the state experiment; neither is
an independent acceptance set. Missing-value controls cannot inherit original
quiet labels, and raw selections do not certify final gating, reporting or
delivery. No prompt repair or clock change is being promoted to production from
these results. The 0.70 thresholds are not lowered, and required watches are not
waived. The v6 acceptance and narrative failures remain in the evidence.

### Input-parity review

The subsequent [cohort qualification](enterprise-onboarding-repair-v6-cohort.md#post-run-fairness-qualification-finance)
identifies a decisive missing fact in finance: the oracle and Luna use the public
period's reporting cutoff, but it is not supplied to native Jev. Adding a generic
evaluation clock is not equivalent. Publish the actual agreed cutoff in a new
source/fixture version before comparing native decisions again; do not infer it
from capture time. This finding qualifies the interpretation, not the retained
response counts or failures.

Replay reconstructs the audited JSON state and question dictionaries, not the
original SDK objects or a byte-identical HTTP request. Sorted serialization and
provider execution may differ. These are semantic-payload sensitivity tests;
distribution variation does not isolate provider nondeterminism from transport
representation effects.
