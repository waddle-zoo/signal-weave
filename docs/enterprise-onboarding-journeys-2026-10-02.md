# Enterprise onboarding journeys: messy-catalog regression

Status: **failed onboarding/readiness gate**. One frozen live run completed with
all 48 planned episode records retained. Five of six treatment onboardings
failed. No comparative product benefit or enterprise readiness is established.

## What changed in the test

The earlier local binary check supplied three configurations. It did not show a
user's agent discovering assets, asking questions, authoring a card, obtaining
approval, and running it later. Earlier Northstar trials exercised many recurring
decisions, but started with curated cards. Neither establishes easy onboarding.

This regression uses six existing business families, with no card preloaded:

| Simulated company | Owner's question | Analytical distinction |
| --- | --- | --- |
| Juniper Trail Retail | What sales do we actually keep? | Gross sales, refunds and net sales; unknown refund timing |
| Harbor Workspace | Is retention getting worse? | Within-plan deterioration versus customer mix |
| Kindred Helpdesk | Are we letting customers down? | SLA attainment versus ticket volume; missing eligible denominator |
| Cinder Database Cloud | Is this slowdown customer-facing? | Joint latency, lag and region coverage; isolated CPU is not enough |
| Mosaic Exchange | Are fewer people buying? | Distinct buyers versus overlapping channel counts |
| Lumen Freight Finance | Are receipts weakening? | Settled cash versus booked amounts; late bank partition |

Each company has 24 catalog entries: four original assets plus archive, sandbox,
regional-pilot, forecast and partner-scope alternatives. These alternatives copy
measurements with changed scope/provenance. They test scope selection, **not 144
independently authored enterprise assets**. The business families and private
period labels were used before; this is a regression, not a fresh holdout.

Both arms use `gpt-5.6-luna` through the saved-login Codex CLI, the same source
tools, calculators, owner answers and persistent notes. Treatment additionally
uses production SignalWeave tools and live Jev. Independent model owner-review
episodes check policy fidelity; they are not real human approval. The treatment
agent must discover, draft, preview, get reviewed, approve and finish setup itself.

One setup and three later snapshots per company, per arm, produce **48 planned
author/monitor episodes**, plus owner-review invocations. Failed setup keeps all
three later periods in the denominator. Missing service is not successful silence.
Later snapshots cover quiet, material movement and unavailable/ambiguous evidence;
they are not a months-long scheduler or notification-delivery test.

The runtime and harness were frozen at `6bac807`. The pre-call protocol caps Jev
at 144 request attempts including failures, disables SDK retries, and permits 45
tools per author/monitor episode. There are at most 36 additional owner-review
invocations. No runtime repairs, manual card edits, label changes or replacement
runs are allowed during this experiment. Offline export/review code is separate.

## Results

| Endpoint | Luna + company tools | Same Luna + SignalWeave + live Jev |
| --- | --- | --- |
| Setup complete | 6/6 | **1/6** |
| Product preview returned during setup | Not applicable | 6/6 |
| Later reports completed | 18/18 | **3/18** |
| Final outcome and recipient keys correct | 18/18 | **2/18** intended; 2/3 returned |
| Native SignalWeave outcome and recipient keys correct | Not applicable | 2/18 intended; 2/3 returned |
| Frozen exact structured score | 14/18 | 0/18 |
| Median setup attempt, including failed attempts | 72.0 s | 162.1 s |
| Setup author tool calls, excluding reviewer tools | 77 | 156 |
| Setup tool errors returned to author | 0 | 44 |
| Scripted owner questions | 29 | 28 |

The treatment read the guide in all six cases, asked for the supplied owner
policy, and obtained a preview in all six. The major loss was **turning a draft
and preview into a usable approved workflow**, not merely discovering missing
business intent. Preview completion does not imply correct analysis or approval.

Only Cinder completed treatment setup. Its material slowdown and missing-coverage
periods had the correct native and final routes. Its quiet period instead became
`insufficient_data` for Data operations: the output added a versioned-definition
prerequisite despite the supplied population and unchanged latency/lag. The final
agent preserved that incorrect native decision. This is not excused by the five
other onboarding failures. The native bundle explicitly distinguishes an unresolved
Jev watch assessment from observed missing source data. The final writer nevertheless
turned that uncertainty into an asserted comparability/definition defect. Faithful
use of that distinction must be tested, not assumed because it appears in the bundle.

