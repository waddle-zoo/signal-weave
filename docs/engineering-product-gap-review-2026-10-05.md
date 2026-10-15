# Engineering and product gap review — 2026-10-05

## Verdict

SignalWeave has useful building blocks for a local agent companion: a human-facing
CLI, Superset/Preset/Trino and reviewed-MCP source paths, source normalization,
cards, typed Jev judgments, provenance-bearing receipts, and optional report
coverage. That is not yet proof that a user can install it, ask Codex or Claude
to analyze their BI, and reliably get better answers than the same agent using
its existing BI tools directly.

The biggest gap is not “more governance.” It is the missing handoff between the
frontier agent's analysis and SignalWeave's repeatable decision path. The agent
can reason over BI tools, but the approved-card MCP runtime does not accept a
typed, provenance-bound analysis bundle from that agent. It fetches the selected
card's own sources and asks Jev to judge those observations. The latest Helio
trial exercised that weaker path and lost to Luna; its own report correctly
labels the result exploratory and contaminated, not product proof.

## Findings

### P0 — The runtime does not match the intended agent-plus-Jev split

`evaluate_insight_card` accepts a stored `card_id`, context, and run metadata; it
does not accept caller-computed measurements, comparisons, evidence references,
or data-quality findings. `ContextSnapshot` carries narrative facts and
provenance strings, not validated numeric facts with grain, units, population,
time windows, and source identity. The MCP path also marks supplied context
unverified, and the engine prevents unverified context from authorizing
`notify`/`escalate`.

This blocks the product shape the team has described: Codex/Claude does the
heavy analysis through BI MCPs and SQL tools; SignalWeave retrieves relevant
card context and applies a consistent, typed decision to that analysis. The
solution is not to trust arbitrary agent prose. It is a bounded typed handoff
that binds each claim to authorized source IDs, query/run references, time
windows, metric definitions, and computation provenance, while preserving
unknown/conflicting states.

### P0 — Current “proof” does not establish added value

The 2026-10-05 Helio local-Superset trial is a diagnostic result, not a fair
comparison. It passed raw chart rows to Jev rather than having the frontier
agent compute the comparisons first. It reports 3/12 Jev versus 11/12 Luna on
observed adjacent-month cases, and explicitly identifies class-label leakage in
the broader 30-case prompt set. Cases also reuse one synthetic company's charts
and periods. It did not test first-run onboarding, real hosted Preset, or the
intended typed agent-analysis handoff. See the [trial report](evidence/helio-local-superset-paired-trial-2026-10-05.md).

Do not publish its aggregate accuracy as a benchmark. Keep it as useful failure
evidence until a blinded, same-tools/same-model paired run tests the intended
architecture.

### P1 — “Query a metric” stops before executing the query

The local query-card path can propose a plan, compile bounded SQL, and approve a
card for a caller-owned executor. SignalWeave does not execute that SQL or
return the resulting table. A user therefore needs an existing SQL tool/MCP and
an agent capable of carrying query output back into a useful analysis. The
current code also has no visualization specification or chart-rendering
contract. These can remain caller/BI responsibilities, but the boundary and
handoff must be explicit and the example agent must actually demonstrate it.

### P1 — First-class connector onboarding is narrower than the adapter story

The local setup menu exposes Superset, hosted Preset, Trino, a reviewed MCP
manifest, or skip. Hex and Looker do not appear as native local wizard choices,
even though the repository contains connector implementations elsewhere. The
generic MCP route may bridge additional systems, but it is not the same as a
tested, human-friendly setup path. Document the supported local contract, then
test each advertised route from empty local state through an agent query.

### P1 — Scheduling and delivery are intentionally outside the binary

SignalWeave returns a decision/receipt; it does not wake up on a schedule or
send Slack/email messages. That can be a clean boundary, but it means
“alerting/reporting superpowers” require an agent or external scheduler/delivery
adapter. The starter workflow should show this end-to-end, including retries,
idempotency, quiet periods, a generated evidence bundle, and a human reply—without
implying SignalWeave itself sent or scheduled anything.

### P2 — Onboarding can still confuse “connected” with “usefully onboarded”

`signalweave setup` is a real guided CLI path, and `signalweave --help` plus
`signalweave health --live` work. A healthy connection proves catalog access,
not that a selected dashboard/chart has usable semantic fields, comparable
history, enough context for a user's goal, or a workflow that produced a useful
report. The next onboarding acceptance test should start with a clean local
home and end only when the user and agent have produced and reviewed a
source-backed result—not stop at “ready” or connector health.

