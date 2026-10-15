# Codex + live Jev bootstrap trial — October 1, 2026

This trial tests an agent starting from a business brief and supplied owner
policy, not a prewritten SignalWeave card. It uses the user's existing Codex
login; an OpenAI API key is not required. SignalWeave calls the live TypeSafe API.

## Result: onboarding is not ready

All 48 planned episode records were retained. The run finished without exhausting
the global budget or changing the frozen implementation. **SignalWeave completed
none of the six onboarding attempts**, so none of its 18 scheduled monitoring runs
could execute. This is evidence against the current easy-onboarding claim, not
evidence that Jev made 18 incorrect monitoring decisions.

| Observed endpoint | Codex/Luna + source tools | Same agent + SignalWeave/live Jev |
| --- | ---: | ---: |
| Completed onboarding | 6/6 | 0/6 |
| Completed scheduled monitoring | 18/18 | 0/18 |
| Correct outcome and recipients | 18/18 | Unassessed: no submissions |
| Exact structured passes / scheduled cases | 8/18 | 0/18 (setup blocked) |
| Total onboarding wall time | 154.32 s | 626.72 s |
| Completed monitoring median wall time | 25.40 s | Not measured |
| Codex invocations | 24 | 6 |
| Live Jev requests | 0 | 89 |

The baseline's 8/18 is a strict schema/numeric/provenance score, **not 44% arithmetic
accuracy**. Exact-key contract errors, unavailable metric definitions, incorrect
values and citation defects are mixed in that endpoint. The baseline's 18/18
routing result is also not proof that every explanation is correct.

| Synthetic company | Baseline setup | SignalWeave setup | Baseline exact monitoring |
| --- | --- | --- | ---: |
| Juniper Trail Retail | Complete | No structured completion | 1/3 |
| Harbor Workspace | Complete | 45-tool-call limit | 3/3 |
| Kindred Helpdesk | Complete | No structured completion | 2/3 |
| Cinder Database Cloud | Complete | No structured completion | 0/3 |
| Mosaic Exchange | Complete | No structured completion | 2/3 |
| Lumen Freight Finance | Complete | No structured completion | 0/3 |

All 89 Jev requests succeeded and resolved to `jev-1.13.0`. There were no foreign
agent-tool calls. One Codex invocation lacks terminal token usage. Known usage
estimates are $0.1081 for baseline and $0.1673 for treatment, including $0.01186
for Jev; treatment's estimate is incomplete. These are illustrative token-price
estimates, not actual subscription bills. No cost advantage is established.
Skipped monitoring is neither zero-cost successful work nor evidence of safety.
The six event-period investigations were not delivered by the treatment; the
scorer's zero observed wrong alerts must not conceal that missing service.

The preregistered onboarding and end-to-end quality gates failed. Repeated-run
benefit, enterprise adoption, and the wider product goal remain **unproven**.
No repair or additional paid retry was folded into this holdout.

### Evidence

- [Frozen configuration, usage and all 48 case results](evidence/bootstrap-codex-holdout-v2-01/results.json)
- [Public evidence and arm-metadata-blinded narratives](evidence/bootstrap-codex-holdout-v2-01/blind-review.json)
- [Review ID mapping](evidence/bootstrap-codex-holdout-v2-01/review-key.json)
- [Internal process, narrative and scoring reviews](evidence/bootstrap-codex-holdout-v2-01/reviews.md)

Dataset SHA-256: `5cced07c836ccb320a75c8f438079b480665b65ca8c7291c655edc4b803daacf`.
Full local report SHA-256: `5985ff36fc1c85bda7c531f46a96009b2c335e4c9c571fcdaeea6a39b2d32b92`.
Credential-redacted tool traces and original episode files remain under
`artifacts/bootstrap-codex-holdout-v2-01/`. The checked-in export contains synthetic
business data, not credentials or real company records. Export validation checks
the frozen fixture digest and reproduces the simulated clock. Review metadata is
hidden, but narrative wording may reveal an arm; this is not perfect blinding.

### Review qualifications

The blinded narrative reviewer assessed all 18 completed baseline outputs:
13 supported, three qualified, two with substantive unsupported assertions.
One asserted $11,000 where source arithmetic gives $10,000; another encoded
unknown SLA values as zero and invented a source annotation. No substantive
causal overclaim or unauthorized recommended action was found. These are internal
review judgments, not a separately validated accuracy metric.

A separate label-informed scorer audit explains the ten strict failures as:
one numerical-error case, four vocabulary/citation-only cases, four cases asserting
unavailable or unvalidated canonical quantities, and **one genuine label omission**.
The missing-current buyer fixture retains a valid 4,200-person baseline but omits
it from accepted numerical facts. Finance also needs explicit historical-baseline
freshness rules. The original 8/18 is retained, not repaired into a new headline;
it cannot be interpreted as arithmetic accuracy. These evaluator weaknesses do
not explain or remove SignalWeave's six setup failures.

## Design

The measured run is frozen at `8eb70f3de81a1085cad596cf57692a8e80488c47`.
See the [preregistered protocol](bootstrap-benchmark-protocol.md).

