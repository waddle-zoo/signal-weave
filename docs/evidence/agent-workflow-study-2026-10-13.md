# Agent workflow study — October 13 snapshot

This is an **unpooled evidence note**, not a product score. The readiness and
Northstar evaluations use generated company data and labels with live Jev; the
development pilot uses synthetic exports over a loopback company-MCP bridge.
No hosted BI account, customer workflow, or external message delivery was
tested. Full run artifacts remain under local `artifacts/`; this note records
their scalar results and SHA-256 digests rather than copying large reports or
traces into `docs/`.

## Results, kept separate

| Evidence track | Observed denominator and result | What it means |
| --- | --- | --- |
| Generalized readiness | Four simulated companies, 14 workflow cases: **14/14 exact**; six retrieval cases: **6/6**; five card/source bootstraps ready. The independent gate passed. | Thresholded fixture readiness across simulated adapters, not proof of live enterprise connectors or customer accuracy. The harness made no catalog-list calls; each simulated catalog represented 16,666 resources. |
| Generalized readiness, Oct 14 live run (experimental fingerprint; unpooled) | **4 synthetic companies, 5 workflows, 14 workflow cases, 6 retrieval cases; 20 SDK requests; 70,048 input / 2,410 output tokens.** Deterministic adversarial gate: **PASS**. Fingerprint `7c77d6c459e9dbab610d4abe734c957e6493cd8a4afcfac3a70e7e6dac6fede1`; producer `b8229b4` + CLI merge `001cb35`; [source harness at `7ceb75c`](https://github.com/waddle-zoo/signal-weave/blob/7ceb75cd530ea601054d273a30cec7d0ffe3cf0f/evaluations/generalized_readiness_trial.py). | Curated fixture cases were repeated, not a new holdout; synthetic only, with no real-connector, onboarding, or agent-efficacy evidence. Regression checks: **2,919 passed / 7 skipped** before CLI merge; post-merge checks covered **112 CLI/install** and **31 parity-focused** tests; native MCP smoke passed on binary `3c5e…`. No broad comparative trial or performance win. |
| Northstar scale, original full run | **167/168** workflow outcomes exact. Anchor retrieval: 169 cases, 100% candidate and recommended recall, **89.6% recommended precision** (below the 90% gate), and 59.8% required-group recall. Graph-bundle stage: **168/168 `RecursionError`**, zero graph-stage Jev requests. The adversarial review failed; overall status is shadow, not approved. | Curated-card execution, not onboarding. A separate retrieval repair supersedes only these retrieval measurements; the workflow result remains reused at 167/168. All rows, labels, roles, and destinations are simulated; delivery is disabled. |
| Northstar retrieval repair v3, frozen | 169 anchors: approved retrieval subgate, **91.2001% recommended-anchor precision**, 100% recommended recall; required-group recall 55.0% (configured minimum 0). 168 bundles: **0 errors**, 100% selected-group recall, but only **31.1508% selected-bundle precision** (shadow). Reused workflow is **167/168, shadow**; exact frozen input and label digests verified. | The 91.2% anchor metric does not clear the composite gate: selected-bundle precision and the reused workflow remain shadow. Frozen-fixture retrieval-only repair; all Northstar data and labels are synthetic. |
| Agent-workflow development v2 | Six companies and 18 pairs assigned; four companies onboarded/completed. **12/18 pairs observed**; among those, final-agent outcomes and routing were each **12/12 correct** in both baseline and treatment. Six pairs remain unobserved, so the cohort is incomplete and shows no treatment advantage. Treatment's native judgments are a separate 12/12 across 16 attempts. | This adds onboarding to the evaluation, unlike the curated-card Northstar endpoint. Loopback HTTP carried synthetic normalized exports, not hosted BI data. One reviewer marked message M04 `needs_attention`: it did not explicitly say the source lacked measurement windows. Mock outbox only; no real communication was sent. |
| Two-company repair check (interim) | Finance alone completed onboarding. **3/3 paired final outcomes** were correct in both arms. Treatment Jev judgments were observed in **2/3** cases and both were correct; the agent skipped Jev in the third. | Not a clean product-superiority result. Operations paused with policy fallback undefined and repeated owner-static clarification still unclear. |
| Full v4 root cohort (decision-first; completed) | **6/6 related synthetic business families onboarded; 108/108 paired periods observed** (18 per family, not 108 companies). Baseline outcomes/routes: **108/108**; treatment: **107/108**. Native judgments: **108/108 correct**. | Across the 108 post-onboarding paired episodes, summed per-arm runtime (including recorded native preflight/tool overhead) was **2,063.6s baseline vs 3,091.2s treatment** (**49.8% slower**, 1.50×). The 36 quiet results skipped treatment-frontier invocations; the other 72 used the frontier, versus 108 baseline invocations. This call avoidance did not produce a net runtime win. Timing excludes onboarding and independent narrative review; no dollar savings are claimed and cached-token billing is unknown. One treatment miss followed a correct native Notify. Synthetic loopback company-MCP replay, not real-user or hosted-source evidence. |
| Native local-Superset budget failure (Oct 13; earlier paired readout) | Setup **5.64s**, catalog health passed (48 entries); onboarding **227.83s**. Baseline: **223.56s**, 4 discoveries, 16 data reads. Treatment/frontier: **227.71s**, 3 discoveries, 22 reads. The evaluated payload was **150,456 bytes (~150 kB; 50,152 estimated tokens)** against a **12,000-token** limit. | Card scoped to local Northstar dashboards 1/8/11, report-only, no automatic notification rules; approval was operator-simulated, not authenticated customer approval. Both arms produced reports, but the saved `insufficient_data` receipt had run status `failed` and no typed policy judgment. This Oct 13 payload failure is separate from the Oct 14 paired handoff below; no advantage is established. |
| Native Superset paired handoff (Oct 14; two policy modes) | Original-policy treatment completed and submitted a report, but the receipt was `decision_deferred` with no typed judgment (**49,571 tokens** vs **12,000**). Explicit-deferred treatment also remained deferred (**49,574 tokens**) and exhausted the **60-tool-call** limit with **no submission**. | Post-run snapshot comparison was `different` in both repeats: sales/digital business data matched, quality evidence differed at `cache_status`, and source metadata/contracts differed (`signalweave_resolution`, `contract.roles`). Native reads and helper snapshots were separate—not the same input or an atomic warehouse snapshot. No superiority or total-source-cost claim follows. Trial method is pinned below; local run artifacts are not linked. |
| Northstar cache-qualified business readouts (Oct 14; separate trial) | Two repeats/four Luna Codex runs used the same approved card and skill. Both arms received identical frozen helper responses, while a separate native preflight made real Superset reads; full inputs were not identical. **Strict snapshot parity remained `different`**; cache-only opt-in admitted descriptive reports because only `cache_status` leaves differed (helper `unknown`, native `cached`), while observations, comparisons, contracts, and freshness fields matched. Delivery was disabled and four reports were saved. Original-policy: baseline **100.536s / 154,404 input tokens**, treatment **82.496s / 250,532**. Skill-guided-deferred: baseline **114.155s / 182,576**, treatment **193.001s / 604,535** (13 receipt pages, 6 chart reads). Treatment all-in **294.469s** includes **14.897s** shared capture and preflight; baseline **214.691s** is episode-only, so totals are asymmetric. Both treatment judgments were `decision_deferred`, with zero reported Jev attempts. | The original-policy report's first saved version had malformed semicolon Markdown links; a later correction was rejected after submission. Review found its numeric facts matched the receipt without invented currency, cause, or routes, but noted an App-vs-Mobile-Web comparison gap. The guided report had valid links and platform coverage, but omitted a partial Data Quality caveat and a duplicate/unaggregated-value caveat; its undated `SUM(failed_rows)=595,694` was not useful. Four saved reports are **not** four quality passes: neither treatment is a clean end-user handoff, and no Jev benefit was tested. Candidate RC2 binary was dirty; not clean-release validation. |
| Northstar guided pointer-repair retest (Oct 14; one pair, not holdout) | Clean experimental native binary `b9e3…` / source `4eeab…`; baseline **110.492s** (285,080 input / 211,200 cached / 12,024 output tokens), assisted **139.544s** (539,521 / 470,784 / 15,052). Assisted made **0 direct BI-tool reads** and **13 receipt calls**; native snapshots contained **30 charts**, not a measured query count. | Three MCP pagination-validation errors came from the **12,000-item** limit being used as an item count—not provider payload-limit failures. Jev remained `decision_deferred`, with **0 Jev attempts**. Galileo review rejected an analytical-quality pass: `SUM(total_rows)` for `status=FAIL` is not `failed_rows`; May/June vs August/September are dated periods, not current failure counts. Healthy contracts show availability, not completeness; all **3 sources** had partial analytical coverage on some charts. URL fix `0afe13c` passed **106 focused tests** and a live read-only 3-source/117-observation check with all **150** source/observation/evidence URLs absolute (`127.0.0.1:18089`); it is source-only, not published or in a new binary. Pagination fix `c407` passed **26 focused tests**. Restricted full suite: **2,981 passed / 7 skipped / 2 environment failures**; authorized-target retry pending. No query-cost or efficacy claim. |
| Development v1 validity | `invalid_method_stopped`; scoring is marked not admissible. | Static review found inconsistent time framing and label-derived quality variants. The run stopped during onboarding; it is neither a product success nor a product failure and is not pooled with v2. |

The frozen v3 report records **337 wrapper calls** and **842 new SDK requests**
(338 anchor + 504 bundle). Its **1,178 reported requests** include 336 reused
workflow calls; do not describe 1,178 as new calls. The 8,918,165 input tokens
include the reused workflow. Runtime is **28.735 seconds**, excluding large
workflow encoding, so it is not comparable to the earlier 1,295-second figure.
The first repair attempt failed late in the loader and lost its paid reports;
it is excluded, not counted as a pass. **V2 is retrieval-functional but not a
verified composite result:** fixture regeneration changed capture time, so its
reused workflow input digest was not a strict content match. V3 uses the frozen
fixture and verifies exact workflow input and label digests.

## Fixes tested and limits

- The 14-case readiness gate passed, and the Northstar workflow layer scored
  167/168, but the same Northstar run failed retrieval/bundle gates. These are
  synthetic harness results; neither establishes live source access.
- The skill installer/source journey tests passed offline: **15 passed** across
  `tests/test_native_skill_journey.py` (source CLI) and
  `tests/test_skill_install.py`. The latter separately exercises source,
  frozen-bundle, and wheel-data-root discovery plus install safety. Separately,
  a real wheel from commit `313f9ac` was installed in an isolated environment;
  its wheel and bundled skill hashes begin `c821b4…` and `40da…`, and the live
  Codex `skills/list` discovery succeeded. This is wheel proof, not a published
  download claim.
- `artifacts/native-skill-journey-current-2026-10-13.log` records the latest
  real native skill journey: **14 passed in 61.86s**.
  `artifacts/verify-enterprise-workflow-2026-10-13.log` records **2,923 passed,
  7 skipped in 208.46s** for freeze `6a1b975`. This suite still did not catch
  the broad-card native payload failure above.
  The real wizard setup took **6 seconds**, left no pending prompt, and Codex
  registered the installed skill (`e88620…`). That journey's source-health
  check remains unverified. A separate local Superset trial passed catalog
  health (48 entries), but did not test resource-level permissions or freshness.
  This session's earlier non-elevated `semctl: Operation not permitted` was a
  sandbox limit, not a product failure; the later native run supersedes it as
  journey evidence.
- Oct 14 supporting checks (not agent-efficacy results): onboarding-guidance
  suites **42+22 tests**, source-capture suite **49 passed**, Python full
  regression suite **2,946 passed / 7 skipped** before the harness (separate
  from the **2** native tests), and **2/2** installed-binary
  checks in **291.72s**. An exploratory packaging probe measured one-file
  `--version` at **14.45s** and **16.336/14.374/9.025s**, one-file `--help` at
  **10.71s**, versus an isolated one-dir cold build of **11.91s** and warm
  `--help` at **0.680s** and warm `--version` at **0.554/0.434/0.463s**.
  Commands differ; this is not a
  controlled startup benchmark, and no packaging fix or release-format change
  is in place. Receipt-page tests passed **21 focused tests**: they compare all
  **117** inline fact rows with raw receipt rows and exercise deferred-state
  persistence with **117 and 1,000** observations. In a separate native replay,
  an experimental candidate (`b9e3a66a…`, source `4eeab4a4…`, commit `c6e693f`)
  returned the same raw observation through the advertised pointer as inline,
  but equality was checked only for the **first** row, not all 117. A later local
  candidate (`c4073fe`, source `73307570…`, binary `e3363e…`; not published RC2)
  repeated first-row pointer equality, inspected one fresh chart, and verified
  seven absolute source URLs on `127.0.0.1:18089` plus the MCP schema's
  item-count limit description. Neither replay is a fresh multi-source
  evaluation or report. Real
  Codex stdio guide calls completed at client-default and 30s settings with an
  `item.completed` event for `type=mcp_tool_call` (`server=trial`,
  `tool=get_signalweave_guide`, `status=completed`, `error=null`, result
  `inference_performed=false`); end-to-end including one Luna turn:
  **17.98s / 15.70s**. Guide-only handoff proof, not a fresh source/report test
  or a standalone startup/throughput benchmark. The restricted full-suite run
  reported **2,981 passed / 7 skipped / 2 environment failures**; both blocked
  test IDs later passed in a targeted **135-test / 6.13s** rerun with PTY,
  loopback, and hosted connections. This was not a single combined 2,983-test
  run.
- The October 13 root trials froze `6a1b975`. October 14 checks use the
  fingerprints stated above, including source commit `c6e693f` for the clean
  receipt replay. The published native `v0.2.0rc2` includes the October 13 root
  code through release commit `b8917e5`; subsequent experimental evidence-handoff
  changes are not in that release. None of these trial results is a main-merge
  or enterprise-readiness certification.
- The full v4 root report records 250 native attempts across 108 cases (253
  tool attempts: 3 argument-validation errors and 15 decision-tool errors; 180
  valid current results; zero budget-censored companies). Its 144 mock-outbox
  messages received 114 `supported`, 29 `needs_attention`, and 1
  `cannot_assess` review—not a single binary pass/fail grade. By family
  (supported/needs_attention/cannot_assess): retail 16/8/0; SaaS 22/2/0;
  support 18/6/0; ops 22/2/0; marketplace 15/8/1; finance 21/3/0. In
  Marketplace `weekly-close-17`, the native
  judgment correctly chose Notify for valid Apr 21–May 5, 2025 measurements;
  the frontier agent followed stale Jan 6 notes instead and routed to Data
  Operations. No external messages were sent.
- A separate Galileo ALL-IN calculation matched source evidence for both the
  controller and frontier, but input tokens exceeded output and cache billing
  is unknown; this is not a physics or profitability result.
- Nothing here claims the published `v0.2.0rc1` download contains current
  source-candidate skill or workflow changes. See the version boundary in the
  [README](../../README.md).

## Reproduction and source

- Full v4 cohort: [decision-first harness](https://github.com/waddle-zoo/signal-weave/blob/6a1b97563e4f4c151a797bd797e08b589dd8c607/evaluations/native_cadence_trial.py) and [case definitions](https://github.com/waddle-zoo/signal-weave/blob/6a1b97563e4f4c151a797bd797e08b589dd8c607/evaluations/native_cadence_cases.py), pinned to commit `6a1b97563e4f4c151a797bd797e08b589dd8c607`. Runtime comparison sums each saved period's `baseline.arm_seconds` and `treatment.arm_seconds`; it excludes onboarding and independent narrative review.
- Oct 14 Superset paired handoff: [journey harness](https://github.com/waddle-zoo/signal-weave/blob/986f651286dbac9658d3a395e03ff7870756d584/evaluations/native_superset_card_journey.py), pinned to commit `986f651286dbac9658d3a395e03ff7870756d584`. Its local frozen `0.2.0rc2` binary was marked dirty; this retest is not a clean-release validation.
- Oct 14 cache-qualified readouts: [paired journey harness](https://github.com/waddle-zoo/signal-weave/blob/c6722a66dbe0d14843d8cbe08e2677de3325a9c6/evaluations/native_superset_card_journey.py), pinned to `c6722a66dbe0d14843d8cbe08e2677de3325a9c6`. The local result and audit artifacts are not copied into this repository.
- Readiness: [harness](../../evaluations/generalized_readiness_trial.py),
  [independent gate](../../evaluations/generalized_readiness_adversarial_review.py).
- Northstar scale: [harness](../../evaluations/northstar_scale_trial.py),
  [adversarial gate](../../evaluations/northstar_scale_adversarial_review.py).
- Agent workflow v2: [cohort harness](../../evaluations/agent_workflow_cohort.py).
- Skill: [canonical source/native journey](../../tests/test_native_skill_journey.py),
  [installer and source/frozen/wheel resolver tests](../../tests/test_skill_install.py),
  [wheel data mapping](../../pyproject.toml), and
  [native bundling](../../scripts/build_binary.py).

The local v1 validity record is
`artifacts/agent-workflow-development-2026-10-13/validity.json`. Its explicit
invalid-method status is retained rather than presented as a scored cohort.

Historical workspace cleanup moved 24 untracked raw-run directories and the
companion Northstar expert note unchanged to the local ignored archive at
`artifacts/research-archive-untracked-20261013/docs/evidence/`. Nothing was
deleted or rewritten; `docs/evidence` is now about 25 MB (about 81 MB before),
and tracked regression fixtures remain in place.

## Artifact SHA-256

These hashes identify the exact local JSON artifacts summarized above; they are
not replacements for the raw files or independent verification of their
contents. The October 14 cache-qualified result, audit, and native handoff
artifacts remain in the experimental worktree; their digests below are not
links to files in this repository.

| Local artifact | SHA-256 |
| --- | --- |
| `generalized-readiness-current-2026-10-13.json` | `0afa3557b6f2eaf2b6847853194d63d4a596375187ac3e309b897db9d017a789` |
| `generalized-readiness-current-2026-10-13-review.json` | `3ae9f8bb0bec9ca7aba56dbe3cd3bb2eda91e910b02046f01e9e87c722f966cd` |
| `northstar-scale-current-2026-10-13/report.json` | `7c0d0c3b8ba4fb3baab883c47b5157929c5ae35030a45e3aaac75fc198a814eb` |
| `northstar-scale-current-2026-10-13/adversarial-review.json` | `1300a3367e86e9e9f5fcc78cf6be3c6375086fba4b3db5218903cff2625f1dc8` |
| `northstar-scale-retrieval-repair-v2-2026-10-13/report.json` | `1b63e395ed9c11cbbd6a7cb0dfda6e68cbbc38c0136dfe40aa9c39db6381851b` |
| `northstar-scale-retrieval-frozen-repair-2026-10-13/report.json` | `a982bf8b709e4cfe333ccedf46ad0b080b8103e454e8f1dbf6012945f6d86c22` |
| `agent-workflow-development-v2-2026-10-13/report.json` | `fbf86570f3cd6d95cdcd9fd966f48737dcbac5870c8b5c5f8a1853f441ea204b` |
| `agent-workflow-development-2026-10-13/validity.json` | `d16b462bbcf5511f2b83a67553a8f16bb62d5a015a99e3c51bd0c64aab36446c` |
| `native-superset-card-budget-repair-2026-10-13/results.json` | `35d30c96771fc62fab67a89e90f72a19cb34e09d8f5314b35fd8c591ad761cb6` |
| `agent-workflow-prospective-card-first-2026-10-13/report.json` | `bd3aca0757ecc6d3684f48186fd26e3469930774e8e40eb56e5bddd46fe36f28` |
| `northstar-business-readouts-cache-qualified-2026-10-14/results.json` | `0214c018b82a1daede0df9bf714e59a3446692e26444518dac463d6d91013725` |
| `northstar-business-readouts-cache-qualified-2026-10-14/audit.jsonl` | `3514d3b3e349e9419bdd9ccc6ae6b92acc7cab64d2149197996a414e8e898fda` |
| `native-receipt-pointer-check-2026-10-14.json` | `1ee1ce79dc3c57a868561f6eef6c4096ad5269e316a3d93291f3f14db90112c7` |
| `real-codex-native-startup-check-2026-10-14.json` | `77354609db5eb5f6c22a55873e0ca03e6c7797908699b36627fb232b83955391` |

Per-company v2 report hashes, in `company-00` through `company-05` order:

```text
5cc3785edb15a965ed0d5ed2a8bbf5a486a7e364517f5c478d8bea8692847086
b4d57ec9932af337eee301a66e0659b8042078fabd311e0c2e68be14ffdb81c1
906ba4f0c7267cb1b18fab19ac785e248a640247b0a75c8645a26ba871f3a063
c81a63b01b10535ce0257a1112c4aad96492914f711e1c1d3a70344baae4c62c
cdb411920c7f865f059d9fedbf087e59c4b1ad75bca94ba74ea4906b83c28a82
3705fe281f4e377f49e86bf4eb0aa672048f08faa9e6892618b1745a2a77cb9a
```
