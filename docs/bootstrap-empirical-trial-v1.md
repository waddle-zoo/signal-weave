# Empirical card authoring trial v1

## Question

Can a Luna author turn complete owner context into a working recurring Jev card,
use setup failures to correct it, and then execute correctly on unseen evidence?
Separate authoring quality from the quality and cost of recurring execution.

This is a bounded mechanism trial, not an enterprise-readiness claim. The prior
reviewed-card regression passed; the prior novice bootstrap comparison failed.
Neither result is replaced by this trial.

## Inputs and arms

Three synthetic companies cover SLA deterioration, correlated database-service
regressions, and approval-record interpretation. Each has three owner-labeled
setup examples and four different monitoring cases. Source scope, completeness,
measurement periods and numeric changes are explicit; no model must invent an
unstated coverage guarantee or perform hidden arithmetic to earn the label.
Finance includes a fourth policy branch (an unresolved signed status routes to
review) in monitoring only. Its three setup examples therefore cannot certify
coverage of the entire policy; the unseen branch is an additional challenge.
Other monitoring cases test new snapshots of known rules, not new companies or
entirely new business rules.

1. **Authoring:** saved-login Codex `gpt-5.6-luna`, low effort, receives complete
   free-form owner policy, approved source/destination references and labeled setup
   examples. It never receives the expert card or monitoring cases during setup.
   At most two candidate tests compile and replay its draft through live Jev and
   the existing strict workflow acceptance evaluator. Diagnostics may inform the
   next draft. Passing setup is frozen before monitoring; failure is retained.
2. **Authored card + Jev:** run the frozen accepted card on each unseen case, with
   no reasoning agent repairing or overriding its outcome. Count missing runs
   caused by failed authoring as unavailable, not as successful abstentions.
3. **Expert card + Jev:** use a separately authored reference card on the same
   monitoring evidence. This measures the remaining authoring gap, not an oracle
   supplied to the author.
4. **Luna execution baseline:** same owner policy, setup examples, current evidence
   and accepted authored card when one exists. No future cases, hidden labels or
   expert card. Where authoring failed, report the baseline separately rather than
   pretending it received an equivalent accepted card.

Setup labels are intentionally available to both model arms; monitoring labels
are scored only by the parent evaluator. No labels are added to Jev state.
The baseline may inspect all supplied evidence; this is not a restricted lexical
retrieval baseline. Saved setup examples/card preserve context across runs.

The author uses a research-only MCP wrapper around the production compiler and
workflow evaluator. This does not test the complete installed onboarding MCP
tool sequence or actual owner approval. Evidence is already supplied as bounded
snapshots: adapter names identify source kinds, not live Preset or Trino calls.
Historical replay uses the observation-time clock, not today's wall clock.
These timing results exclude warehouse queries and source discovery.
Required evidence labels identify indispensable sources. Retrieval-reference
labels identify the supplied snapshot bundle; they do not prove discovery or
ranking quality. The database CPU source is diagnostic, not a prerequisite.

## Running it

From the repository, an offline invocation writes the frozen inputs only:

```sh
uv run python -m evaluations.bootstrap_empirical_trial --output artifacts/empirical-plan
```

After review, live execution requires an explicit opt-in, an existing saved Codex
login and a TypeSafe key file. Use a new output directory for every attempt:

```sh
uv run python -m evaluations.bootstrap_empirical_trial \
  --live --jev-key-file /path/to/private-key \
  --output artifacts/empirical-live-01
```

`manifest.json` retains the frozen inputs and code hashes, `events.jsonl` the
requests, responses and tool activity, and `report.json` the results. A completed
runner is not a passed product evaluation; inspect acceptance and every case.
The default offline invocation makes no semantic-success claim.

## Freeze and resource limits

Internal Luna preflight review initially withheld approval over optional-source
handling, incomplete diagnostic retention and partial-run accounting. Those were
repaired, along with a native-run serialization bug found by the main reviewer.
Final targeted review cleared dispatch. Verification before dispatch: full suite
1,666 passed / 3 skipped before the last harness-only fixes; the final focused
fixture, runner and transport suite passed 58 tests, plus Ruff and diff checks.
This is internal agent review, not independent external peer review.

- Record dataset/source/prompt hashes before dispatch; keep source unchanged
  during execution. Use a new exclusive output directory for each trial.
- Global ceiling: 72 Jev attempts, including failures; zero automatic retries.
- Three author episodes and twelve baseline episodes at most. Record CLI errors,
  timeouts, invalid submissions and foreign-tool use; none can approve a card.
- Codex runs in an empty temporary directory with only the bounded trial MCP.
  The parent alone holds credentials and private monitoring labels.
- Record setup and monitoring usage separately. Codex subscription usage is not
  an API invoice; no invented dollar-cost or ROI claims.
- No external notification, production data or production approval occurs.
- Do not edit prompts/labels mid-run, lower thresholds or rerun until green.

## Primary observations

The mechanism acceptance target is three accepted authored cards and twelve of
twelve correct native monitoring outcomes, exact destination sets and required
evidence references, with no runtime errors. Report each component independently;
one correct component cannot conceal another failure. Setup success does not count
as monitoring success. Expert-control failure is a separate execution problem,
not automatically an authoring failure. First-attempt success would not demonstrate
that diagnostic feedback caused an improvement. Even a successful second attempt
would be a correction example, not a randomized estimate of the repair loop's effect.

Report per company: candidate attempts, first/final setup acceptance, correction
reasons, final card binding and unavailable monitoring runs. Report per monitoring
case: exact outcome and destination, evidence-reference correctness, runtime errors,
raw Jev distributions, usage and latency. Keep native outcomes distinct from the
baseline's narrative, and review explanations separately rather than implying
that correct routing proves correct causal reasoning.

An independent reviewer checks each baseline explanation against the supplied
evidence: supported, qualified (minor omission or imprecision), or unsupported
(invented fact, numerical error, or unearned causal claim). Jev distributions are
model outputs, not measured probabilities of real-world causation. The reviewer
also checks the native evidence bundle; a correct routing label alone cannot
validate the bundle. This is internal adversarial review, not external peer review.

Passing all supplied cases would support this bounded onboarding mechanism. It
would not prove generalization across arbitrary companies, large-catalog retrieval,
live connector operation or months of useful push analytics. Any meaningful cost
comparison must include setup and eventual exception investigations, not merely
compare a Jev request with an entire CLI startup.
The Luna baseline retains the labeled setup examples on each call, while native
Jev receives the compiled card and current evidence. This favors baseline context
availability but increases its recurring input. It is not a token-minimized or
warm-session Luna baseline; do not attribute the entire token/latency difference
to Jev model efficiency.