- Six synthetic companies: retail, SaaS, support, database operations,
  marketplace, and freight finance. Four assets per company.
- One setup and three later monitoring periods per company and arm: a quiet
  period, an event, and a data-quality or definition problem.
- Same requested `gpt-5.6-luna` model, low reasoning effort, source tools,
  calculators, owner answers and persistent notes on both sides.
- Treatment additionally gets production SignalWeave MCP tools and live Jev.
  Cards must be inspected, simulated and procedurally approved before use.
- No real messages, pages, database mutations or operational actions.
- Up to 45 tool calls and a 360-second Codex-process deadline per episode;
  a shared emergency ceiling of 210 Jev requests. Incomplete onboarding leaves
  its three scheduled monitoring runs in the denominator.

The company data are synthetic normalized exports served over a local MCP.
This does not measure a real warehouse, arbitrary BI connector normalization,
large-catalog retrieval, continuous months of operation, or real-human approval.
Every completed monitoring episode wakes the LLM on both sides. Dollar values
are illustrative API-equivalent token estimates, not measured Codex subscription
charges. Codex's internal inference requests/retries are not directly counted.

## Development ledger

All five development attempts were retained. Nothing was overwritten or counted
as free because it failed.

| Attempt | Finding |
| --- | --- |
| 01 | Disabling the Codex execution host also disabled MCP calls. No Jev calls. |
| 02–03 | MCP approval configuration prevented calls. No Jev calls. |
| 04 | Actual live Jev calls worked; untyped delivery arguments and chat-only owner questions prevented treatment setup. |
| 05 | Both agents completed setup for both development companies and all six monitoring periods. Both got six outcomes and six recipient sets correct. |

The original strict score for attempt 05 was 2/6 for each arm. Independent review
identified an unnecessary second-source citation requirement and an omitted valid
baseline fact. Scorer v2 corrects those rules for both arms before holdout, adds
public fact definitions, and retains invented-citation and unsupported-number
penalties. The original results are not rewritten or advertised as a win.

Development used 27 Codex invocations and 38 live Jev requests in total. The
combined illustrative token-price estimate was $0.2081; this is not a billing
statement. Development tuning is separate from the measured holdout.

## What changed before the measured run

Product changes are small: typed delivery/source schemas and enum inputs on
the three card-authoring MCP tools, plus an injectable freshness clock for
reproducible simulations. There are no scenario-specific production branches.
The Codex transport, fixtures, scorer and review exports remain in `evaluations/`.

Independent internal agents reviewed isolation, budgets, scoring and production
schema boundaries. Regressions include validation-before-mutation, nonfinite
arguments, call limits, source/citation isolation, fixed clocks, unknown usage,
and blinded review exports. Full verification passed **1,024 tests**, with three
separate integration skips. These tests validate contracts, not business accuracy.
After adding fixture-digest and review-clock export regressions, final verification
passed **1,026 tests**, with three skips. All eight frozen source-file hashes still
matched after the run. Postprocessing/docs changes did not alter trial execution.

## Internal adversarial findings

A separate read-only agent reviewed the frozen code and sampled failed onboarding
traces. Its findings distinguish three problems:

1. **A title collision can strand approval.** Candidate review groups resources by
   adapter, normalized title and domain. Distinct resources with the same title
   can produce a `definition-conflict` even after the agent selects the intended
   source. Production approval rejects that review state. Retail's preview and
   simulated owner approval succeeded, but production approval did not.
2. **Correction choices are not discoverable.** The correction MCP tool advertises
   a string although implementation requires an enum. The agent repeatedly guessed
   invalid values. Accepted feedback is append-only; discovering a valid value
   would not itself clear the approval blocker.
3. **Some failures are procedural.** SaaS attempted approval without the harness's
   current-card owner receipt. This is an agent failure under a disclosed simulated
   review requirement, not evidence of the same production defect in every case.

The sampled retail preview assigned the duplicate distractor relevance 0.05 and
omitted it. That does not show Jev choosing the wrong resource. Failed setup then
prevented scheduled monitoring entirely: those runs are end-to-end availability
failures, with Jev decision quality and narrative safety **unassessed**.

The next product experiment should expose the correction enum and provide an
explicit, provenance-bearing resolution of a specific source ambiguity. Resolution
must be bound to the reviewed card/catalog version and revalidated on change—not
a free-text bypass of source health or authorization. These are proposed repairs,
not fixes validated by this frozen run. Any follow-up is a new evaluation version.

## Reproduction

```sh
codex login status
uv run python -m evaluations.bootstrap_agent_trial \
  --agent-transport codex --jev-key-file /absolute/path/to/typesafe.key \
  --split holdout --limit 6 --max-api-requests 210 --max-tool-calls 45 \
  --output artifacts/bootstrap-codex-holdout-v2-01
```

Use a new output directory for every attempt. Full traces and episode records
are retained locally with credential redaction. A replay makes new paid model
calls and can produce different results. Model confidence is not a correctness
guarantee. Internal adversarial review is not external peer review.
