# Human and agent workflow study

Status: **independent method review complete; design remains unexecuted and not admitted for paid expansion**.
This is the next research plan, not a new performance result. Keep earlier
cohorts, including failures and environment-censored attempts, unchanged.

Review disposition: adequate as a staged research roadmap, not an execution
approval or a power assessment. A bounded review of the synthetic available-
history projector found a daylight-saving fold ordering defect. Three regressions
first reproduced early correction/deletion/event visibility; UTC-instant
comparisons repair it, with scoped code-review closure. The helper remains
fixture projection only, not a source adapter, state reconstruction, business
oracle, or tenant boundary.
The time-ordering repair follows [PEP 495's intra-zone comparison guidance](https://peps.python.org/pep-0495/#temporal-arithmetic-and-comparison-operators).

## Question and product boundary

Does adding SignalWeave to a capable BI agent make it easier to establish and
repeat useful analytical workflows, with less human inspection and no loss of
important findings? Where does it instead add effort, cost, or noise?

The intended intervention remains cards, reusable context, source evidence,
narrow typed policy decisions and workflow handoffs. The frontier agent owns
discovery, analysis, SQL, causal hypotheses and the human message. The caller
owns schedules and delivery. Do not add a scheduler, agent builder, mandatory
report-publication pass or a general analytical engine to make this study pass.
Use live Jev for the primary treatment's policy judgments; offline fixture or
transport checks are not substitutes for those judgments.

## What the research changes

| Source | Application to this study |
| --- | --- |
| [Anthropic: agent evaluations](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | Inspect final environment state and messages as well as traces. Use deterministic checks for factual claims and calibrated reviewers for usefulness; allow valid alternative analytical paths. |
| [τ-bench](https://arxiv.org/html/2406.12045v1) | Include ordinary-language owner interaction, tool state and repeated fresh attempts. Measure consistency, not best-of-many success. Simulated owners remain simulations. |
| [Spider 2.0](https://arxiv.org/html/2411.07763v2) | Test source discovery, conflicting definitions, project context and multi-query analysis, not just reading normalized chart values. Preserve source/schema complexity without asking Jev to perform that reasoning. |
| [AI Agents That Matter](https://arxiv.org/html/2407.01502v1) | Use a strong inexpensive baseline, holdouts, and complete accuracy/cost/time accounting. Include setup and correction costs rather than only the narrow provider call. |
| [Microsoft: trustworthy experiments](https://www.microsoft.com/en-us/research/articles/patterns-of-trustworthy-experimentation-pre-experiment-stage/) | Define falsifiable hypotheses, data-quality checks and the correct unit of comparison before execution. |
| [NN/g: quantitative usability sample sizes](https://www.nngroup.com/articles/summary-quant-sample-sizes/) | Separate formative usability discovery from population-level success-rate claims; justify sample size against desired precision. |

These studies motivate the design; they do not validate SignalWeave or prescribe
the counts and acceptance targets below. Those are proposed engineering/product
choices, subject to the independent method review and budget gate.

## Three evidence tracks

1. **Human usability:** a person follows the actual public installation and
   setup instructions, connects a source, then works with their agent. Observe
   where they get stuck, misunderstand a card or cannot assess the proposed
   output. A scripted terminal or LLM playing the owner is not a participant.
2. **Business workflow simulation:** fresh agents onboard separate fictional
   companies through the real native/default-profile MCP, then repeat workflows
   over changing source states with live Jev in treatment. Score final reports,
   useful silence, missed issues and completed shadow-delivery handoffs.
3. **Source/transport validity:** test actual local services separately from
   simulated vendor APIs. Verify extraction, SQL, tenant/credential lifecycle,
   reconnect and the source evidence the business test actually consumed.

Passes in one track cannot replace missing evidence in another.

### Real-person sessions

Propose six formative participants unfamiliar with implementation: three people
who can install/connect tools and three business leads working with a supplied
configured source. Record prerequisites and assistance; do not pretend a lead
who needs an administrator's connection has completed self-service installation.
This small purposive panel discovers friction, not an enterprise adoption rate.
Recruitment and participant consent are still required; none are enrolled yet.

Observe installation/help/health and credential repair; first useful readout;
clarification and exact card review; then understanding a concise alert, an
ordinary digest and a partial-data investigation. Ask recipients what changed,
what is established versus hypothetical, who acts and what happens next.
Record active effort, abandonment, mistaken assumptions and facilitator help.
Do not guide them through undisclosed fixes or exclude assisted failures.
For comparisons, counterbalance matched tasks/order and retain learning effects;
do not call repeated sessions with one author independent participants.

Owner simulations have bounded knowledge: business intent, exceptions and who
owns a decision, not the hidden arithmetic answer or ideal asset IDs. They must
be able to misunderstand, be unavailable or contradict old notes. Review the
simulator's replies for policy/answer leakage and impossible expertise. Replaying
the same fixed owner statement is a separate reproducibility control, not proof
of successful conversational onboarding. A model's approval is not human consent.

## Scale and sampling

Start with a formative wave of four company journeys, two workflows each and
three later observations per workflow: **24 paired recurring observations**.
Use Northstar and Harbor only as known development cases. They do not become
unseen holdouts through a new seed or renamed dashboard.

After repairs and a new frozen method, target **12 newly authored company
environments, six domains, two workflows per company and 12 observations per
workflow**: **24 workflows and 288 paired recurring observations**. This means
24 primary onboarding journeys across two arms and up to 576 recurring agent
episodes, not 288 independent companies. A legitimate decision-first quiet path
may avoid a treatment frontier episode; record that skip and its Jev/source cost.
Use eight observation points for ordinary cadence and four for distinct
workflow continuations such as a follow-up, recovery, feedback or definition
change. A continuation advances time/state; it is not another independent trial.

Use six prespecified sentinel workflows for three independent fresh-onboarding
repetitions **per arm**, each followed by the same three-step trajectory
(ordinary observation, issue, follow-up). This separate reliability cohort has
36 arm-specific onboardings, 54 paired later slots and up to 108 recurring arm
episodes. It measures repeatability of those short workflows, not 12-week fleet
reliability. Do not treat its dependent steps as independent repetitions or
merge it into confirmation. Each cohort needs its own budget and admission.

Balance small/large catalogs and simple/messy organization structures within
domains. Proposed catalog tiers are 100, 1,000 and 10,000 inspectable assets,
with independent data shapes, not just copies with new names. Record actual
materialized counts, search behavior, query/result sizes and relevant-asset
recall. Virtual catalog load is a separate load test, not agent adoption proof.

Large coverage is not automatic statistical power. The company trajectory is
the primary paired cluster because workflows share definitions, people and
source failures. Report domain and company results, not only a pooled period
percentage. Twelve purposively designed companies cannot establish a universal
enterprise success rate. Before confirmation, assess precision under plausible
within-company dependence; increase independent environments or accept an
inconclusive result rather than manufacture significance through more weeks.

For scale intuition only: if independent, identically sampled company journeys
had zero failures, the one-sided 95% upper failure bound would be
`1 - 0.05 ** (1/n)`: 22.1% at 12 journeys, 11.7% at 24, and 4.9% at 60.
Counting 288 correlated periods as independent would misleadingly suggest
about 1.0%. These are planning calculations, not confidence bounds on the
purposively authored synthetic companies or observed SignalWeave reliability.

## Business tasks, not just metric alarms

Each company gets one recurring brief and one related investigation workflow.
Scenario authors must supply the question, data, owner knowledge boundaries,
available sources and acceptable conclusions before either acting agent runs.

| Domain | Recurring question | Investigation / human outcome |
| --- | --- | --- |
| Retail / commerce | What changed in online sales and its contribution to net sales? | Separate traffic, purchase conversion, refunds and channel mix; involve Analytics/Data Trust before Leadership when the cause is uncertain. |
| Subscription software | Which customer cohorts need attention this week? | Distinguish renewal exposure, usage, account maturity and support patterns; produce a short CS action list, not a company-wide alarm for a tiny cohort. |
| Support operations | Is customer support getting materially worse? | Separate resolution from first response, weighted populations, open backlog and incomplete ingestion; route supported service issues and data gaps appropriately. |
| Logistics / inventory | Where will delivery commitments or stock availability fail? | Join orders, promised dates, inventory and carrier events without double counting; communicate the affected commitments and next owner. |
| Finance / commercial planning | Are actual results off the agreed business course? | Separate booked, recognized, billed and collected amounts, currencies and close completeness; explain supported drivers without substituting one definition for another. |
| Service operations | Is there a broad customer-impacting performance regression? | Combine latency, lag, throttling, deployments and regional concentration; an isolated CPU spike is not sufficient, and temporal association is not proven causation. |

Two company environments in one domain must differ materially: source systems,
business policy, organization, grain, reporting cadence or missing evidence.
Do not reuse one metric formula and relabel it as six industries.
Include quality-held manufacturing lots in the inventory domain and settlement
reconciliation in finance: neither should collapse into a generic revenue alarm.

## Required workflow stressors

Distribute these across the matrix rather than forcing every nuisance into
every case. Include both positive and negative controls.

- Clear first use with an owner who knows the business but not asset IDs.
- Two plausible definitions or populations; a focused clarification resolves it.
- Unresolved ambiguity: deliver supported partial facts and ask, without a false
  all-clear or withholding the entire useful answer.
- Complete data with an important adverse movement, and complete data with an
  ordinary or beneficial movement. Correct quiet behavior must be observable.
- Planned promotion, migration or approved exception that changes interpretation.
- Segment-mix reversal, zero/small denominators, nonadditive rates and overlapping
  entities. Appropriate caution must not suppress a large supported impact.
- Late data, partial periods, backfill and correction; separate real deterioration
  from incomplete measurement and distinguish recovery from repaired history.
- Similar chart names, archived definitions, forecast versus actual, untrusted
  source text, pagination, and an unusual table/multi-series chart shape.
  A query-lineage canary must tie evidence to the actual query/version used,
  including similarly named queries with different ancestry; provenance success
  alone is not user-benefit evidence.
- Required evidence missing versus optional context missing. Report available
  facts, withhold only the affected conclusion and choose the useful next step.
  Owner-authorized urgent provisional warnings may still be useful; do not make
  an unrelated data gap veto a supported customer-impact notice.
- Multi-step investigation: contribution breakdown, competing explanation,
  follow-up evidence, then a compact message to the appropriate teams.
- Feedback that corrects a definition or audience, plus feedback that is only a
  preference or an unverified hypothesis. No silent policy rewrite.
  Wording feedback or an ambiguous “looks good” is not blanket approval to run
  or deliver. Confirm the displayed policy/source scope; a concurrent revision
  must invalidate the pending approval rather than substitute unseen changes.
  Accept clear ordinary-language assent in context; do not require a magic
  phrase, schema knowledge or hand-written JSON from the human.
- Owner change, repeated incident, acknowledgement, quiet recovery, process
  restart, new run key versus receipt replay, and changed source definition.

Missing context is not a test that Jev can invent business intent. Evaluate
whether the agent obtains the missing information and saves a repeatable brief.
Allow bounded owner/expert correction as part of onboarding, count its effort,
and keep cold-start outcomes separate from expert-repaired card execution.

## Data and oracle requirements

Use raw records plus source-owned views, documents, notes and discoverable
charts. Saved queries and semantic definitions may be realistic company assets,
but both arms receive access to them and their preparation cost is disclosed.
Never emit expected routes, scenario labels or private grader answers into the
catalog, source snapshots, skill or agent opening prompt.

Operational recurrence requires event time **and availability time**. Append
state/definition revisions and expose only information available at each run.
Resolution, refunds, ingestion and ownership changes must become visible when
known, not when the final warehouse eventually contains them. The current Harbor
fixture is retrospective and cannot establish that property by filtering cohorts.
Keep immutable input/result hashes for each observation; cache state and query
settings must be comparable between arms or the affected comparison is unqualified.
Publish the same explicit business/run clock to both arms. Enforce the visible
cutoff at the source boundary: arbitrary read-only SQL must not reveal future
versions or hidden grader tables. Filtering only the final prompt is inadequate.
The event-projection helper alone does not prove that connector boundary or
reconstruct ticket, order or account state; test those integrations separately.

An independent reference implementation recomputes consequential quantities
from visible raw records, not production normalizers, source views or the
scenario's generator helper. Check reconciliation and boundary dates before
agent admission. Define acceptable findings and alternative supported paths;
do not require a particular SQL string, tool sequence or wording.

Two domain reviewers independently assess definitions, intended policy and
material claims before freezing the task. Preserve disagreement; mark a task
ungradable when its evidence cannot support a verdict. Authoring and grading
roles must not share hidden answer keys with the acting agent.
Freeze the confirmation case roster before any confirmation agent preview;
independent scenario authors must not select cases based on treatment success.
New companies within reviewed families are new environments, not unseen domains.
If a fixture or grading defect is found after admission, retain its original
record and handle a corrected cohort separately instead of replacing its score.

## Fair comparison

Primary baseline: the same frontier model/effort with all the same company BI
and SQL tools, source documentation, owner interaction, durable notes, calendar,
calculation and shadow-delivery capabilities. Give it a strong general BI skill
covering the same analytical checks, not a deliberately weak prompt. Both arms
may retain reviewed definitions/policy. Treatment adds SignalWeave's native
default-profile MCP, canonical skill/cards/context/receipts and live Jev.
Do not force the baseline to forget its work, re-read every chart or wake an LLM
when its own reviewed saved query/script can legitimately complete a quiet check.
Both arms may batch queries and save safe reusable analysis helpers under the
same workspace/source constraints. Record authoring/maintenance cost for those
helpers. Include a separately labeled ordinary-agent-workspace compatibility
slice: the locked research transport must not be the only evidence for how a
person's normal Codex/Claude setup behaves. Keep private grader/future-source
files inaccessible even when safe workspace calculations/scripts are permitted.

Separate two estimands:

- **Cold start:** independently onboard from the same initial business question
  and source access; measure each arm's actual clarification and repair burden.
- **Recurring execution:** use equivalent reviewed meaning/policy and source
  scope, preserve each arm's durable artifacts and compare future outcomes.
  A separate equal-card execution slice can isolate reuse; do not attribute its
  expert preparation to successful automatic onboarding.

Randomize/counterbalance arm order within company and isolate homes, agent
memory, output directories and mutable source/delivery state. Freeze model,
binary/source/skill fingerprints, fixture and actor/tool budgets. Do not share
treatment discoveries with baseline after one arm has started. Reset mutable
sources to the same available state, while preserving the arm's own prior work.
Record genuine product errors separately from environment/harness failures;
both remain visible in the attempted-workflow denominator.
For each failure, identify the first supported divergence: source/availability,
retrieval/definition, owner clarification or card, frontier analysis, typed policy
or runtime routing, final message, or delivery. Preserve the actual arguments,
evidence and expected owner intent. Do not blame Jev for absent context, excuse a
wrong message because the receipt is valid, or blame SignalWeave for a broken
test environment. Root-cause classification does not erase the failed outcome.

## Outcomes and review

Primary quality endpoint: **useful completed workflow at the required cadence**.
For an actionable case, this requires correct material facts, scope/comparison,
justified interpretation, appropriate recipient/next step and a concise human
message with inspectable evidence. For a quiet case, verify the check completed
and no unrequested interruption occurred. Abstention alone is not success.

Report separately, rather than hiding them in a single weighted score:

- Onboarding completion, active owner/expert time, clarification turns, corrections,
  time to first useful answer and first reviewed repeatable workflow.
- Important-event recall, unnecessary interruptions, precision among actual
  notifications, missed important events and time to supported notification.
  No notifications means precision is undefined, not 100%.
- Supported investigation findings, material factual/causal errors, useful next
  steps, recipient correctness, concision and recipient comprehension.
- Recurrence reliability, duplicated delivery, stale-context handling and the
  effect of feedback/review without unapproved policy drift.
- Setup + recurring + investigation + review cost/time, tool/query counts, source
  bytes, provider attempts, input/cache/output tokens and known/unknown billing.
  Report real query latency separately from any modeled three-minute warehouse
  queue. Parallel simulated delays are not observed Trino performance.

For the proposed confirmation endpoint, average the 16 ordinary-cadence binary
completion scores (two workflows × eight observations) within each company;
compare treatment minus baseline across the 12 company clusters with equal
company weight. The eight continuation slots per company are a separate
investigation-quality guardrail, not an implicit one-third primary weight.
Report important misses, harmful errors and wrong-recipient messages separately;
easy quiet cases cannot offset them. Keep scheduled slots, attempted/completed
model episodes, legitimate quiet skips, product failures, environment failures
and ungradable cases as different counts. Never recode an unfinished run as quiet.

Before confirmation, propose and freeze a quality noninferiority margin (initial
candidate: five percentage points on that completion endpoint) and a primary
practical benefit (initial candidate: 20% fewer unnecessary interruptions with no
important-event recall loss). These are product targets, not achieved results
or automatically powered tests. If baseline has no unnecessary interruptions,
relative reduction is undefined and cannot be declared a win. Report cost/time
as prespecified secondary outcomes, not a replacement primary chosen afterward.
Assess paired-effect precision using company-level variation; the IID planning
bound above is not that assessment. An interval too wide for the chosen margin
cannot establish noninferiority, even if point estimates look favorable.

Deliberately balanced challenge cases do not estimate production alert precision.
Report their exact mix and challenge-set precision/recall; add a separately
justified operational-prevalence replay before projecting expected alert burden.
Treat domain/stressor analyses as exploratory, publish all planned strata and
do not promote an isolated favorable comparison to the primary conclusion.

Use code for independently verifiable arithmetic, source-state and delivery-sink
checks. Review redacted final messages blind to arm and in shuffled order with
two separate product/domain reviewers; inspect source results and traces when
needed. Record disagreement and reasons; model consensus is internal review,
not peer review or human validation. Actual people must calibrate comprehension,
usefulness and onboarding-friction judgments before making human-usability claims.
Budget review explicitly: two ratings for all 576 possible confirmation messages
is up to 1,152 ratings, before onboarding reviews and adjudication. Also audit
all quiet skips against source/check evidence. Freeze any review subsampling,
calibration set, disagreement procedure and grader budget before admission;
never select only impressive messages. Research-grading cost is reported
separately from owner effort during operation. Count required operational
expert review in the product's total effort; do not assign simulated minutes to
LLM owners. Unknown billing stays unknown, with no dollar-savings claim from
token counts alone.

The simulated delivery sink must store the actual destination, message, source
references, run key and acknowledgement state from both arms' tool calls. A
message merely proposed in prose is not a delivered shadow message. Shadow
delivery proves that local handoff only, not real Slack/email delivery or
actual on-call acknowledgement. Test a real external sink separately under
explicit authorization; do not contact real colleagues for a simulation.

Report paired company-level differences and uncertainty, including failures,
censoring and missing usage. Do not pool development, confirmation, reliability
and user-panel results. Prespecify a practically meaningful benefit and quality
guardrails before seeing confirmation outputs. An inconclusive comparison stays
inconclusive; do not repeatedly tune against its labels until it passes.

## Admission and execution order

1. Product/domain + DE review of this design and its fixture requirements;
   independent adversarial method review, with findings recorded.
2. Materialize and validate formative raw states and independent references.
   Exercise fresh native setup and actual MCP inventory/source calls without
   inference. Test clock deadlines, cleanup and full cost accounting.
3. Freeze a **new** small formative protocol with explicit actor, Jev, tool,
   token/accounting and wall-time limits. Confirm host stability before paid
   work. Do not reopen any closed cohort or transfer unused allowance.
4. Run complete onboarding through later human-facing outputs, inspect failures,
   repair supported product/skill problems and retain the original scores.
5. Only then freeze newly authored confirmation fixtures, power/precision
   assessment, reviewers, budgets and the full matrix. No automatic launch of
   hundreds of actors from this document; obtain budget approval for each wave.
6. Run reliability and real-human sessions separately. Summarize what actually
   ran, where SignalWeave helped, where it hindered and what remains unproven.

Keep raw transcripts and large datasets in ignored artifacts or separately
versioned evidence storage. Keep this plan, compact manifests, reusable tests
and concise measured summaries in the repo. Never publish synthetic proposed
counts as completed trials, or claim enterprise readiness from unit-test totals.

## Implementation checkpoint — October 17, 2026

Three internal Luna-xhigh consultations covered product/domain fit, DE/data
quality and adversarial methodology. Product/business-analysis, data-quality
and scoped analysis-validation skills informed the review. They added specific
settlement and quality-held inventory tasks, approval/query-lineage controls,
company-cluster accounting, review-cost accounting and the DST correction.
These are simulated experts, not external peer review or human participants.

The first implemented prerequisite is
[`available_history.py`](../evaluations/available_history.py): select the latest
knowable event revision before filtering event time/deletion, compare UTC
instants and preserve the original record in an isolated result. Its
[tests](../tests/test_available_history.py) cover 12 caller-separated event sets,
each with 1,000 events and 100 correction versions, at 12 cutoffs (144 projections,
13,200 versions). Those sets are not 12 onboarded companies. The test-side
reference checks projection mechanics, not independently validated business facts.

After the DST fix, 50 focused history/Harbor checks passed in 32.17s; the 17 new
history checks also passed on Python 3.11.6 in 1.29s. The three failing pre-fix
DST cases remain in the local diagnostic log. Final `make verify` passed lint
and 4,256 tests, with 12 opt-in skips, in 261.82s on Python 3.12.10. These are
software checks, not 4,256 business observations. Reproduce without credentials:

```sh
uv run pytest -q tests/test_available_history.py tests/test_harbor_reference.py tests/test_harbor_onboarding.py
```

Ignored local evidence logs (SHA-256):

- `artifacts/available-history-dst-before-tests.log`: `8efd7d2a4eb6c176bd777cc5902159991522bbde01f4fcbe26d17a2334d4b435`
- `artifacts/workflow-history-reviewed-focused.log`: `d7496add7c3c373a00ae5a811b6aae596608dce6c740cdae5635b85bcb4b1a97`
- `artifacts/workflow-history-reviewed-full-verify.log`: `615888f5ea625af4ba75a179cb29891f96d5bddd5c310b61242758995aaa1aad`

No new business-agent trial, Jev judgment or human session has run under this
plan. Raw company histories, source-boundary enforcement, independent business
references, the actual workflow runner and execution admission remain work to do.
No production code, native build or product scope changed in this checkpoint.
