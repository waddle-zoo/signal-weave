# Domain-context preview evidence

Updated 2026-10-15. Feature branch: `feat/domain-context-memory`;
[draft PR #19](https://github.com/waddle-zoo/signal-weave/pull/19).
Main and the published rc3 download are unchanged.

## Current conclusion

The context/card API and native transports have engineering evidence. One
two-turn, scripted-owner onboarding pair completed with independent policy
reviews. Its report-only follow-up completed six fresh reports and three live
Jev calls, with correct policy outcomes but mixed narrative quality and no
overall cost/quality win. Comparative business benefit and enterprise readiness
are **not yet proved**. Do not interpret unit-test counts, synthetic approvals or
correct outcome labels as that broader proof.

The [acceptance ledger](../domain-context-plan.md#current-acceptance-ledger)
keeps the full goal open. This report is a current summary; the
[complete earlier chronology](https://github.com/waddle-zoo/signal-weave/blob/28becbefa740bc92ab0e271b347e786a6316a925/docs/evidence/domain-context-preview-2026-10-14.md)
retains old source identities, failed attempts, exact costs, limitations and
reproduction details. No raw research files were deleted by this consolidation.

## What is verified

| Layer | Evidence | Boundary |
| --- | --- | --- |
| Context persistence and authorization | Contract tests; signed native HTTP checks, review/reuse, tenant/read-only rejection and restart | Synthetic issuer, not customer SSO |
| Card/context dependency lifecycle | Exact revisions, source/meaning checks, reapproval, stale-context deferral and historical receipts | Not semantic graph traversal or automatic reminder delivery |
| Same-card clarification | Owner-scoped revision preserves anchors/pins, increments version and clears approval/plan; concurrent lifecycle writes use exact-snapshot CAS | Source scope cannot be silently changed; JSON locking is process-local, multi-process uses SQLite |
| Current native/local Superset | Rebuilt-candidate stdio lifecycle: 1 passed in 26.18 seconds, 10 MCP calls, 9 metadata reads, zero inference | Scripted isolated setup, not a real human wizard or analytical report |
| Current native HTTP/context | Signed HTTP reuse/roles/restart passed in 28.11 seconds; zero inference; 10 additional URL validators passed | Local signed issuer and Superset metadata, not customer deployment |
| Live recurring decision lifecycle | Current scripted same-card clarification/reapproval matched all three supplied periods and exact routes; changed required meaning returned facts without another model call | Outcomes combine provider judgments and code guards; routes come from the card, not an invented model recipient |

The latest full suite passed **3,406 tests, 11 skipped, in 226.38 seconds**;
Ruff and diff checks passed. These are software checks, not companies, business
trials or an accuracy estimate.

## Live-agent results: retain the negatives

All cases below are synthetic development cases. Neither arm loses its source
tools; both can retrieve the company glossary and keep reusable notes. Installed
skill bytes are explicitly supplied, not autodiscovered. CLI setup is isolated
and non-interactive. Arbitrary scripts are disabled in both arms, so these are
not comparisons with an unconstrained BI agent.

| Cohort | Observed result | What cannot be concluded |
| --- | --- | --- |
| Initial paired canary | Both reports supported the quiet outcome, but treatment never exercised context tools; report audience and alert recipients were conflated | No context-layer benefit or valid route comparison |
| Earlier cold-onboarding variants | Invalid consent handle, incomplete source semantics, and a capped treatment with unknown usage; later harness repairs are recorded in the archive | No completed onboarding or comparative cost claim |
| `owner-workflow-v1` | Baseline setup accepted by a synthetic reviewer; treatment gave a correct first readout but left policy unresolved without using available clarification tools | No treatment approval or recurring report; guide wording is not a proved cause |
| `owner-handoff-v1` | Invalid shared-schema enum restricted refs/notes/readouts/card IDs. Baseline saved only a topic token; treatment read sources and drafted a card but could not finish | Neither completed onboarding; this is a harness failure, not product underperformance |
| `owner-handoff-v2` | Both first authors read sources, saved work and correctly reported unchanged 90% attainment. Baseline's second turn attempted `codex/list_mcp_resources`; the foreign-tool guard terminated it before a result/final usage | No completed resumption, independent policy review, final report, Jev call or valid product comparison |
| `owner-handoff-v3` | Baseline saved a valid pending-owner handoff. Treatment computed the same supported readout, but the harness rejected its advertised draft-edit tool and poisoned subsequent notes/handoff calls | Another harness capability/dispatch mismatch; no completed treatment handoff, second author, review, report or Jev call |
| `owner-handoff-v4` | Both arms saved pending-owner work, applied the same owner answers, and passed independent policy reviews; treatment revised the same draft v2 → approved v3 | Stopped at the original token limit before either fresh report; no Jev call, changed-period analysis, context reuse or advantage estimate |

In v2 the two complete weeks were 5,220/5,800 and 10,440/11,600: both 90%,
despite doubled volume. That supports the first readouts, not an alerting result.

The shared second-turn prompt exposed baseline to SignalWeave-specific card
instructions; the agent then announced a card-search plan. This is a confirmed
prompt-design flaw, but its causal link to the metadata call is unproved.
Future instructions now separate notes-backed baseline from card-backed
treatment, with tests on the actual supplied prompts. The advertised baseline
consent/completion schemas now match its notes-only capability; source tools,
glossary, owner answers and durable notes remain equal between arms.

The metadata namespace/source remains unresolved. The
[official MCP configuration guide](https://learn.chatgpt.com/docs/extend/mcp)
documents server tool controls but did not establish this particular event's
scope. A read-only global CLI probe showed that an empty `mcp_servers` override
did not clear user server entries; this is **not** proof about the separate exec
path, which uses `--ignore-user-config`. The guard has not been weakened or
allowlisted based on a tool name. No result established access to outside data.

A zero-model app-server probe also stopped before initialization on an inherited
invalid MCP transport, despite process-only disables. Personal configuration
was not edited. The [app-server status protocol](https://learn.chatgpt.com/docs/app-server)
is adjacent to, not proof of isolation for, the separate exec runner.

The role-corrected `owner-handoff-v3` was preregistered and independently approved
for one development attempt, not efficacy estimation. Its zero-inference native
preflight passed: 17 tools, exact source analytical fields/tenant, serialized
schemas in both arms/stages, zero Codex invocations and zero Jev requests.
Runner SHA-256: `c14bdf4b6bdefb3699cc4f4efe60e0253f90ab9952a75092f0fcf366ee0d1736`.
Preflight report: `artifacts/owner-handoff-v3-preflight/report.json`, SHA-256
`85b150f04e969d843c76cf36b008693f3a67ed5316b837f993b020cb16bc3794`.
Its later failed live attempt is retained, not resumed. Normal first-turn draft
edits now reach the native service; a validation error must not poison notes and
handoff. This does not permit first-turn approval or evaluation. Turn-two
same-card/version+1 verification remains unchanged.

All stopped cohorts remain terminal. In particular, unknown v2 cost is not a
fresh retry allowance or a zero-cost attempt.

## Accounting

Counts are observed tokens, not billed dollars or a speed-benefit claim.

| Cohort | Input / cached / uncached / output | Completeness |
| --- | --- | --- |
| Initial paired canary | 102,767 / 76,544 / 26,223 / 1,410 | 2 recorded agent invocations; no context-tool use |
| `owner-workflow-v1` | 427,159 / 329,216 / 97,943 / 4,791 | 3 invocations; zero Jev attempts |
| Invalid `owner-handoff-v1` | 377,916 / 304,896 / 73,020 / 4,305 | 2 invocations; zero Jev attempts |
| `owner-handoff-v2`, known first turns only | 302,307 / 244,736 / 57,571 / 4,427 | 2 known responses out of 3 attempted invocations; third cost unknown, zero Jev attempts |
| `owner-handoff-v3` | 366,151 / 292,608 / 73,543 / 5,155 | 2 known responses; stopped on first-author draft-edit mismatch, zero Jev attempts |
| `owner-handoff-v4` | 959,348 / 770,048 / 189,300 / 10,249 | 6 known responses; stopped before reports at the 180,000 uncached-token threshold; zero Jev attempts |

V2 charged the invalid v1 trace against cumulative stops. Its **total**, including
the censored third invocation, remains unknown. No project-wide total is claimed;
earlier unknown costs remain unknown. The full older accounting is in the archive.

### What the completed v4 onboarding establishes

Both first readouts correctly calculated 5,220/5,800 and 10,440/11,600 as 90%:
volume doubled without worse attainment. Both completed setups preserve the
all-parcels-due population, complete UTC weeks, owner-defined 0.05-ratio-unit
decline threshold, volume-only ignore rule, and missing-denominator route to
data operations. Independent synthetic reviewers accepted both policies.
Treatment's same saved card reached approved version 3 from draft version 2.
No delivery or scheduling occurred.

Setup was more expensive with SignalWeave in this single development pair:
the two authors plus policy reviewer used 755,509 aggregate input / 133,429
uncached tokens versus baseline's 203,839 / 55,871. This is observed setup
overhead, not a billed-dollar estimate or a recurring-run cost comparison.
No final reports started, so there is no amortization, quality or speed win to
claim. Shared context was saved/reviewed, but the card had no context pins;
neither cross-card reuse nor changed-context behavior was tested here.

Frozen runner: `574a26bf5d430bd19fa331758e681d8728edda6807b9c3934989a33642f30f5e`.
Retained local `artifacts/owner-handoff-v4-live/report.json` SHA-256:
`e4f4cef42971fefb466ba0eb9df0c6d267dce05fc13544dae9fcb397354b5048`;
trace SHA-256:
`e534505dfc0eb8a6072d47de408be3308489ab18619db4a681c810208975a13b`.
The separate zero-model native preflight passed before the reviewed live attempt.
Independent agent review accepted the code/evidence diff for this narrow claim,
confirmed the artifact hashes, and required that threshold/destination policy
remain described as recorded—not runtime-tested by this cohort. Synthetic
notes approval and card approval are different artifacts, not a card-to-card
comparison. This is not scientific peer review or customer validation.

### Fresh reports after accepted onboarding

`reviewed-setup-reports-v1` completed once, without retries or repairs, across
the same three Pine Courier development periods. Both arms received the same
accepted policy, owner answers, glossary and generic company tools. Treatment
added the installed SignalWeave skill/native analysis tools: this is a whole-
package comparison, not an isolated Jev ablation. The exact accepted card was
restored into fresh SQLite and verified through the rebuilt native MCP; the
original temporary home did not survive. No public import/reapproval or context
reuse is claimed.

| Check | Baseline | SignalWeave |
| --- | --- | --- |
| Final policy outcomes | `ignore`, `insufficient_data`, `notify`—all correct | Same, all correct |
| Agent tool calls | 15 | 7 |
| Source reads | 5 | 3 |
| Agent episode seconds, summed | 62.36 | 51.81 |
| Agent aggregate / uncached input tokens | 227,025 / 59,345 | 252,379 / 75,483 |

All three native receipts used the accepted card/version 3 and correct fixed
keys/routes with delivery disabled. Three real Jev requests used **18,434 input
and 391 output tokens**, with known usage. Agent output tokens were 3,322 versus
3,014. The combined new-agent usage plus both accepted onboardings is 1,438,752
input / 324,128 uncached / 16,585 output tokens across twelve invocations; Jev
usage is separate. All older failed/unknown cohorts remain separately recorded.

These numbers do not establish a win: the two avoided reads were handbook
context, not warehouse metric queries. Both arms made three primary metric
reads. Treatment was slower in two periods; its smaller summed time came from
the quiet period. It also used more input tokens, plus Jev, and had higher setup
cost. No billed-dollar or statistically reliable speed claim follows.

The raw structured report score was 2/3 in each arm, retained unchanged. The
baseline's quiet report proposed the business owner despite `ignore`; report
audience versus alert-recipient wording needs independent interpretation. The
treatment's missing-data report cited its actual receipt as well as its source;
the source-only scorer rejected the receipt reference. A legitimate workflow
receipt is not automatically an unsupported measurement citation.

More importantly, treatment said parcel volume was unresolved in both complete
periods despite the same compact packet containing denominator counts of
5,800 → 11,600. It followed an optional watch's `unknown` judgment instead of
the available measurements. Correct policy/math did not guarantee a complete
business explanation. Preserve this narrative defect; do not claim perfect
reports or rerun the closed cohort to hide it.

Retained `artifacts/reviewed-setup-reports-v1-live/report.json` SHA-256:
`cf0c148c5ff31c98352e8c375670045dfcdacfb3f0c2d3ff0df437c2079c275e`;
trace SHA-256:
`3387a21ce9ceccd432c9c63a267ba9030c6f44ca84fbd3e9083cacfe4eb368db`.
Runner SHA-256: `c3bc675a7f96117a042a1808d86fb19f74a2117ca0c20cf9663d19ef555fdf05`.
Native source SHA-256: `bd1677659bb97626906514dc9cab21684882ad564bcbe56907b26e4ae5bcde5d`;
binary SHA-256: `6f4e249d5196c80b4de2e1ba572cb8f17411ae3fd95b636ee0a18d24dea4ab78`.
Build Git `7d9822e`, dirty flag true for the research-only checkout changes;
source fingerprint matched current production. This is not a published rc3 asset.
Independent agent review accepted this mixed evidence for publication, confirmed
the volume-description defect and legitimate receipt citation, and rejected
claims of advantage or warehouse-query savings. The broader goal remains open.

### Bounded card handoffs

Card discovery now pages identity/status summaries instead of sending every
stored card's history. Normal agent revision responses retain active policy,
source scope, pins and version while omitting history. Full audit access remains.
Nineteen focused cases cover paging, tenant/status filtering, strict bounds,
profile defaults, retained policy/history and no source/model calls.

Replaying the actual retained v4 card listing through the production MCP in an
offline SQLite fixture reduced compact JSON from **16,033 to 365 bytes (97.72%)**
with the same card ID. This is one serialization measurement, not token usage,
billed savings, latency, database-scale performance or better agent outcomes.
Independent code review found no blocker to this scoped change. Reports still
need a separate paired trial; v4's costly explicit full-mode selections are not
being relabeled as compact-default failures.

The v2 safeguards have 17 offline cases: immutable prior-trace identity,
prior-plus-current token stops, unchanged legacy defaults, no forwarding of
old conversations into prompts, and explicit unknown-versus-partial usage.
Preflight validates both stages' serialized common schemas with the actual
transport's JSON Schema validator; it does not substitute Python-only fake
dispatch for wire-schema validity.

## Native owner-clarification check

`approved-card-clarification-v2` is a separately preregistered product check,
not a resumption of the agent cohorts. It uses the existing retail fixture
(seed `20261001`, company index `0`), all three periods in order, and at most
three upstream Jev attempts with retries disabled. No frontier agent or delivery.

The script first saves a draft without policy/routes, reviews and pins its
definition, applies the fixture owner's policy/routes to the same card, reviews
and approves it, then checks outcomes, exact destination keys/URLs, receipt
identity/version and delivery disabled. A changed required definition must
defer policy without another inference call, preserving source facts/provenance.

The v1 attempt failed before inference because the script incorrectly read the
compact binding receipt as a full card; JUnit records zero provider attempts and
errors. That is a harness failure, not a decision outcome. The corrected v2
preflight then completed the entire clarification/review/approval path in 25.28
seconds, with a synthetic key, hard zero-request budget, card version 3 and zero
provider attempts/rejections.

The separate live v2 run **passed in 26.39 seconds**. All three version-3
receipts matched their expected outcomes: `insufficient_data` to Data operations,
`ignore` with no route, and `notify` to the Business owner. Exact destination
keys and URLs matched the saved policy; no messages were sent. After changing
required meaning, the fourth packet had no outcome or routes but retained
nonempty source evidence/provenance, without a fourth inference call.

The three provider requests used **15,024 input and 163 output tokens**; usage
was known and no provider error/rejection occurred. Cache usage and billed
dollars were not reported. This is not comparative latency or cost evidence.

The alert packet also contained source rows and a reconciled accounting
decomposition: net sales were 10,000 → 7,000 USD; web contributed the entire
3,000 USD decline and shop contributed zero. These are source/contract-derived
calculations, not causal findings or calculations performed by Jev. No frontier
agent consumed this packet in the check. This gate cannot establish
conversational onboarding, comparative usefulness, causal analysis or customer
acceptance.

V2 preflight JUnit SHA-256:
`4aba5f1de150e2b3064314b9e850748b307029964bda39e2d61207c4d3e39c2c`.
Frozen v2 test SHA-256:
`4abb8db656fcbc41bacd802f2a5230e28d8bd3a5757e3c0f201f5d4b78d8d685`.
V2 live JUnit SHA-256:
`52f36b24157d8962e676bf7e30f54e17eaad6a9715776ed709aa05fca0e30100`.
V2 live trace SHA-256:
`7868fe83089da81951b4384344c8ea24fdbf8227d4b6ad15052fae35e032b93b`.
The four native result packets remain in the ignored live trace directory.
Independent agent review reconciled the JUnit and retained packets and accepted
this bounded lifecycle claim. It did not approve broader onboarding, accuracy,
cost/speed superiority or enterprise-effectiveness claims.

The older native/provider series remains separately charged: four attempts,
18,760 input and 220 output tokens, including its initial response-shape
assertion failure. The stronger route/content assertions were not live
validated in that old series; they must not be backdated into its result.

## Identities and retained artifacts

The rebuilt candidate's combined local-stdio/signed-HTTP check passed 12 tests
(two actual native lifecycles and ten URL validators) in 54.79 seconds, with no
provider inference. Local Superset metadata remained on loopback port 18089.
Retained `artifacts/bounded-card-native-transports-v1.xml` SHA-256:
`6db05641bd70d056ce8c0ccdb50c2c87b1334885e8f91bcfcd5675cdec723570`.
Its recorded source/binary identities match the current report trial above.

Earlier native lifecycle production/skill fingerprint:
`60d7e67c5f11ceaf56518a323cf20909aabd28c317bf6f905ff47157cbdf0ac5`.
Clean native build: `87f518c6f65ebb38ee1c2da842170236dd78e420`;
binary SHA-256:
`ca473d181de034c9e3b868376cf538d72275e4080027c37e0241911bdd34267a`.
This executable matches the source used by those earlier lifecycle checks, not
the later bounded-handoff change. Current report-trial binary/source identities
are recorded above. Neither is the published rc3 binary, despite matching labels.
The HTTP JUnit below records an earlier executable
(`2ea5cab3c2fb623499ed6c7202fa4d1f7640d9688b53a08d96bebe02c5cdfdab`)
with that same production fingerprint, not the clean binary's identity.

| Artifact | SHA-256 |
| --- | --- |
| Clean native/local Superset JUnit | `d60c505b33394f22fd37af88fce422b951cc247ffeb960b9c1fc70b16b8df322` |
| Native HTTP/context JUnit | `f19f2eb6c587c87563e5944ec1b5eb546fc2a0aa3ec31dd4879505311fb3f149` |
| Invalid handoff v1 trace | `532070437a6f9ced1e6f5e0668fba1d0b5d7f4c9012ce9512916dc0bb61d173d` |
| Handoff v2 report | `0bcae9082bcdc1327461a67e7988a54130a3154a6e3d9df15e3cfad1d46b1e4a` |
| Handoff v2 trace | `8468a3354bc718ffb79eab533e5c62610f69ac8ec6aa404f755d1b23896780e5` |
| Frozen v2 runner | `089eca1e76496b363f425d8e5f36738565cad975ef6b1e4fa52d2971c0c73d94` |

Full traces/result packets stay ignored under `artifacts/`; private credentials
are not public evidence. The archive retains the preceding exact identities.

## Reproduce the engineering checks

Run `make verify`. Build the current source with
`uv run python scripts/build_binary.py`; native checks reject stale production
or bundled-skill fingerprints.

For the explicitly selected local synthetic Superset fixture on port 18089:

```sh
RUN_CONTEXT_CARD_INTEGRATION=1 SIGNALWEAVE_BINARY="$PWD/dist/signalweave" \
  uv run pytest tests/test_context_native_card_integration.py -q
RUN_CONTEXT_HTTP_INTEGRATION=1 SIGNALWEAVE_BINARY="$PWD/dist/signalweave" \
  uv run pytest tests/test_context_native_http_integration.py -q
```

These two checks use synthetic startup credentials and a disabled inference
endpoint; they do not require provider credits. See the
[protocol](../domain-context-plan.md) for the separately bounded live-provider
check, its real-key requirement, and the terminal agent cohorts. Do not
automatically rerun a stopped series or present these commands as business proof.

## Remaining outcome gates

Expand the single scripted-owner onboarding result; improve and validate final
report completeness and investigations; demonstrate cross-card context reuse
and changed-meaning behavior; expand to diverse real connector paths and held-out
business cases with equal information and full accounting. Customer SSO,
interactive human onboarding, actual scheduling/delivery and enterprise efficacy
are not established by these synthetic checks.
