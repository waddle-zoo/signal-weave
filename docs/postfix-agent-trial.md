# Guided onboarding trial

This trial asks a narrow question: does a guided onboarding review help a
general-purpose Luna agent create a usable monitoring card over a messy,
multi-adapter enterprise catalog?

The run used the real `gpt-5.6-luna` Responses API, the real SignalWeave MCP
registry, and the real Jev-backed discovery and evaluation path. Expected source
refs remained outside the agent prompt and scorer. Delivery stayed disabled.

## Trial design

- 20 enterprise/scenario sessions across Northstar Commerce, Harbor Bank, and
  OrbitWorks SaaS.
- Superset, SQL, Airflow, table-quality, incident, and calendar-shaped sources.
- Tenant-aware catalogs with intentionally repeated semantic titles and noisy
  related artifacts.
- The agent workflow was: discover → draft → `review_insight_card` → revise if
  needed → simulate → approve → evaluate.
- The review exposed Jev relevance, source reasons, omitted recommendations,
  catalog metadata, and ambiguous candidate groups.

## Results

| Measure | Before review | With review |
| --- | ---: | ---: |
| Sessions | 20 | 20 |
| Complete onboarding workflow | 7/20 | 17/20 |
| Complete cards | 10/20 | 19/20 |
| Complete provenance | 7/20 | 17/20 |
| Exact selected source sets | 0/20 | 1/20 |
| Required-source recall | 5% | 27.5% |
| Wrong-tenant data leaks | 0 | 0 |
| Unsafe automatic actions | 0 | 0 |
| Trace integrity | valid | valid; 1,665 events |

## What this proves

The review step materially improved workflow completion and card completeness.
It also made source ambiguity visible instead of silently selecting the first
matching dashboard or context artifact. The catalog fallback was fixed to bound
large local scans and interleave candidates from multiple adapters; previously,
large catalogs could fail validation or starve later adapters.

It does **not** prove autonomous onboarding. Exact source selection remained
poor because the fixture contains many near-duplicate resources with the same
semantic title. This is representative of a real enterprise problem: source
selection needs human confirmation when ownership, lineage, freshness, or
relationships disambiguate otherwise similar assets.

The current product claim should be:

> SignalWeave helps an agent turn a human's free-form operating intent into a
> reviewable, evidence-backed card. It does not silently decide which ambiguous
> enterprise asset the business meant.

## Artifacts

The latest raw run is in:

```text
artifacts/live-postfix-luna-2026-09-19-onboarding-v3.report.json
artifacts/live-postfix-luna-2026-09-19-onboarding-v3.trace.jsonl
```

The labels remain independent of the agent. The result is evidence for the
onboarding boundary, not a universal accuracy claim for every enterprise
catalog.
