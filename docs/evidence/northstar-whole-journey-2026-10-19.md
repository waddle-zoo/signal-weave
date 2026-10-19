# Northstar: fresh setup through seven weekly reviews

An agent onboarded a fictional retailer through the actual native executable,
Codex and local Superset, authored its own SQL and card, obtained owner approval,
and reused that card for seven live-Jev evaluations. Independent data and product
reviewers checked the delivered messages—not just the decision labels. The
weekly headline figures and routes were supported. Reporting was too verbose,
and the capable baseline was faster and used fewer frontier tokens.

The [compact execution record](../../evaluations/data/northstar-whole-journey-2026-10-19-summary.json)
contains the actual baseline and forward-treatment messages, evidence-file hashes,
usage, policy calls and review findings. The earlier treatment's failure and costs
remain recorded. Large traces, databases, credentials and binaries stay untracked.

## What the company received

Dispatch wanted a weekly digest and an investigation when damaged shipments
exceeded 2% of the promised-date cohort, with at least 400 shipments. All seven
dates must be represented before calling a week clear. Missing dates go
separately to Data Operations; carrier differences are leads, not causes.

| Promised dates, 2026 | Raw damaged / shipments | Represented dates | Live Jev policy |
| --- | ---: | ---: | --- |
| Jul 27–Aug 2 | 5 / 511 = 0.98% | 7/7 | `ignore` |
| Aug 3–9 | 12 / 497 = 2.41% | 7/7 | `investigate` |
| Aug 10–16 | 4 / 527 = 0.76% | 7/7 | `ignore` |
| Aug 17–23 | 4 / 524 = 0.76% | 7/7 | `ignore` |
| Aug 24–30 | 6 / 502 = 1.20% | 7/7 | `ignore` |
| Aug 31–Sep 6 | 3 / 504 = 0.60% | 7/7 | `ignore` |
| Sep 7–13 | 0 / 154 observed | 5/7 | `insufficient_data` |

All seven Dispatch digests arrived. The qualifying week's investigation included
the twelve affected shipment records and carrier contributions: Summit 7/120,
Pioneer 4/126, Northstar Parcel 1/106 and Maple 0/145. It suggested checking
handling evidence without inventing a cause, accepted assignment or repair.

The last digest did not turn zero observed damages into an all-clear. It named
the absent Sep 12–13 dates and asked Data Operations whether those were valid
zero-volume dates or missing coverage. The extra Data Operations clarification
repeated information already sent: nine messages were delivered in total, of
which one was redundant. All twelve attached files were present and matched
their recorded sizes and hashes. Delivery and replies used local simulation
inboxes, not Slack or real company recipients.

## The whole onboarding path

The current GitHub Actions native archive was checksum-verified and installed
into a fresh fake person's home. The real wizard stored credentials privately,
connected Superset and registered the exact executable with isolated Codex.
Its ten scripted prompts took 6.62 seconds; that is not measured human reading
time or a test of the published curl installer.

The analyst started without analytical SQL or a card. It discovered the source,
asked the owner, wrote and checked its own query, and requested one real CLI
import through the existing Superset connection. It inspected that result,
showed the actual saved card and source scope, obtained explicit consent and
completed native approval. Card version 1 and the same imported SQL served all
seven periods. One malformed workflow argument was rejected before inference
and corrected by the agent itself; no researcher repaired its SQL or card.

Both arms retained the same 27 analytical tools from the real community Superset
MCP, business information, workspace, SQL/code capabilities and reusable notes.
The baseline was not forced to forget its work or deprived of source tools.
Raw shipment checks covered 70,000 records. This is a retrospective review of
the complete finalized warehouse, not an as-known-at-the-time backtest: later
outcomes were available to both agents, and the period selector did not alter
retrieval freshness.

## Effort, including the negative result

