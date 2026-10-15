# Why the recurring-report benchmark failed

This investigation tests mechanisms, not a predetermined success story. The
[earlier paired trial](business-outcome-trial.md) remains **10/12 versus Luna's
12/12**. No result below replaces that denominator.

## Conclusion

**Do not ship the experimental composition layer.** On the twelve new transfer
cases, the direct Jev outcome question and Luna both matched the frozen policy
labels 12/12. The separately code-composed path matched only 8/12. More narrow
questions and more Boolean structure did not improve reliability here.

The four strict-score deviations are inspectable confidence-gating interactions:
the selected subanswers agreed with the fixture labels, but were below the
unchanged 0.70 support floor. One comparability label is disputed in narrative
review; the other three cases clearly forced an irrelevant exception review.
That is not a reason to lower the threshold after
seeing the answers. It is a reason to distinguish model uncertainty from missing
source data and to avoid requiring answers from inapplicable branches.

The direct Jev result is a **typed decision result**, not a separately executed
final-report arm. It received reviewed policy context and code-computed numeric
checks, not the older production input unchanged. It does not prove that the
shipped runtime is repaired, that Jev universally beats Luna, or that the full
product saves cost or human time. The candidate changed several input/design
factors together; this study does not isolate which one improved direct outcome
selection relative to the original production trial.

## Measured results

| Experiment | Luna report decision | Direct Jev decision | Composed Jev report decision |
| --- | ---: | ---: | ---: |
| First-pass generated plans, 12 development cases | 11/12 | 11/12 | 9/12 |
| Reviewed plans, 12 new transfer cases | 12/12 | 12/12 | 8/12 |

The narrative reviewer flagged one transfer oracle assumption: a shared weekly
population and settled-order definition do not literally assert regional
population comparability. Both the intended notification and a cautious data-gap
response are defensible readings. The original scores above remain frozen.
Excluding that disputed case gives **11/11, 11/11 and 8/11**, respectively. It
must not be presented as four indisputable errors on fully unambiguous cases.

All six transfer report episodes completed. The composed path missed two required
business notifications under the original labels (one disputed) and unnecessarily
routed two quiet cases for review.
It did not send a false business notification, but that must not be presented as
zero unnecessary alerts: review destinations also create work for people.

| Transfer recurring resources, including final prose | Luna baseline | Composed Jev + Luna |
| --- | ---: | ---: |
| Total episode time | 111.2 s | 116.1 s |
| Source reads | 12 | 12 |
| Agent tool calls | 25 | 24 |
| Luna uncached input tokens | 55,489 | 49,886 |
| Luna output tokens | 2,906 | 2,800 |
| Additional Jev input / output tokens | — | 22,177 / 2,184 |

The composed path used less uncached Luna input but took 4.4% longer and was less
correct. There is no useful end-to-end win here. The 2.49 seconds of Jev requests
are already inside the composed episode time; they must not be added again or
compared with Luna's complete reports as if they measured the same task. They
include both broad and narrow experimental questions, not separately measured
Jev arms. Prices, warehouse latency, customer effort and human hours were not
measured.

### Failure trace

- A regional-comparability check selected `true` with 0.63 support. Code changed
  it to `unknown`, which the reviewed plan treated as a data gap. The direct
  outcome selected the required notification with 0.90 support on that same
  request. This is agreement with the fixture, not independent certification of
  the real-world comparability of two populations.
- Three delivery cases explicitly had no weather exception. The exception-conflict
  check selected `false` with 0.57, 0.62 and 0.59 support; code converted each to
  `unknown`. Mandatory conflict handling then forced investigation even when
  the exception branch was inapplicable. The direct outcome correctly selected
  notify/ignore/ignore with 0.99/1.00/0.99 support.
- An offline counterfactual consuming every recorded top-1 subanswer yields
  12/12. That localizes the gating effect; it is **not a repaired live result**,
  safe confidence policy, new model evaluation, or permission to bypass review.

The corrected arm-masked AI review judged 12/12 baseline narratives usable and
8/12 composed narratives usable, accepting either interpretation of the disputed
retail case. Preferences were baseline 9, composed 2, tie 1; this is one internal
AI reviewer, not a human preference study. One report with a correct structured
data-owner route still added an unsupported exception-conflict caveat and asked
for unnecessary exception records. The original reviewer mistakenly described
that route as wrong; its initial review and factual correction are both retained.
Typed correctness and faithful final prose therefore need separate tests.