The reported Helio setup snapshot makes this concrete: seven cards existed, all
were drafts, none were approved, there were zero metric-query cards, and most
cards had no delivery policy. Four cards were labeled ready for approval, one
needed human review, and the weighted-pipeline card was blocked for lack of an
approved anchor/candidate. That is not a successful business onboarding; it is
an incomplete draft backlog. The implementation explains how the misleading
“ready” label can happen: a missing delivery policy is recorded as a warning,
and warnings do not change `readiness_status`; `onboard_insight_card` then says
`simulate_then_approve`, but does not itself run the simulation. Readiness here
means “no blocking source-review condition,” not “this card produced a useful,
routable, human-accepted result.” The approval MCP tool also accepts no
workflow-acceptance report and returns `workflow_acceptance: unassessed`; the
enterprise-readiness summary flags that later, but approval itself does not
require the workflow to have passed.

### P2 — Trial cost and latency need end-to-end accounting

The Helio run recorded 30 Jev requests, 214,238 aggregate TypeSafe input tokens,
and 2,837 output tokens. Those are usage facts for that run, not a savings or
cost advantage. The treatment did not receive the frontier-computed analysis;
no current-price estimate or same-work paired cost model was reported. Future
trials should count agent tokens/calls, Jev tokens/calls, connector query time,
warehouse scan/cost, human review time, retries, and total wall clock per
completed task.

## Change made in this branch

Two implicit global rules were removed:

- Questions and `watch_for` entries are now advisory by default. A card author
  can mark an exact existing slot as required when its answer must exist before
  automatic notification/escalation.
- A current-only metric is no longer forced to `insufficient_data` solely
  because it lacks a baseline. If a card explicitly binds a comparison, or a
  numeric condition requires it, the comparison remains a hard requirement.

Required source failures, missing explicitly required comparisons, stale or
ambiguous required evidence, low-confidence actions, unverified context used
for automatic routing, incomplete explicitly required evidence, and
unconfigured delivery routes remain enforced. That is a narrower policy than
requiring every card to satisfy an implicit checklist; it does not claim that
governance alone makes the answer correct.

The policy version was incremented so previously generated certification
artifacts are not silently treated as current under the changed admission rules.
Current-only evidence statements were also corrected to show the available
value and state plainly that no comparable baseline exists, rather than
misreporting the value as absent or a zero movement.

## Recommended implementation order

1. Add the typed, source-bound agent-analysis handoff and let Jev judge only the
   bounded decision question the card defines. Preserve source authorization,
   unit/grain/window checks, provenance, contradictions, and unknowns.
2. Build a clean-home onboarding evaluation for Superset first: connect, select
   arbitrary charts, have the agent create a useful report, show supporting
   evidence and limitations, let a human correct the card, and rerun it. Add
   Trino and reviewed-MCP scenarios next; add Hex/Looker setup only when it is
   fully tested and supportable.
3. Add a small example agent that uses the installed SignalWeave MCP alongside
   the user's BI MCP/SQL tool, and demonstrates one-shot query/report plus a
   caller-owned recurring alert. Make the ownership boundary visible.
4. Rerun a blinded paired evaluation: same frontier model, same BI tools, same
   card/context and connector data; baseline is agent-only, treatment is
   agent-plus-SignalWeave/Jev. Hide class labels and expected outcomes from the
   model. Use multiple businesses and workflows, and report correctness,
   evidence/provenance quality, useful-vs-useless notifications, cost, latency,
   and human review effort. Separate independent cases from repeated mutations.
5. Treat visualization as a typed artifact handoff (or delegate rendering to
   the connected BI system); do not market charts as a SignalWeave feature until
   a supported output path exists and is tested.

## Evidence and limitations

The current code, tests, local CLI, Helio artifacts, and user-reported Helio
card-state summary were inspected for this review. This is a code/system review,
not an independent adversarial review panel, enterprise deployment certification,
or proof of analytical accuracy.
The simulated contract matrix verifies policy behavior across adapter labels;
it does not establish semantic quality from live Jev or an agent. No new paid
TypeSafe or OpenAI requests were made for this review.

Verification on this checkout: the full suite passed (**2,482 passed, 5
skipped**); changed-file Ruff checks and `git diff --check` passed. A fresh
macOS 15 ARM64 binary was built from this checkout, then passed the offline
private-setup/health/agent-config/MCP stdio smoke with 32 tools discovered. The
installer-mediated native-binary smoke also passed (**1 passed**), including
install to a temporary home and MCP initialization. These checks prove the
packaged current code starts and exposes its MCP surface; they do not call Jev,
connect to company BI, or prove analytical value.
