# Typed evidence-contract gate: live Jev regression

Date: 2026-10-04
Run: `evidence-contract-gate-live-01`
Model: `jev-1.13.0`
Delivery: disabled; no notification sink was invoked

## Question

Why did the earlier evidence-sufficiency trial fail even though the owner card
and source prose described the expected population and metric definitions?

The earlier run sent Jev raw values plus prose and expected it to infer whether
the provider had measured the complete population and comparable periods. On
the six primary cases, repeated twice, that produced 8/12 exact business
routes (66.7%). Typed observation normalization did not improve it: it kept
the same 8/12 result. The missing fact was not language understanding; it was
an adapter-owned measurement contract.

## Change under test

Resources can now expose `ResourceContract.comparison_contracts`. Each scalar
contract declares its exact key, metric definition, population, unit, window,
coverage, comparability, and provider references. The engine then:

1. requires every card-bound comparison key to be present;
2. fails closed when the provider declares coverage `partial` or `unknown`, or
   `comparable=false`;
3. admits a scalar contract as primary evidence only when it is complete and
   comparable; and
4. lets Jev explain and classify the admitted evidence, while code owns the
   completeness gate and workflow handoff.

This is source-adapter metadata, not a new dashboard-specific rule. A Superset,
Preset, Hex, Looker, Trino, CloudWatch, or internal MCP adapter can supply the
same contract when its provider response can support it.

## Protocol

- One retained database-performance card and six cases: quiet, actionable, and
  four incomplete-population controls.
- The card was bound to two exact scalar keys: query p95 latency and replication
  lag for the previous period.
- Six cases were shuffled and repeated twice: 12 live Jev attempts, no retries,
  one request per case, one resolved model.
- Gold outcomes and delivery routes stayed evaluator-only; request payloads
  were audited for evaluator-label leakage.
- The run was a regression over the known failure family, not a general
  accuracy claim or an enterprise trial.

## Result

| Measure | Result |
| --- | ---: |
| Exact outcome + configured route + workflow handoff | **12/12 (100%)** |
| Incomplete cases routed to `repair_source / blocked` | **8/8** |
| Actionable cases routed to `retrieve_evidence / pending` | **2/2** |
| Quiet cases routed to `suppress / complete` | **2/2** |
| Jev API errors | **0** |
| Evaluator-label leaks in requests | **0** |
| Median Jev latency | **237 ms** |
| Jev input/output tokens | **82,766 / 1,048** |
| Real deliveries | **0** |

The live report and every request/response are retained in
[`docs/evidence/evidence-contract-gate-2026-10-04/`](evidence/evidence-contract-gate-2026-10-04/).
The archived report is explicitly marked as rebuilt: all 12 Jev calls completed,
but the first reporter crashed after the final call on a bookkeeping bug. The
report was reconstructed from the retained attempt files and trace without
spending another Jev call. The exclusive writer and a regression test now cover
that failure mode.

## What this proves

The identified failure is fixed for this source-contract family. Jev is useful
once the adapter provides the fact the model cannot safely infer: whether a
measurement is complete and comparable. The engine can then use Jev for the
semantic judgment without allowing a confident model answer to override a
provider-declared evidence defect.

## What this does not prove

This is not proof of perfect onboarding, universal chart support, or 100%
notification precision across enterprises. It does not yet cover a fresh
business domain, a real Superset response carrying these contracts, an
agent-authored onboarding session, or a matched Luna-only baseline. Those are
the next gates before calling the local product enterprise-ready.