### What to pursue, and what to reject

Keep the narrower existing contract: owner policy, validated numerical facts,
a bounded typed Jev decision, and a caller-owned agent. Test a compact
code-computed-condition projection in the real runtime before adding a new
execution language. Do not generalize this experiment's plan schema into a new
production abstraction on the strength of these results.

Onboarding must check policy semantics, not just JSON/schema validity. Include
quiet cases, each alternative trigger, conjunction failures, missing evidence,
source-precedence overrides and unused branches. Separate a known source gap
from uncertainty in a semantic judgment, and expose that distinction to the
agent rather than making it narrate the uncertainty as an observed fact.

The next promotion gate is a prospective, full-runtime comparison using that
smaller design, including the final writer and approved review handoffs. The
direct-outcome 12/12 here is motivation for that test, not a substitute for it.
No production source files were changed and nothing was merged into main.

## Hypotheses and frozen boundaries

1. **State sensitivity:** the old requests duplicated the card and observation
   fields and included a plan whose evidence slots still said `pending`.
   Replay six known failure/control inputs in three arms: retained original
   state, remove exact duplicate aliases, or remove the plan. Questions,
   evidence, business policy and confidence floor stay unchanged. Plan removal
   removes unique context as well as pending slots; it is not deduplication.
2. **Composition:** compile plain-English policy once with Luna, before seeing
   measurements. Code handles catalog-bound numeric comparisons and explicit
   ordered Boolean rules; live Jev handles narrow semantic conditions. Compare
   this with a broad Jev outcome judgment and a persistent Luna reporter given
   the same policy, compiled plan, evidence and numeric checks.

The second experiment is an evaluation-only prototype. It does not introduce
a production policy language, change card approval, or claim that generated
plans have been semantically approved. A syntax-valid plan can still be wrong.

