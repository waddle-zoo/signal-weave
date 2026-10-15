# Evidence admission review

Reviewed 2026-10-01. Bounded adversarial review of evidence admission and
certification migration; no live or paid calls.

## Baseline and closure

At frozen commit `8dde234`, the initial admission suite produced **53 expected
failures and 16 passing controls**. It reproduced admission changing solely with
`follow_up_guidance`, missing explicit requirement policy, trusted cached slots,
and missing map persistence, approval binding, and MCP authoring exposure.
Existing required-source/comparison gates and question-change fingerprint controls
passed. These were ordinary failing tests, not expected-failure markers.

After implementation, the targeted closure run passed **72 admission tests and
41 certification-migration tests** (113 total). The existing cached-plan reuse
regression also passed separately. `git diff --check` passed.

Coverage includes strict boolean overrides for exact existing question/watch
keys, required-by-default semantics, optional unknowns remaining visible without
blocking, unconditional required-slot admission, preserved source/comparison
checks, cache-slot reconstruction, persistence, and approval fingerprints.
Certification tests exercise actual MCP tool dispatch with JSON and SQLite report
stores: missing, legacy, boolean, string, and future policy versions block
readiness; current policy still requires the other readiness gates. Reads preserve
old reports, and readiness does not fall back to an older compatible report when
the latest report is legacy.

## Cache finding and fix

The first cache repair rebuilt evidence slots but retained stale mirrored
`plan.questions`. An offline reproduction changed a question without changing
the card version: the card and rebuilt slot contained the new question while the
plan still contained the old question. The full plan enters the judgment state,
so this supplied contradictory policy context. No required-slot bypass was
demonstrated by that reproduction.

`InsightEngine.compile` now derives `evidence_slots`, `questions`, `watch_for`,
and `card_scope` from the current card when reusing a cached plan. The strengthened
same-version-edit test checks the mirrored fields, and the cache-reuse regression
checks that the stored cache is not mutated. This finding is closed by the
targeted tests; no additional evidence-admission blocker was found in this review.

## Verification and limits

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q \
  tests/test_evidence_admission_policy.py tests/test_evaluation_policy_version.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q \
  tests/test_engine.py::test_stored_compiled_plan_is_used_without_recompiling
```

These are deterministic offline contract tests, not live semantic validation,
enterprise certification, or proof of onboarding ease. No thresholds, golden
fixtures, historical results, or private trial labels were changed by this review.
The concurrent comparison-window contract and the final full-suite run are
outside this closure. Old audits remain historical evidence; current readiness
requires a fresh report under evidence admission policy version 1, not relabeling
an old approval.

## Subsequent comparison-window and projection review

A separate bounded pass reviewed exact source-declared identifiers, default
intersection, undeclared compatibility, approval blockers, catalog fingerprints,
and compact card reads. It found no remaining concrete privilege or
source-confirmation bypass in that scope. Main review also caught a runtime
boundary: an in-memory cached plan with an empty window list could bypass the
diagnostic comparison-window check. The engine now rejects empty or out-of-card
cached windows before reuse; the two mutation tests verify no Jev compilation
call occurs. Valid subsets remain accepted.

The completed window suite has 40 passing cases. Two additional configured-MCP
bridge cases verify that snapshot metadata and mutated catalog copies cannot
replace the manifest's capabilities; caller parameter injection is rejected.
Compact reads retain current review and plan, and explicit history reads return
the unchanged audit. These remain offline contracts, not evidence that an agent
will always choose the right business policy or that undeclared adapters support
an arbitrary comparison window. The final integration-suite and live regression
results are recorded separately in the repair ledger.
