# Empirical authoring v1: failed onboarding, useful diagnosis

This trial **did not pass the onboarding goal** and establishes no advantage over
Luna. Frozen implementation: `5abd4d3`. Three synthetic companies, nine labeled
setup examples and twelve monitoring cases; live `jev-1.13.0` and saved-login
`gpt-5.6-luna` at low reasoning effort. No external delivery occurred.

## Results

| Company | Authoring setup | Expert Jev monitoring | Authored Jev monitoring |
| --- | --- | --- | --- |
| Support SLA | Failed after 2 tests | 4/4 exact | Unavailable |
| Database operations | Failed before any test | 4/4 exact | Unavailable |
| Finance approvals | Passed on test 2 | 4/4 exact | 3/4 exact; one missing route |

“Exact” includes outcome, delivery keys, exact endpoints and required evidence.
The finance card selected the right outcome in all four cases but omitted the
owner-requested Finance review route for an unresolved signed status. The setup
examples did not cover that fourth policy branch. Passing those examples was
not proof of the complete policy, as the protocol explicitly warned.

Across the intended twelve automated runs, only three fully succeeded: eight
were unavailable because authoring failed, and one lacked its route. Do not
report the three successful runs as 100% accuracy by dropping the others.

The expert controls are bounded **live semantic execution evidence**, not just
offline plumbing. They do not validate novice onboarding, discovery at scale,
live connectors, causal diagnosis, or enterprise-wide generalization.

## Baseline validator defect

The retained protocol scorer accepted only **5/12** Luna submissions. Its seven
rejections were a harness defect: the model cited current source keys or actual
fact provenance, while the validator accepted only `adapter|resource` strings.

Independent inspection found the expected outcome and recipients in **all 12
attempted answers**, including the seven rejected submissions. Exact lookup of
their identifiers against the current case's evidence establishes their source
grounding. These were not seven observed business-decision errors.

The original report and events remain unchanged. The 12/12 figure is a separate,
post-hoc audit of attempted answers, not twelve successfully completed episodes
under the original submission contract. It cannot be used to claim a Jev win.
Future validation accepts exact, unambiguous current-source identifiers and
retains the original citation; it does not guess aliases or accept old fact IDs.

## What failed

- **Support:** the author invented bounded follow-up retrieval for a registry-free
  replay and a confidence floor of 1.0. Its repair removed the unsupported stage
  but retained that floor. Jev selected notify and ignore with 0.99 support; code
  correctly applied the card's stricter setting and routed to investigation.
- **Database:** enum, evidence-slot and source-declaration errors prevented any
  candidate evaluation. Zero semantic Jev calls occurred for its authoring.
- **Finance:** removing unsupported follow-up retrieval repaired setup. The author
  still omitted a route present in the full owner policy but absent from the
  three setup examples. Monitoring exposed that omission.

The trial required the author to construct a full storage-shaped card, including
technical settings and nested source declarations. That is not the same interface
as the product's flat `draft_insight_card` tool. Treat these interface failures as
diagnosis of this path, not proof that every installed onboarding path fails.

## Resource accounting

32 Jev attempts; zero retries; 15 Codex episodes; source/data freeze verified.
Jev reported 212,397 input and 6,653 output tokens. Codex authoring reported
843,090 input tokens (695,296 cached), 16,482 output tokens and 357.12 seconds.
The twelve baseline episodes reported 523,296 input tokens (378,880 cached),
4,425 output tokens and 153.42 seconds.

The twelve expert runs had median engine latency **246 ms**, summing to 3.24
seconds. The four authored finance runs had median **233 ms**, summing to 0.91
seconds. These are supplied-snapshot engine timings, not warehouse/query latency.
CLI episodes include startup and agent overhead, and retain setup examples on
each call. They are not an optimized warm-model comparison or measured invoices.
Onboarding failed, so a favorable per-call timing cannot establish product ROI.

## Review and next check

A Luna adversary and the main reviewer examined code and retained results. The
adversary rejected promotion and comparative-win claims. This is internal review,
not external peer review. The follow-up is [a separately declared, capped
development regression](bootstrap-empirical-repair-v2.md), not a new holdout.

Inspect the [frozen inputs and hashes](evidence/bootstrap-empirical-v1-01/manifest.json),
[unchanged report](evidence/bootstrap-empirical-v1-01/report.json), and
[compressed raw journal](evidence/bootstrap-empirical-v1-01/events.jsonl.gz).
The journal is a lossless compression of the original, including failed attempts.

SHA-256 of the original uncompressed files (copies verified byte-identical):

```text
manifest.json  1ec3c55ca12aa09efda5070778bbb33d21ef300876e7ebbac9ec1b08e49a1001
report.json    37a94426556a0ac15f73fe90c1b46206010818268898a288df5a1f50e94d0c6d
events.jsonl   d2ab3667d0b00531816b2cf4249aacd292b5356fba2f532047cc028236b1bd06
```