The current [TypeSafe guidance on Jev's limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
recommends exact numeric operations in code, direct conditions, relevant state,
and code-enforced composition rather than assuming consistency between separate
judgments. That motivates the experiment; it does not predict the result.

## Predeclared fresh-company experiment

Twelve cases across three new synthetic companies cover OR/AND conditions,
offsetting movements, directional increases, exceptions, conflicting authority,
missing data and qualitative contract-release checks. A separate agent authored
the fixtures and explicit labels before live outputs; another offline audit
recomputed their measurements. This is internal AI review, not human peer review.
The labels are AI-authored test expectations, not customer historical decisions
or independent human-expert judgments.

- Three Luna setup episodes see only policy and a typed measurement catalog.
  They never see case facts, labels or descriptive case IDs. All plans are saved
  before recurring episodes begin. No manual plan repairs or retries to success.
- Six recurring Luna episodes: one persistent baseline and one writer per
  company, four sequential periods each, counterbalanced arm order.
- Twelve Jev requests maximum. Each contains independent narrow questions and
  one broad outcome question over the same state. The broad answer cannot see
  the narrow answers; only the code-composed result reaches the treatment writer.
  This measures composition, not isolated per-arm Jev latency.
- Numeric checks use the same catalog fields and operators for both arms.
  Unknown is not false. An unresolved earlier rule cannot silently fall through
  to a later automatic action. The unchanged semantic support floor is 0.70.
- Both reporting arms read each period once, reuse that bundle and cite the same
  fact IDs. Recipients are bound to policy-owned routes equally in both arms.
  No actual notifications or queries against customer systems occur.
- Report all twelve intended cases, including missing submissions. Review plans
  and final narratives separately. Citation/schema validity is not truth.
- A product advantage requires correct reports and lower whole-workflow cost or
  time, not just fast Jev calls. Report setup and recurring usage separately.
  Tokens are not dollar invoices, and source reads are not human hours saved.

These cases do not test retrieval from a large catalog, unknown source schemas,
warehouse execution, customer onboarding, drift or production authorization.
There is only one live observation per case. Even a perfect result would be a
bounded mechanism result, not enterprise readiness or universal superiority.

## Reproduce

Without `--live`, both commands prepare manifests without credentials or calls.
Use a new output directory each time; all failed attempts remain available.

```sh
python -m evaluations.judgment_input_ablation \
  --primary docs/evidence/business-outcomes-live-01 \
  --output artifacts/judgment-input-ablation-new
python -m evaluations.policy_composition_trial \
  --output artifacts/policy-composition-new
```

For live runs, add `--live --jev-key-file /path/to/private/key`. The second
command uses the locally authenticated Codex CLI for Luna, with a scoped
localhost MCP and no shell, workspace, web or private-label access.

## Results

The retained state ablation produced 3/6 gated outcomes for original structured
inputs, 4/6 after exact-alias removal, and 3/6 after plan removal. Neither old
miss cleared in any arm. This is not a demonstrated cleanup fix. Historical
requests were reconstructed from canonicalized journals, not original wire
bytes; key order may differ. Both histories report `jev-1.13.0`, but neither pins
a provider implementation. Probability differences are not attributed to one
cause. The initial DNS-failed attempt is retained separately as infrastructure
failure, not a model accuracy result.

The first composition run completed every report: baseline **11/12**, broad
Jev **11/12**, code-composed Jev **9/12**. The initial three CLI startups failed
locally before model output; the identical permitted rerun is the measured run.
The policy-only reviewer found defects in all three generated plans. In the
quiet retail case, every semantic/numeric check was correct, but the plan's
default routed to investigation. Blind execution of a syntactically valid plan
is therefore not a solution. Setup took 97.1 seconds; recurring baseline reports
took 124.5 seconds versus 138.0 seconds composed. Neither correctness nor
whole-report resource advantage passed.

### Bounded review/repair transfer protocol

Before further calls, the plan reviewer repairs the plans against policies and
catalogs only. Another agent independently freezes twelve new transfer cases;
the plan-repair agent does not inspect those cases. An initial review draft with
an overbroad unknown-to-investigate guard was rejected and retained. Revised
plans must pass abstract policy truth-table checks before live execution.
This includes assistant review intervention, not unattended first-shot onboarding.

The final transfer budget is **12 Jev requests and 6 Luna report episodes**,
with no new author episodes in that runner. Both reporting arms get the same
reviewed plans. Recurring costs are measured; policy-review/repair subagent costs
are not measured by the runner and must not be treated as free onboarding.
Cases cover new values, wording and branches of the same three policies, not
three additional enterprises. Ambiguous combinations of approved exceptions
and missing data are explicitly outside this bounded transfer claim.

```sh
python -m evaluations.policy_composition_trial \
  --reviewed-plans evaluations/data/policy-composition-reviewed-plans.json \
  --output artifacts/policy-composition-transfer-new
```

Research code, experiment plans and fixtures stay outside `src/`; the shipped
runtime remains unchanged. The transfer result does not replace either failed
primary experiment.

## Evidence and usage

- [State ablation](evidence/judgment-input-ablation-live-02/report.json)
- [Failed first-pass composition](evidence/policy-composition-live-02/report.json)
- [Frozen transfer manifest](evidence/policy-composition-transfer-live-01/manifest.json)
- [Transfer reports and raw decisions](evidence/policy-composition-transfer-live-01/report.json)
- [Internal method review](evidence/policy-composition-transfer-live-01/method-review.json)
- [Arm-masked narrative review](evidence/policy-composition-transfer-live-01/prose-review.json)

This investigation completed **42 Jev requests and 15 Luna trial episodes**:
18 Jev ablation requests, then 12 Jev / 9 Luna in the first composition trial,
then 12 Jev / 6 Luna in transfer. It also retains 18 locally DNS-failed Jev
attempts and three locally failed Codex startups, with no returned provider
usage for those infrastructure failures. They are not semantic scores or
assumed free provider usage. Fixture, code-review and policy-repair subagents
are outside those measured trial totals; their usage is not known here.

Final offline verification: **1,877 tests passed, 3 skipped**, Ruff clean and
`git diff --check` clean. Recorded-evidence tests independently recompute the
reported decision counts, check the private-label boundary, retain failed
denominators, and verify the [archive checksums](evidence/policy-composition-checksums.json).
These are software/evidence-integrity checks, not additional live model trials.
