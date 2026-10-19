# Pine Courier first readout and recurring setup

Both agents gave Dispatch a supported answer: delivery attainment was **89.47%
in both completed weeks**, so the five-percentage-point decline rule did not
call for an exception notice. SignalWeave preserved a real draft card and a
verified query, but **did not complete the connection between them**. This is
useful first-readout evidence, not completed onboarding or an overall advantage.

The [compact record](../../evaluations/data/pine-first-readout-2026-10-18-summary.json)
preserves both exact briefs, usage and artifact hashes. Raw conversations stay
outside tracked documentation.

## What the person received

The Dispatch lead asked what changed, whether to act, and how to reuse the
weekly review. Both briefs correctly distinguish flat performance from a 25%
volume increase. Both reject a completed-only calculation that appears to
improve by 1.96 points because it excludes undelivered parcels.

Each agent saved its SQL, evidence and reusable notes. SignalWeave additionally
saved a draft with the intended comparison, five-point rule and team routes.
Its final message correctly explains that the derived query ran only as a
one-off export: the card still reads raw cached counts. Operator connection,
a card update, fresh review and owner confirmation remain necessary.

Independent internal data review recomputed the counts from the read-only
source, replayed saved queries and checked supporting links and capture hashes.
Internal product review found useful first answers, not a ready recurring
workflow. Both briefs include technical setup details that belong in onboarding,
not an everyday Dispatch alert.

## Effort observed

| First readout and retained work | Company tools and Luna | Plus SignalWeave |
| --- | ---: | ---: |
| Actor-stage seconds | 370.10 | 467.69 |
| MCP calls | 33 | 27 |
| Workspace operations | 14 | 25 |
| Input tokens including cache | 1,503,940 | 2,535,050 |
| Uncached input tokens | 147,652 | 142,474 |
| Output tokens | 45,102 | 61,496 |

SignalWeave used fewer MCP calls and slightly fewer uncached input tokens, but
more time, workspace operations, total input and output. Its extra draft/source
preparation is part of that work. These are different preparation artifacts in
one fixed-order pair, not equal-work savings or a causal performance estimate.
Actor timing excludes startup and cleanup. Scripted native setup took 14.89s;
human setup time, billing and reviewer costs were not measured or amortized.

## What needs to work next

The agent verified its proposed aggregation against source records and retained
the exact SQL and fixed MCP arguments. Connecting a reviewed query should
not require a custom Python reader or a duplicate card. The native revision
surface rejected the agent's attempt to remove a 24-hour age default that was
not appropriate to its historical review; source replacement was also outside
that surface. A separate revision repair addresses this handoff. It does not
change the original artifacts or upgrade this pair's result.

## When the source changes

A separate read-only qualification replayed the **unchanged saved SQL** across
the three archived cutoffs. At September 28 it returns `comparison_valid=0`
because the cached overall denominator is missing. Yet complete raw records,
matching tier counts and population manifests support **2,772/3,420 = 81.05%**
versus **2,550/2,850 = 89.47%**, an **8.42-point decline**. The baseline's own
retained rule query also finds that decline. The treatment procedure would
withhold the business decision if followed unchanged, despite recoverable
evidence; a broken cached total is not the same as an unknowable comparison.

This was checked independently and through the repository-venv MCP stdio
helper with exact saved arguments, three rows per export and no truncation.
It is source/procedure qualification, not a new agent or Jev outcome. At October
5 the later archived cache revision reconciles again; that is not proof a
person repaired it. SQL SHA-256 is
`bdfa4430e4f8b514e99e8ec45419284213e5b6fcd8bff38290719ce5314d57a0`.

The useful next step is to have the caller/data expert qualify the retained
analysis, keeping business-comparison support separate from cache health,
then connect and review the same card. Shadow checks with live Jev must examine
the actual Dispatch update and distinct Data Operations repair request, not
only the outcome label. This path is not yet established by this study.

Operator registration also exposed an invalid generated descriptor: English
definition text had been placed in the structured warehouse metric-definition
field. Moving that text into the descriptor description is counted expert
assistance, not successful unassisted onboarding. The CLI then rejected an
explicit replacement manifest even through `connections update`; a separate
repair makes that command honor its existing update option. Neither correction
changes the original pair or validates the analysis for later weeks.

## Forward native handoff check

A rebuilt native executable from `c521642` completed the connection update,
inspected the unchanged saved SQL through the real source, and revised a copy
of the original card from version 1 to 2. Its identity, business intent and
policy survived; it stayed draft, and evaluation without approval was rejected.
The original store and source were unchanged. This used the recorded operator
schema correction above and **zero provider calls**: it verifies the repaired
handoff, not clean self-onboarding or a successful recurring analysis.

The executable SHA-256 is
`283479ae083c734c877e1a4629dbfcb37b311123c3242e952365f01fe435f258`,
production fingerprint
`99cec53e50c8fbb297037fbb5b6fb6218a5c867a77e70a4b5b0182799d69e8dc`.
Its script, calls and result remain in ignored
`artifacts/pine-native-source-handoff-v5`. Earlier semaphore/closed-SQLite
preparation failures and schema/CLI failures are retained; none are extra
business samples or retroactively passing onboarding attempts.

## Method and reproduction

Two Luna 6 xhigh Codex sessions, baseline first, one attempt each. Both kept the
same company MCP, raw SQL, source-owned exports and prospective fictional owner
statements. Treatment added the normal native agent profile, optional context
tools and canonical skill. Neither approved a card or called Jev; this is not a
decision-provider comparison. No message, assignment or schedule was created.

The [source contract](../../evaluations/data/pine-courier-history-contract.md),
[prospective workflow protocol](../../evaluations/protocols/pine-courier-workflow.json)
and [runner](../../evaluations/pine_courier_onboarding.py) are public. The source
exposes only records known at September 21, 2026, 06:00 UTC; manifests reconcile
the two closed cohorts' 5,400 registrations. It is a synthetic historical source,
not a current production feed. Source setup and consent were not human trials.

The actual downloaded native build embeds `f8b5764`, executable SHA-256
`12a6ebee16b0c1a5f78d721ca67e9a8fe4b988fbeaeb301a4fbfab1d658d57e4`.
Codex was `0.162.0-alpha.17.2`; identities are in the compact record. Final
pre-execution software verification passed **4,956 tests / 13 opt-in skips**
plus Ruff. Those checks do not count as business observations.

Limits were 480 seconds, 48 MCP calls and 50 workspace operations per actor.
The 3M-input and 250k-uncached stops applied between actors, not in flight.
Both completed; combined usage was 4,038,990 input, 290,126 uncached input and
106,598 output tokens. No retry or further actor is admitted by this study.
Earlier zero-inference preparations and the CLI-update rejection remain in
ignored `artifacts/pine-first-readout-preparation-ledger.json`; they are not
extra business samples. Exact conversation replay requires the retained
`artifacts/pine-first-readout-v4` inputs and authorized Codex access.
