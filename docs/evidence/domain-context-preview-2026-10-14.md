# Domain-context preview evidence

Updated 2026-10-15. Feature branch: feat/domain-context-memory;
[draft PR #19](https://github.com/waddle-zoo/signal-weave/pull/19).
Main and the published rc3 download are unchanged.

## Conclusion

**No comparative business-value or enterprise-readiness claim is established.**
The latest agent-authored onboarding study stopped before either recurring
report or any Jev request. It exposed a simulated-expert context gap and a false
review objection, not a Jev policy failure. Earlier live decisions worked on
reviewed cards, but correct decisions did not consistently produce useful
human-facing analysis.

The [acceptance ledger](../domain-context-plan.md#current-acceptance-ledger)
keeps these gates separate. This note is the current summary, not a replacement
for the [immutable preceding record](https://github.com/waddle-zoo/signal-weave/blob/8a05bc84b9a9456c0b33078e6b3e941e79b314ba/docs/evidence/domain-context-preview-2026-10-14.md),
which retains prior results, negative findings, costs, identities and reproduction
limits. Runtime traces, credentials and native state stay outside Git.

## Latest agent-authored onboarding study

[Runner](../../evaluations/public_owner_report_trial.py), known Juniper Trail
Retail development fixture, seed 20261001; its generator's split name
`holdout` does not make it unseen data. Both arms retained the same company
sources, glossary, owner questions, calculator and notes. Treatment additionally
had the current native agent/context tools and installed canonical skill.
No archived expert card or approval was imported. These are normalized synthetic
company-MCP exports, not live vendor queries or real human participants.

Preregistered limits were six Luna-medium CLI invocations, one total Jev
attempt, and between-invocation stops at 1.2M input / 220k uncached tokens.
Thresholds do not cap an in-flight turn. Onboarding snapshots were explicitly
historical; reports would have fetched a later period. No sending or scheduling
was authorized.

1. **V1 stopped after the baseline author.** It saved correct free-form
   definitions, policy and synthetic owner consent, but noted that independent
   semantic review remained pending. The runner treated that procedural pending
   item as missing business context. This was a harness false stop.
2. **V2 reviewed that exact handoff without retrying the author.** A pinned
   manifest verified the original notes, consent, fixture and usage; the prior
   call counted against the same limits. Independent baseline review passed.
   Treatment still began with a blank native home.
3. **Treatment produced a policy-faithful draft and correct historical
   readout, but did not complete setup.** It asked what the primary source's
   “Eligible entities” population meant and whether `previous_period` durably
   meant the previous complete UTC week. The fake owner's fixed-topic lookup
   could not answer those free-form questions. Saved context remained draft;
   no card approval or recurring report followed.
4. **Treatment review also raised a false numerical objection.** It rejected
   `change_pct` because no separate reporting-registry fact defined it.
   Offline execution of the actual saved condition over the adverse period
   returns -30 percent and true. The runtime already defines relative percent
   change of comparison totals; a separate business metric is not required.
   The review contract now supplies that formula, units and preconditions.
   The stopped review is not rerun or rescored, and the real source questions
   remain unresolved.

| Accounted agent work | CLI calls | Input | Uncached | Output |
| --- | ---: | ---: | ---: | ---: |
| Original V1 baseline author | 1 | 109,390 | 31,310 | 2,178 |
| New V2 calls | 3 | 522,030 | 75,822 | 4,180 |
| Cumulative, including the prior author | 4 | 631,420 | 107,132 | 6,358 |

**Zero Jev calls and zero recurring reports.** This is not a baseline win, a
treatment success rate, or a cost/speed comparison. Independent diagnosis agreed
that the percent-change objection was false and the primary-source questions
legitimate. Optional refund-posting corroboration need not share the metric's
population unless actually combined into its calculation. Reviewer/coordinator
usage is separate and unknown.

The [handoff manifest](../../evaluations/data/public-owner-handoff-v1-manifest.json)
pins local audit artifacts; it is not a public replay bundle. The original
studies remain terminal. Their temporary homes were not retained, so another
study cannot claim continuity by importing an approval.

## Verified engineering changes

- Relative percent-change conditions now honor `absolute=true`. Eight
  cross-unit/direction cases include four reproduced pre-fix failures. Signed
  behavior is unchanged. This independent production bug did **not** affect
  the stopped draft, which used `absolute=false`.
- Caller-selected source/window provenance no longer attributes the caller's
  selection to Jev or claims an unobserved search.
- Semantic review now distinguishes executable numeric projections from
  business definitions. Its repaired prompt has offline coverage, not a new
  live approval result.
- The HTTP test mints synthetic curator credentials per session instead of
  reusing one short-lived token across a server restart. Production auth and
  invalid-token checks were not relaxed.

| Verification on current production code | Result | What it does not prove |
| --- | --- | --- |
| Full software suite and lint | 3,577 passed, 11 skipped; 409.72 seconds | Not companies or an efficacy estimate |
| Native stdio context lifecycle | Passed on the current binary | No agent report or provider call |
| Serial source/native skill and signed HTTP checks | 13 passed; 189.89 seconds | Synthetic issuer, not customer SSO |
| Public two-brief context walkthrough | Passed; four source reads, zero provider attempts | Scripted owner, not autonomous onboarding |

**Retained failures:** the first combined native run had 12 passes and two
failures: a 30-second skill-install timeout and a 401 when reusing the old curator
token after restart. The first concurrent public walkthrough also timed out.
Serial reruns passed; the token fixture changed as described above. These are
not one clean combined 14/14 run, and their causes are not all established.
A separate native build-info probe took 15.40 seconds. Startup reliability and
speed are not proven by successful serial reruns.

The current native build records commit
`5a9e0e2f69740dad88ec05853129e049ed95ad39`, source/skill fingerprint
`55013815a667dd4d893c5da4b95eaac00be33835a2c04fae6e50d8bb9e43a7a3`,
and executable SHA-256
`822a3b8a22037dfa91a1ab0fb4e5707d3ca91ba093980206b327cae0ce8debbf`.
It is not the published rc3 download despite the same package label.
Subsequent HTTP-fixture/document edits do not change that executable.

## What earlier studies established—and did not

All rows retain their original limitations; fuller accounting is in the
[preceding record](https://github.com/waddle-zoo/signal-weave/blob/8a05bc84b9a9456c0b33078e6b3e941e79b314ba/docs/evidence/domain-context-preview-2026-10-14.md).

| Study | Evidence and unresolved finding |
| --- | --- |
| Owner-handoff v4 | Two accepted synthetic setups after six calls; 189,300 uncached tokens stopped reporting before it began. Treatment revised one draft to approved v3. Its original temporary home was deleted; later restoration is not original-home durability. |
| Scripted approved-card clarification | Three live Jev calls matched insufficient_data, ignore and notify. Changed required meaning deferred policy while preserving source facts. Scripted owner and synthetic data, not conversational onboarding. |
| Paired report-only v1 | Three periods per arm; outcomes 3/3 each. Treatment used 7 tools/3 reads versus 15/5, but avoided handbook reads, not warehouse queries. Treatment used more uncached tokens and was slower in two periods. It incorrectly left volume unresolved despite counts rising 5,800 → 11,600. No comparative win. |
| Interpretation check | Three more treatment reports/live Jev calls had correct outcomes and receipts; raw structured score remains 0/3. Volume interpretation and typed fact-mapping defects persisted; recipient/citation scorer ambiguity also remained. |
| Grounded-reports v2 | Stopped after four of six reports and two Jev calls at 600,341 input tokens. Review packets omitted timing/recording context, making overall review pass rates unusable. No corrected pass rate claimed. |
| Human-readout canary | Recording succeeded, but one cached report still treated doubled counts as unresolved volume. Independent NO-GO stopped the planned six-report comparison. |
| Evidence-first layout pair | Two cached reporters, no source/Jev calls. Reviewers disagreed; no quality advantage or production promotion. Exact readouts and both opinions are in the [public excerpt](../../evaluations/data/evidence-first-layout-diagnostic.json). |
| First-message guidance | Three supplied-input drafts passed independent review with one minor Finance caveat. No baseline, native evaluation, source read or Jev call; communication checks only. |
| Public context walkthrough | Fresh public save/review/bind/approve operations; two briefs deliberately share one metric and anchors. Definition edit defers both and preserves evidence. Zero models, not independent discovery or business-value proof. |

Earlier invalid-schema, incomplete-handoff, stopped foreign-tool and stale-build
attempts remain documented, including unknown usage where present. They are not
pooled into success counts or relabeled as enterprise outcomes.

## Reproduction and audit

Run `make verify` for offline software contracts. The
[public native walkthrough](../domain-context.md#reproduce-the-synthetic-native-walkthrough)
needs no archived setup or live provider key. Native transport checks additionally
require the explicitly configured local synthetic Superset fixture on port 18089:

```sh
RUN_CONTEXT_CARD_INTEGRATION=1 SIGNALWEAVE_BINARY="$PWD/dist/signalweave" uv run pytest tests/test_context_native_card_integration.py -q
RUN_CONTEXT_HTTP_INTEGRATION=1 SIGNALWEAVE_BINARY="$PWD/dist/signalweave" uv run pytest tests/test_context_native_http_integration.py -q
```

The paid report cohorts require ignored runtime artifacts and cannot currently
be reproduced from public Git alone. The public layout excerpt has separate
arithmetic/disclosure checks in `tests/test_layout_diagnostic_fixture.py`;
these do not reproduce an agent study.

These SHA-256 identities identify local ignored files, not public inputs:

| Artifact | SHA-256 |
| --- | --- |
| V1 report | 836031c662996131d544a44375314a4f3bd0ffb8e87fbf040c88699b6302ca96 |
| V2 report | 5c15c5b7639209cc5bae9b27945367b98b6836b30e8567be8245be9434cec847 |
| Independent V2 diagnosis | cd1c0e7b37404ff0cd70493a3de953a013e190f68b0a8aef709e828712f9d54d |
| Serial native JUnit | 0d9d095ae7b5264c48f1c0f972ed4404f952e0f26b5a2e93104ebf9ecd9cd247 |
| Serial public walkthrough report | 634b7be2ffda1486d4e1487a18066b10842a5911d45b1a32c6906465386f5876 |

## Next acceptance gates

Before spending on another cohort: supply explicit fictional data-expert facts
about source population and reporting-window semantics, support free-form
clarification against that bounded reference, and preserve native state across
the handoff. Test both sufficient and genuinely missing context. Do not infer
semantics from a chart title, relax approval, or ask Jev to invent them.

Then freeze a new paired protocol and evaluate actual recurring messages:
useful scope/breakdowns, unsupported causes, quiet behavior, correct destinations,
misses/noise, complete setup/run costs and source work. Cross-card reuse,
changed-meaning agent behavior, multi-step investigations, varied real connectors,
interactive human onboarding, customer SSO and actual scheduling/delivery still
need evidence. Correct receipts and test totals cannot substitute for those gates.
