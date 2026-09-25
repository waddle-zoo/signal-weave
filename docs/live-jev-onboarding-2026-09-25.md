# Live Jev onboarding evidence

**Run date:** 2026-09-25
**Branch:** `feat/decision-feedback-contract`
**Evaluator:** TypeSafe Jev (`jev-live`)
**Scope:** bounded semantic retrieval and onboarding, not autonomous delivery

The previous onboarding result was fixture-backed. This replay used the real
TypeSafe evaluator against eight deliberately different enterprise cases from
the repository's onboarding corpus:

- cross-dashboard and BI/query-job goals;
- Hex-style run freshness;
- source-quality-first monitoring;
- same-name tenant decoys;
- sparse semantic aliases and sparse lineage; and
- an intentionally ambiguous fintech metric definition.

The case metadata supplied to Jev contained the user goal and candidate
resource metadata only. Expected labels were retained by the scorer and were
not included in resource descriptions, titles, IDs, or the Jev request. The
repository test `test_scenario_metadata_does_not_leak_hidden_case_labels`
checks that separation for the generated corpus.

## Result

| Measure | Result |
| --- | ---: |
| Live Jev cases | 8 |
| Required-candidate recall | 8/8 (1.00) |
| Safe onboarding outcomes | 8/8 |
| Prototype readiness gates | 8/8 |
| Exact recommended sets | 7/8 |
| Wrong-tenant candidate leaks | 0 |
| Governed role disagreements | 0/19 |
| Human-review behavior | 8/8 cases retained review/block state |

The one non-exact recommendation was `fintech-definition-ambiguity`: Jev
returned one of two semantically plausible definitions, while the expected
set required both. The onboarding contract did not silently approve it. It
surfaced `definition-conflict` and kept the card in human review. That is a
known ambiguity, not a hidden safety failure.

## Reproduction

The bounded run used eight TypeSafe requests and did not print or copy the API
key:

```bash
./.venv/bin/python -m evaluations.onboarding_contract_trial \
  --evaluator live \
  --typesafe-key-file /Users/brandonsovran/Downloads/apikey_typesafe \
  --limit 8 \
  --format markdown
```

The same code path also supports the full 30-case fixture contract. The live
run is intentionally a sample, not a claim that eight cases establish
universal semantic accuracy.

## What this adds to the evidence

This closes two gaps in the earlier report:

1. Jev's candidate ranking is exercised live without expected labels in its
   input; the result is not merely a deterministic fixture score.
2. The strongest ambiguity case is measured as a review-preserving outcome,
   rather than being converted into an automatic decision.

It does not prove arbitrary-catalog recall, warehouse cost savings, or
customer-specific business correctness. Those still require a customer's
authorized catalog, card definitions, and operator labels.