The strict score is not an arithmetic-accuracy percentage. Baseline misses include
a mistyped retail citation, finance claims lacking per-claim completeness-source
citations, and canonical finance numeric fields submitted for an explicitly
incomplete export. Treatment misses include an omitted top-level rollout citation,
a canonical latency claim without known population, and the incorrect quiet-period
route. Some prose qualifies the unavailable data; the original structured scores
remain unchanged and are assessed separately from narrative quality.

The run used **99 live Jev attempts**, resolved model `jev-1.13.0`, with one HTTP
520 failure and zero SDK retries. It also used **48 Codex invocations**: 33
author/monitor invocations and 15 separate owner reviews. Fifteen scheduled
monitoring episodes were retained without a model invocation because setup failed.
The 144-Jev-attempt cap was not exhausted. No real messages were sent.

Do not compare total monitoring latency or source reads across arms as savings:
the treatment delivered only three reports. On the only matched completed company,
the three reports took 75.6 seconds for treatment versus 64.5 seconds for baseline,
including native evaluation time. This small, correctness-failing subset proves
no speed advantage. Token-based dollar estimates in raw artifacts are illustrative
API equivalents, not measured saved-login subscription charges; one failed Jev
attempt has unknown token usage. No billed-cost or human-labor saving is claimed.

## The actual user journey and what remains untested

| User step | Evidence from this trial | Remaining gap |
| --- | --- | --- |
| Install and attach an agent | Not exercised here; separate Mac binary smoke test exists | Fresh-user install, managed devices, other release platforms |
| Connect company BI | Synthetic normalized MCP adapter | Real Preset/Looker/Hex credentials, tenant permissions and source fidelity |
| Say what matters | Short business brief; agent asks scripted owner questions | Human comprehension, conflicting stakeholders and incomplete policy |
| Select evidence and draft a workflow | Agent tools run against the messy catalog; no expert card | Larger, independently authored catalogs and unsupported asset capabilities |
| Preview and approve | Production lifecycle plus a simulated owner reviewer | Reliable handoff and human-facing explanation; model review is not authorization |
| Monitor later evidence | Three independent chronological snapshots after successful setup | Long-running state, drift, reassignment, outages and overlapping workflows |
| Receive a useful report | Final structured output and separate narrative review | Real delivery, acknowledgement, duplicate suppression and measured human time saved |

## Findings requiring follow-up

The operational trace already exposes failures invisible to curated-card replays:

1. Selected source references can be rejected after onboarding reranks discovery
   using a changed query. Discovery selection needs a stable, authorized handoff.
2. The agent supplied `selected_sources` objects without the required `ref` field.
   The generic dictionary schema and late error did not make recovery easy.
3. Harbor's native review returned a confirmation fingerprint which the next
   approval call rejected. Review reruns discovery during approval; the precise
   fingerprint instability is reproduced offline in
   [`test_onboarding_review_stability_regression.py`](../tests/test_onboarding_review_stability_regression.py).
   Lumen also reached owner approval and then received repeated native stale-token
   rejections. The characterization test asserts the current defect; it is not
   evidence that the lifecycle is fixed.
4. The simulated owner reviewer receives business policy but not the catalog or
   inspected source contracts. It rejected supported scope checks and reporting
   requirements as unauthorized policy. That is a **methodology limitation**,
   not automatically a product defect or a baseline reasoning failure.
5. Agents encountered 26 workflow-evaluation tool errors during setup, including
   malformed snapshot inputs and tenant-scope rejections. The desired experience
   should not require reconstructing adapter snapshots by hand. These rejections
   do not justify removing tenant checks.

Do not remove approval or source-health checks to make these cases pass. Separate
business-policy fidelity from evidence-contract validation, validate source input
before paid work, and bind confirmation to material policy/catalog state rather
than incidental model ranking. Any implementation repair needs its own versioned
regression and prospective live test; it cannot rewrite this result.

### Narrow next proof gate

1. Stabilize the selected-source and review-to-approval handoff. Prove unchanged
   authorized inputs survive ranking changes while actual policy, permission,
   source-definition and scope changes still invalidate confirmation.
2. Make evaluation-case inputs and recovery steps usable by the caller's agent;
   validate malformed selections before paid inference. Preserve the current
   preview, human approval and tenant boundaries.
3. Correct the simulated owner-review boundary: policy fidelity is distinct from
   source-contract validation and optional reporting. Give each check the bounded
   public evidence it needs, without future snapshots or oracle outcomes.
4. Cover negative evidence versus unknown evidence in the first-report acceptance
   cases. A false watch condition is not a data outage; a model's uncertainty is
   not proof of missing records. The final writer must preserve those distinctions
   and the actual source references.
