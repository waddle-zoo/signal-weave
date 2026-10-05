# SignalWeave live comparative evidence summary — 2026-10-06

## Question

Does a frontier `gpt-5.6-luna` agent do more useful, safer analytical work when
it receives SignalWeave's live Jev retrieval/preflight layer, compared with the
same agent using the same cards, connectors, snapshots, permissions, tools,
and task budget without SignalWeave?

The answer is **yes for a bounded class of evidence-handoff, ambiguity, and
push-gating workflows; not yet proven for universal correctness, lower
provider cost, or production autonomy**.

## Live comparisons

| Trial | Scope | Luna only | Luna + SignalWeave/Jev | What it establishes |
| --- | --- | ---: | ---: | --- |
| Existing paired research package | 56 paired single-step runs across 7 workflow families and 3 live replays | 26/56 exact; 30 unsafe automatic actions | 50/56 exact; 3 unsafe automatic actions | Strongest evidence for ambiguous/root-cause, definition-conflict, and cross-card evidence packaging; descriptive, synthetic, and cost-limited |
| Helio Support | 3 connected-Preset-shaped MCP cases | 3/3 exact; 1 diagnostic query | 3/3 exact; 0 diagnostic queries | Jev preserved correctness and removed redundant exploration; no dollar saving proven |
| Cinder Database Cloud | 3 held-out periods after human onboarding | 3/3 exact | 3/3 exact; 33% fewer downstream wakeups; 57.8% less active warm-agent time | Push-gated quiet periods and safe incident/data-gap routing |
| Juniper Trail + Lumen Freight | 6 held-out periods across two companies after onboarding | 3/6 exact; 50% numeric precision | 6/6 exact; 100% numeric precision; 33% fewer wakeups; 56.2% less active warm-agent time | Better numeric evidence handoff without changing outcome or recipient |
| Northstar multi-step | 6 held-out cases covering quiet, material, diagnostic, conflicting, and missing-source paths | 3/6 final exact; 2 unsafe terminal outcomes | 5/6 final exact; 1 unsafe terminal outcome; 91.7% vs 83.3% evidence recall | Jev improved two multi-step evidence handoffs, was never worse, but did not fix every frontier-agent omission |

All current live comparison reports were independently re-scored from raw
submissions. The current Northstar review passed with zero findings after a
runner/reviewer provenance mismatch was fixed. The full repository suite is
green: **2463 passed, 5 skipped**.

## What the evidence supports

1. **The value is not Jev doing the analysis.** Luna remains responsible for
   interpretation, causal caution, and the caller-owned diagnostic follow-up.
   Jev contributes typed retrieval/path judgments, evidence selection, and
   push-gating context before the agent wakes.
2. **The strongest effect is on messy handoffs.** The largest gains occur when
   the agent must distinguish an ordinary movement from a meaningful one,
   reconcile conflicting definitions, assemble multi-source evidence, or
   abstain because a source is unavailable.
3. **Push gating can remove human/agent toil.** In the held-out Cinder and
   Juniper/Lumen trials, complete quiet outcomes did not wake the downstream
   agent. This is the practical benefit of a trusted preflight layer: humans
   do not inspect dashboards or receive a bare alert for every scheduled run.
4. **The result is reproducible enough to justify a shadow trial.** The same
   cards and snapshots, live Jev, paired baselines, hidden labels, source
   provenance, and independent recomputation are all present in the retained
   protocols and reports.

## What the evidence does not support

- It does not prove Jev or SignalWeave is universally more accurate than Luna.
  The six-case Northstar run still had one evidence-completeness failure in
  both arms.
- It does not prove lower provider cost. Jev adds requests and tokens, and the
  Cinder/Juniper-Lumen reports explicitly show illustrative treatment costs
  above baseline. Real warehouse invoices and provider billing are not yet in
  the harness.
- It does not prove lower latency. Jev was faster than the agent's avoided
  work in some recurring trials, but the Northstar multi-step treatment added
  a median 0.58 seconds end-to-end.
- It does not prove hosted-Preset, Hex, Looker, or Trino production transport.
  Those integrations are represented by connector-shaped fixtures and local
  adapters, not a customer tenant or production invoice.
- It does not authorize autonomous external delivery. The safe posture remains
  read-only shadow mode or human-approved delivery until a larger real-history
  replay shows zero unacceptable automatic actions under governed destinations.

## Adversarial findings and repairs

- A Cinder onboarding run incorrectly promoted source-completeness and
  population-validity rules into free-form `watch_for` requirements. Jev
  preferred the quiet path, but the safety fallback produced a false
  investigation. The onboarding guidance was corrected to keep computable
  constraints in typed source/comparison contracts, then the held-out run was
  repeated successfully.
- The Northstar multi-step scorer treated an authorized source citation as
  provenance-valid only after a tool event, while its independent reviewer
  accepted the source contract. The runner was corrected, a regression test
  added, and the live six-case run was repeated. The independent reviewer now
  recomputes the runner's result exactly.
- The current Northstar card still leaves the required evidence contract more
  implicit than ideal. One quiet case made the correct decision but omitted a
  required corroborating citation in both arms. This is a remaining product
  and experiment-design gap, not evidence of Jev superiority.

## Adoption conclusion

SignalWeave is now defensible as a **Jev-backed retrieval, evidence, and
push-gating layer for frontier agents operating over messy analytical context**.
The compelling enterprise pitch is reduced dashboard inspection and better
evidence-complete handoffs, not “Jev replaces an analyst” or “Jev makes every
query cheaper.”

The next proof needed before claiming enterprise-wide readiness is a shadow
deployment or anonymized historical replay from one real team with governed
destinations, real provider/query telemetry, an explicit owner-authored
evidence contract, and repeated paired runs across enough periods to estimate
false-alert and safe-abstention rates.

Supporting reports:

- [Paired-agent research results](../paired-agent-trial-results.md)
- [Helio connected-Preset comparison](helio-preset-mcp-paired-2026-10-06.md)
- [Cinder held-out comparison](cinder-heldout-live-comparison-2026-10-06.md)
- [Juniper/Lumen held-out comparison](juniper-lumen-heldout-live-comparison-2026-10-06.md)
- [Northstar multi-step comparison](northstar-multistep-paired-live-comparison-2026-10-06.md)
