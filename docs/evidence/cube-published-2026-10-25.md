# Published binary with a real semantic query engine

October 25, 2026. [Preregistered protocol](../../evaluations/protocols/cube-native-2026-10-25.json).
This extends the [earlier semantic-export study](decisions-semantic-2026-10-25.md)
with actual Cube Core and Postgres. It does not add a production Cube adapter or
replace the existing metric engine.

## What actually ran

The public **v0.2.1 Apple Silicon release** was installed through the published
HTTPS installer into an empty private home. Terminal setup entered a hidden
OpenAI key, connected a reviewed company-MCP manifest, registered Codex, and
installed its bundled skill. Enabling shared context was a separate documented
operator command. A Luna agent then inspected sources and authored, reviewed and
approved the card and shared definition through the normal MCP profile.

The source is a synthetic retailer with 96 ledger records and six measures all
titled “Revenue,” including gross, net, GMV, ARR, a draft and a retired meaning.
**Cube 1.8.13 executes the measures against Postgres**: the gateway uses actual
`/meta`, `/sql` and `/load`, not Python/SQLite aggregate substitution. A separate
Decimal calculation from captured source records checks correctness. Cube and
Postgres images are digest-pinned; the database reader is read-only.

The frontier agent discovers meaning and explains evidence. OpenAI Decisions
applies only the saved Finance significance policy. Nothing is sent or scheduled.

## Closed checks

| Check | Observed result |
| --- | --- |
| Source controls | All six Cube measures matched independent ledger calculations. A hand control added exactly $0.82 to the actual aggregate, then restored the exact original records. Reader writes were rejected. |
| Continuous onboarding pilot | Public install → actual registration → agent-authored shared definition/card → four fresh reader reports passed. Both arms correctly answered the net and explicitly different gross questions. The applicable treatment run produced a fresh native Decisions receipt. |
| Actual definition change | With unchanged raw records, Cube's net formula changed from r3 to r4 to subtract credits. After the documented operator manifest-lineage update and reconnect, the required context became `source_changed`. The native result deferred without an outcome, route or provider attempt. This is declared-lineage checking, not automatic upstream discovery. |
| Actual Codex registry discovery | After the user completed normal browser sign-in in the disposable profile, Codex loaded the installer-registered stdio entry and made exactly one evaluation call. Its stored receipt and supported review brief matched. No proxy or transport override; one invocation-only tool-approval override was disclosed. |
| Meaning-change handoff | Both fresh readers reported attributed r4 figures and requested definition review rather than reusing r3 approval for a business conclusion. The treatment's actual native receipt was outcome-free and provider-free. |
| Expert maintenance | The agent edited/reviewed the same shared definition to revision 4 and revised/reapproved the same card at version 4. Independent review confirmed the credits deduction, unchanged strict decline threshold, archival scope and Finance routes. A fresh native Decisions evaluation returned the supported `notify` before the data correction; delivery remained disabled. |
| Data correction | Exactly 48 September activity factors changed in actual Postgres. The r4 model, view and query stayed fixed. Independent recomputation and Cube agreed on $3,368.94 versus $3,302.66, up 2.01%, with a new result identity. Both arms and the policy evidence received the same explicitly fictional owner correction record. |

The source-change figures are **$2,762.53 versus $3,302.66** under r4, compared
with **$2,828.54 versus $3,381.70** under r3. A definition revision is not a data
revision. Both the source results and their distinct identities were retained.
Independent review cleared these bounded pilot, source-control, maintenance and discovery
checks. It does not certify the entire study or enterprise adoption.

## Continuation in progress

Following those closed phases, ten fresh paired readers run,
five baseline-first and five treatment-first. Every treatment judgment must
match the actual card/version, current context, corrected source snapshot,
independent amounts, outcome and routes—not merely a plausible final brief.
Every human brief and the maintenance semantics require independent review.
The final evaluation-code revision passed `make verify`: **5,397 passed,
13 skipped**. Tests are regression evidence, not substitutes for the live cohort.

Both arms retain the same company tools and reviewed card/context notes.
Treatment adds the public native MCP and bundled skill. Comparative episodes
use a research MCP proxy forwarding to that actual binary; the separate
registry-discovery check above does not retroactively change their transport.

## Stops and claim limits

- The first reconciliation attempt stopped on a missing test-driver source label.
- The first revision probe changed the literal MCP endpoint and stopped before
  editing the formula. The separate corrected probe preserved that endpoint;
  no production identity gate was weakened.
- The first direct-discovery attempt found the installed tool but the harness's
  `approval_policy=never` rejected it. No evaluation occurred. The later attempt
  explicitly preapproved that tool for the invocation, leaving its registered
  command, arguments and on-disk registry unchanged.

Stopped attempts remain separate, not rescored as successes. One vendor, one
synthetic company and clustered reader prompts are not independent enterprise
replications or a novice-human usability panel. These checks do not establish
speed/cost superiority, calibrated probabilities, identical prose, real human
acknowledgement or external delivery.

## Reproduction and retained evidence

Use a disposable project and new exclusive output directories. These stages
mutate only their synthetic source and private installed state; never point the
mutation scripts at a real company. They require Docker, a normally logged-in
Codex CLI, and separately authorized paid OpenAI calls where `--live` is required.

1. Generate with [`cube_fixture`](../../evaluations/cube_fixture.py), start its
   pinned [Compose services](../../evaluations/cube/compose.yml), and run
   [`cube_reconcile`](../../evaluations/cube_reconcile.py) followed by
   [`cube_fixture_control`](../../evaluations/cube_fixture_control.py).
2. Run [`cube_native_trial`](../../evaluations/cube_native_trial.py) against the
   restored source and completed control report. It performs the public install
   and agent-authored onboarding; it does not mark the larger study complete.
3. Run [`cube_revision_probe`](../../evaluations/cube_revision_probe.py) once
   against that pilot's original r3 phase. It leaves the recorded r4 phase active.
4. After normal sign-in to the pilot's disposable Codex profile, run
   [`cube_registered_discovery`](../../evaluations/cube_registered_discovery.py).
5. Run [`cube_native_continuation`](../../evaluations/cube_native_continuation.py)
   against the closed pilot/probe. Audit its retained source captures, tool
   traces, receipts, briefs and independent review—not only `structured_complete`.

Each module documents its arguments through `--help`. Credentials remain local;
raw traces, state backups and source captures stay in ignored
`artifacts/cube-native-2026-10-25/`. Closed attempts include
`retail-reconcile-v2/v3`, `retail-hand-control-v1`, `published-pilot-v1`,
`actual-revision-probe-v2` and `registered-discovery-v2`. The continuation retains
helper/protocol hashes before paid calls. No production dependency, `src/` behavior
or release binary changed for this study.
