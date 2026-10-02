# Why the recurring-report benchmark failed

This investigation tests mechanisms, not a predetermined success story. The
[earlier paired trial](business-outcome-trial.md) remains **10/12 versus Luna's
12/12**. No result below replaces that denominator.

## Hypotheses and frozen boundaries

1. **State sensitivity:** the old requests duplicated the card and observation
   fields and included a plan whose evidence slots still said `pending`.
   Replay six known failure/control inputs in three arms: retained original
   state, remove exact duplicate aliases, or remove the plan. Questions,
   evidence, business policy and confidence floor stay unchanged. Plan removal
   removes unique context as well as pending slots; it is not deduplication.
2. **Composition:** compile plain-English policy once with Luna, before seeing
   measurements. Code handles catalog-bound numeric comparisons and explicit
   ordered Boolean rules; live Jev handles narrow semantic conditions. Compare
   this with a broad Jev outcome judgment and a persistent Luna reporter given
   the same policy, compiled plan, evidence and numeric checks.

The second experiment is an evaluation-only prototype. It does not introduce
a production policy language, change card approval, or claim that generated
plans have been semantically approved. A syntax-valid plan can still be wrong.

The current [TypeSafe guidance on Jev's limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
recommends exact numeric operations in code, direct conditions, relevant state,
and code-enforced composition rather than assuming consistency between separate
judgments. That motivates the experiment; it does not predict the result.

## Predeclared fresh-company experiment

Twelve cases across three new synthetic companies cover OR/AND conditions,
offsetting movements, directional increases, exceptions, conflicting authority,
missing data and qualitative contract-release checks. A separate agent authored
the fixtures and explicit labels before live outputs; another offline audit
recomputed their measurements. This is internal AI review, not human peer review.

- Three Luna setup episodes see only policy and a typed measurement catalog.
  They never see case facts, labels or descriptive case IDs. All plans are saved
  before recurring episodes begin. No manual plan repairs or retries to success.
- Six recurring Luna episodes: one persistent baseline and one writer per
  company, four sequential periods each, counterbalanced arm order.
- Twelve Jev requests maximum. Each contains independent narrow questions and
  one broad outcome question over the same state. The broad answer cannot see
  the narrow answers; only the code-composed result reaches the treatment writer.
  This measures composition, not isolated per-arm Jev latency.
- Numeric checks use the same catalog fields and operators for both arms.
  Unknown is not false. An unresolved earlier rule cannot silently fall through
  to a later automatic action. The unchanged semantic support floor is 0.70.
- Both reporting arms read each period once, reuse that bundle and cite the same
  fact IDs. Recipients are bound to policy-owned routes equally in both arms.
  No actual notifications or queries against customer systems occur.
- Report all twelve intended cases, including missing submissions. Review plans
  and final narratives separately. Citation/schema validity is not truth.
- A product advantage requires correct reports and lower whole-workflow cost or
  time, not just fast Jev calls. Report setup and recurring usage separately.
  Tokens are not dollar invoices, and source reads are not human hours saved.

These cases do not test retrieval from a large catalog, unknown source schemas,
warehouse execution, customer onboarding, drift or production authorization.
There is only one live observation per case. Even a perfect result would be a
bounded mechanism result, not enterprise readiness or universal superiority.

## Reproduce

Without `--live`, both commands prepare manifests without credentials or calls.
Use a new output directory each time; all failed attempts remain available.

```sh
python -m evaluations.judgment_input_ablation \
  --primary docs/evidence/business-outcomes-live-01 \
  --output artifacts/judgment-input-ablation-new
python -m evaluations.policy_composition_trial \
  --output artifacts/policy-composition-new
```

For live runs, add `--live --jev-key-file /path/to/private/key`. The second
command uses the locally authenticated Codex CLI for Luna, with a scoped
localhost MCP and no shell, workspace, web or private-label access.

## Results

Results and reviewer findings are appended after the frozen run. Research code
and fixtures stay outside `src/`; the shipped runtime remains unchanged.