5. Freeze a new small live acceptance run before scaling again. Require complete
   onboarding, faithful quiet/event/gap reports, correct exact endpoints and
   supported explanations without manual repairs. Then test independently authored
   catalogs and real-user installation/account connection. More copies of these
   same fixtures cannot substitute for those checks.

## Evidence and review

- [Frozen pre-call protocol](evidence/enterprise-onboarding-journeys-2026-10-02/frozen-protocol.json)
- [All scored episode results](evidence/enterprise-onboarding-journeys-2026-10-02/results.json)
- [Twelve onboarding stories: owner questions, reviews and errors](evidence/enterprise-onboarding-journeys-2026-10-02/onboarding-stories.json)
- [Execution counts and integrity checks](evidence/enterprise-onboarding-journeys-2026-10-02/execution-audit.json)
- [Compressed full report](evidence/enterprise-onboarding-journeys-2026-10-02/full-report.json.gz)
- [Compressed redacted interaction trace](evidence/enterprise-onboarding-journeys-2026-10-02/trace.jsonl.gz)
- [Compressed arm-masked review packet](evidence/enterprise-onboarding-journeys-2026-10-02/blind-review.json.gz)
- [Methodology review and reviewer corrections](evidence/enterprise-onboarding-journeys-2026-10-02/methodology-review.md)
- [Narrative review A, follow-up](evidence/enterprise-onboarding-journeys-2026-10-02/narrative-review-a-followup.json)
- [Narrative review B, follow-up](evidence/enterprise-onboarding-journeys-2026-10-02/narrative-review-b-followup.json)

Frozen runtime/harness hashes and the wrapper hash were checked after execution;
none changed. The exporter independently checks all 48 identities, request/terminal
pairs and total/per-episode usage against the trace. The actual configured Jev key
was checked for absence before archiving. No credentials are included.

Two internal Luna reviewers examined methodology and the approval defect. Their
export-integrity findings led to denominator/trace cross-checks and corruption
regression tests. Separate arm-masked narrative review is recorded alongside the
results; these reviewers knew the study design and earlier process issues, so this
is not fully blinded independent peer review. The raw results' pending-review field
records export time, not the final review status.

After checking all 36 report slots against the public evidence, the final internal
narrative verdicts were:

| Verdict | Baseline | Treatment |
| --- | --- | --- |
| Supported narrative | 15 | 2 |
| Qualified narrative | 3 | 0 |
| Unsupported narrative | 0 | 1 |
| Missing output | 0 | 15 |

These are prose-support assessments, not substitutes for the stricter structured
scores. For example, the treatment's slowdown explanation is supported by actual
source values but still omits the rollout source from its top-level evidence list.
The reviewed quiet-case explanation is unsupported: source snapshots contain the
population and zero affected regions, contrary to its asserted new prerequisite.

Both initial reviews remain in the evidence directory. The first passes missed a
retail citation defect and incorrectly accepted the quiet-case coverage story;
parent review sent both back for checks against exact source payloads. The follow-ups
correct these findings. Agent agreement without inspectable reasons was insufficient.
Review pointers refer to `blind-review.json`; decompress the retained `.gz` to use
them. The uncompressed packet SHA-256 is
`ecd861e98e259c05da173b04a62506d791c494c894fd402327bd8bceba89f089`.

Offline verification: **2,027 tests passed, four opt-in tests skipped**; Ruff and
`git diff --check` passed. `uv` was unavailable in this shell, so verification used
the existing virtualenv directly. Passing these contracts does not override the
failed live onboarding gate. TypeSafe skill boundaries were preserved: live Jev
for semantic judgments, code-owned arithmetic/permissions/approval, no production
heuristic fallback and no fixture logic in `src/`.

## Reproduction

Zero-call protocol and contract checks:

```sh
uv run python -m evaluations.enterprise_onboarding_journeys --output artifacts/journeys-preflight-new
uv run pytest tests/test_enterprise_onboarding_journeys.py tests/test_enterprise_journey_review.py
```

Explicit live run, using an already authenticated Codex CLI and an explicitly
provided private Jev key file:

```sh
uv run python -m evaluations.enterprise_onboarding_journeys --live \
  --jev-key-file /private/path/to/jev-key --output artifacts/journeys-live-new
uv run python -m evaluations.enterprise_journey_review \
  artifacts/journeys-live-new/report.json artifacts/journeys-review-new
```

Every output directory must be new. The exporter checks fixture identity, all
planned episode identities, matched request/terminal events, and report/trace
usage totals. Give narrative reviewers **only** the arm-masked packet, not its
mapping or scored results. Output wording can still reveal the arm; this is
internal adversarial review, not external peer review.
