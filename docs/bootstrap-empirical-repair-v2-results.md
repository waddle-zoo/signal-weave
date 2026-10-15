# Live onboarding repair: three accepted cards, twelve exact runs

The [predeclared development regression](bootstrap-empirical-repair-v2.md) passed
on frozen commit `65ae247`: **3/3 agent-authored cards accepted; 12/12 subsequent
Jev monitoring runs matched outcomes, delivery keys, exact endpoints and required
evidence.** No person edited these cards during the run. No notifications were sent.

This repairs a demonstrated onboarding failure on **known synthetic cases**.
It does not prove enterprise readiness, novice usability with incomplete context,
or superiority over Luna. The [failed first run](bootstrap-empirical-v1-results.md)
and its baseline-validator defect remain part of the evidence.

## What ran

| Company | Draft attempts | Paid setup tests | Native monitoring |
| --- | ---: | ---: | --- |
| Support SLA | 1 | 1 | 4/4 exact |
| Database operations | 2 | 1 | 4/4 exact |
| Finance approvals | 2 | 2 | 4/4 exact |

Saved-login `gpt-5.6-luna` at low reasoning effort received the full owner policy,
approved source/destination directories and three labeled setup examples per
company. It did **not** receive expert cards or monitoring labels. The repaired
interface accepted business prose and directory selectors; code bound exact
source declarations and the operator's existing runtime defaults. Live
`jev-1.13.0` compiled and evaluated each candidate. Only accepted cards proceeded
to monitoring, frozen without rerunning Luna or repairing those twelve runs.

The setup examples and monitoring cases are unchanged from v1. Although the
three author episodes were new, these are not fresh experimental holdouts:
developers had already inspected v1 failures. Several interface and guidance
changes landed together, so this is not a causal estimate for one isolated fix.

## Failures that the setup loop caught

- **Database:** an initial draft keyed evidence requirements by descriptions
  rather than numbered card slots. Validation rejected it before a Jev call.
  Luna corrected it and passed its first paid test.
- **Finance:** the initial draft added required watch conditions beyond the
  authoritative signed-status decision. Jev marked the note-conflict watch
  unknown in a setup case, so the evidence gate changed the expected notification
  into investigation. Strict replay rejected the card. Luna removed those
  additional watch gates and kept the complete signed-ledger policy in
  `decision_guidance`, including unavailable and unresolved states and both routes.
  The second draft passed setup and all four monitoring cases.

The finance correction is meaningful but limited: the final card has no separate
watch items or questions. It proves policy execution and routing here, not rich
question-level explanations or diagnostic investigation. Source requirements,
the 0.70 action-support floor, endpoints and runtime gates were not relaxed.

Finance also handled the unresolved-status investigation branch omitted by v1's
card. That branch was explicit in the owner policy, though absent from the three
setup examples. Passing it now is useful regression evidence, not a guarantee
that a sparse example set covers every future policy branch.

## Resource accounting

- 28 Jev attempts: four compilations, twelve setup judgments and twelve
  monitoring judgments. Zero retries; the ceiling was 40.
- Three Codex author episodes; no new baseline or expert-control runs.
- Jev: 196,481 input tokens and 5,774 output tokens.
- Luna authoring: 485,046 input tokens, including 370,688 cached; 3,370 output
  tokens; 96.78 seconds summed episode time.
- Twelve native monitoring runs: median **248 ms**, 3.22 seconds summed engine
  time. Each used already supplied evidence, not live warehouse queries.

Across v1 and v2, 60 Jev attempts were used, below the combined 72-call ceiling.
These are recorded usage and timing, not invoices. There is no fresh paired
baseline for v2 and no justified cost/speed superiority claim. V1's separately
audited Luna attempts also selected all twelve expected outcomes and recipients.

## What this establishes—and what remains

The tested path can turn complete owner policy plus approved context into cards
that repeat these three workflows without rerunning the Luna authoring model.
Jev still evaluates every monitoring snapshot.
Empirical setup replay caught a real policy-representation error and allowed the
agent to repair it before monitoring. The supplied-source execution path works;
large-catalog discovery and retrieval quality were not exercised.

Still unproven: fresh companies and policies, owner ambiguity/clarification,
installation and connector onboarding by an actual user, live permission/freshness
changes, multi-step causal investigation, sustained drift, and an optimized paired
Luna cost/latency comparison. The optional bridge lives in the example agent; it
does not silently alter installed clients or supply an enterprise source directory.
The broader product goal remains open.

## Audit

Before dispatch: independent Luna adversarial preflight plus **1,698 passed,
3 skipped** in `make verify` (recorded local verification, not a trial metric).
A separate retained-result test recomputes all
twelve outcomes, routes and required-source checks from the frozen labels and
checks rejected attempts remain present. That offline audit is not a new live run.
Final local verification, including that added audit test: **1,699 passed,
3 skipped**; Ruff and whitespace checks passed.

After execution, the Luna adversary independently checked acceptance digests,
all twelve outcomes/routes/evidence sets, retained failures and usage accounting.
Its verdict was **pass for the bounded known-case repair**, not enterprise or
comparative approval. It specifically limited the finance result to signed-status
policy execution, not diagnostic explainability. This is internal adversarial
review, not external peer review.

Inspect the [manifest](evidence/bootstrap-empirical-repair-v2-01/manifest.json),
[report](evidence/bootstrap-empirical-repair-v2-01/report.json), and
[losslessly compressed journal](evidence/bootstrap-empirical-repair-v2-01/events.jsonl.gz).
The report verifies the source/data freeze before and after execution.

SHA-256 of the original uncompressed files (copies verified byte-identical):

```text
manifest.json  a794014c5f1eac4da411d7b78560a87e1bc5e7fa236519b2b4a462ceec63b83a
report.json    973333868541ada6ed34c21e3e1d4df7f4e77d1e00f8cfba5f29014b83c5400a
events.jsonl   48fc91193cc8dbb2a572d69b19e45ad0e0afab48a16f08af79ab903115dc6b8f
```