| Whole actor stage | BI tools + Luna | Forward SignalWeave + Jev |
| --- | ---: | ---: |
| Elapsed seconds | 398.53 | 846.72 |
| Actor and hidden MCP calls | 54 | 89 |
| Workspace operations | 28 | 34 |
| Frontier input tokens, including cache | 5,203,523 | 13,516,047 |
| Uncached frontier input tokens | 131,011 | 325,391 |
| Frontier output tokens | 37,755 | 81,800 |
| Messages / readable attachments | 8 / 0 | 9 / 12 |
| Live Jev requests | 0 | 7 |

Jev used 92,376 input and 1,406 output tokens. Individual policy calls took
0.221–0.375 seconds. Those fast calls did not make the complete reporting job
faster. No overall efficiency, billing, accuracy or causal advantage is shown.
The baseline's source locators were not recipient-open attachments; treatment
provided accessible detail but added process clutter and a duplicate message.

Before this forward run, a treatment completed useful fallback reports but
remained in draft: our scripted owner dodged explicit card-approval questions.
It made zero Jev calls, took 947.14 seconds, and used 278,420 uncached frontier
input / 97,538 output tokens. We repaired the simulated owner, not the product's
approval guard, then started a separate fresh treatment. That prior attempt and
its three query imports remain in the record. This is not a clean new paired
comparison or a rescore that excludes failed work.

## What review changed

Internal independent reviews found no material numerical, date-bound, causal or
repair overclaim in the nine forward messages. Six reader stages passed; the
digest stage needs revision for repeated card/runtime explanations and secondary
metrics. The extra Data Operations message was redundant after a canned reply.
Repeated scripted acknowledgements are not independent endorsements.

The trial exposed a presentation problem: query results legitimately used
Evidence rows without Observation mappings. All 23 evidence rows were already
inline in each of the seven recorded native responses, verified against the
immutable receipts. Nevertheless, generated comparison reports had no numeric
claims, and the agent repeated “partial report” mechanics to readers. Missing
engine comparisons were being confused with missing source quantities.

A separate oversized-response regression reproduced lost inline evidence above
the compact handoff bound. The forward changes address that generic paging gap
and clarify the generated-report language; they did not cause or improve the
recorded Northstar results. Fresh-native and agent validation remain required.

This job deliberately requested a digest every week. It does not test the
separate exception-only pattern where the caller starts a frontier analyst only
when a policy needs attention. It also does not exercise shared-context memory,
another team's onboarding, changed business definitions or hosted multi-user use.

## Reproduction and scope

The [journey runner](../../evaluations/northstar_enterprise_journey.py) exposes
fresh `prepare`, zero-inference `preflight` and reviewed `actor` execution. Its
retained forward-study ledger prevents replacing the original pair. The
[public lab](../../examples/northstar-enterprise-lab/README.md) includes the
synthetic generator and Superset seed; offline checks reproduce all sixteen
original CSV hashes without committing the generated data. Read its runtime
verification boundary separately from the executed original local instance.

The executed native production fingerprint was
`a4a27dbfc34b0c3c9126dd344f75e7b45f90eff33381243ec0e7bb122de79255`
(embedded commit `04dedb3`). Subsequent source changes require a new matching
binary. This is one fictional company and seven dependent historical cohorts,
not seven independent enterprise trials or external peer review. Together with
the [Pine whole journey](pine-whole-journey-2026-10-19.md), it establishes working
onboarding-to-delivery paths—not enterprise-wide superiority.

### Current native: separate first-class Superset connection check

The clean `97a5daa` native build completed fresh scripted terminal setup against
the isolated Northstar replica: Superset credentials, Codex registration,
bundled skill, source health and two cold native MCP starts. Each start returned
a schema-valid, nonempty snapshot of the selected fulfillment chart: 132 rows.
This used the production Superset adapter, not a normalized company-MCP bridge.
No model judgment ran. Earlier setup-observer failures were retained and fixed
before the fresh successful attempt.

This verifies connection and source access, not another analytical journey,
all-chart coverage, correct business aggregation or novice-human usability.
Dashboard inspection also fetched other charts and produced failed fallback
GETs; the selected chart's successful read does not certify the whole dashboard.
The existing replica was reused; a fresh Superset image build was not tested.
