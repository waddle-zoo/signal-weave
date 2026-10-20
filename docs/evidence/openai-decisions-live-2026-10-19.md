# OpenAI Decisions: live integration and Northstar policy replay

OpenAI Decisions exercises the same saved-card workflow without a Jev key.
The **published `v0.2.0rc4` download** completed guided setup, source health,
normal-profile MCP startup, a live typed `notify` judgment and receipt replay
across process restart. This is integration proof, not an enterprise-readiness
certification.

## Published install: the actual user path

The release was built from merged `main` commit
`de7d769df162e4e8d0936f510a833dc1e8ceb922`. macOS ARM64/x64 and Linux x64
native release jobs passed. The actual GitHub installer and Apple Silicon
archive were downloaded over HTTPS and their checksums verified. The published
executable SHA-256 is
`e5fa49cefff9d22c2979cb8e238fbd9dac4fd7cf989c8da1ca5a263ec621d3e2`.

An isolated fake-person home then exercised:

- One piped installer command with `--setup`, the hidden OpenAI-key prompt,
  a reviewed company-MCP manifest and confirmed Codex registration.
- The actual Codex CLI registration and bundled skill, `signalweave --help`
  through PATH, and a live read-only source-health probe.
- The installed executable's default 11-tool profile, one seeded approved-card
  live OpenAI `notify` evaluation, and replay after process restart.
- Native uninstall with local configuration retained, followed by reinstallation
  and a healthy existing configuration.

No Jev credential or user-global agent configuration was used or changed.
Terminal inputs were scripted; this was not a novice-human usability panel.
The seeded card proves the provider path, not fresh business card authoring.
OpenAI API usage is separate from a Codex subscription. Install or switch
providers using the [local walkthrough](../local-install.md#choose-a-decision-provider).

## Source-candidate checks

The frozen local `rc4` candidate was built from `b155de0`, production-source
fingerprint `054ef3d6fb9a544a4e4154fcce6734407c6061622e5646b1ac1e1fa23e5f9a57`
and executable SHA-256 `8b691244a81270b7f6dc5f0a70d98f63cc5e9768c7f9ddcd5acfd7b8dafa5513`.
Its isolated installer/reinstall/uninstall check passed, as did 5,162 offline
tests (13 skipped). The published-download check above is separate from these
local-candidate checks; both have the same production-source fingerprint.

## Codex using the published binary on company cards

One actual Luna Codex invocation used the published executable to find and
evaluate two existing, analyst-authored Meridian **historical** cash and renewal
cards in native approved status, not researcher-supplied gold cards or newly
completed onboarding. That status did not resolve the original journey's
consent contradiction, described in the
[Meridian review](meridian-onboarding-diagnostics-2026-10-19.md#retained-budget-continuation-useful-files-incomplete-human-workflow).
This check establishes technical reuse, not valid human authorization.
Their SQL, business guidance and
July 6 source snapshot stayed unchanged. New run keys ensured live OpenAI
judgments rather than replay of the earlier Jev receipts.

The first attempt stopped before inference because unattended Codex denied
MCP tool approvals. It is retained. A separately recorded attempt explicitly
permitted only its two configured test servers and completed in 113.44 seconds:
seven MCP calls, two new OpenAI receipts and a 214-word business brief. No shell,
web, card edits, external messages or full renewal-worklist delivery occurred.

The brief reported historical net settled cash separately in EUR, SGD and USD;
it did **not** call the empty prior ledger window a confirmed cash increase.
It also reported 1,668 scheduled renewals, retaining currency splits and the
July 6–August 4 population. OpenAI routed cash to `insufficient_data` and renewals
to `investigate`; those labels were not treated as reasons to withhold supported
findings or as proof of customer harm. The prior Jev choices differed, so this
does not demonstrate provider decision agreement.

Independent internal review passed the scoped integration and verified the
brief's reported figures, but **did not pass the first brief's completeness**:
it omitted settled-event and pending counts requested by the cash card. The
review also requested an explicit visible-at-cutoff qualification for renewals.
The original brief and failure are retained; correct inference and figures do
not by themselves establish a complete human report.

A separate saved-receipt feedback attempt hit its artificial four-call test
cap before a final revision; it created no new decisions and its frontier usage
is unknown after interruption. That is an incomplete test, not proof that
feedback works or a product-level four-call limit. It is not counted as a
successful report or retried into one.

The same installed binary subsequently served authenticated Streamable HTTP,
replayed both OpenAI receipts and rejected an unauthenticated request. This
checks transport and receipt portability, not new live inference over HTTP or
a managed-cloud deployment.

The completed agent invocation used 45,257 uncached input and 13,210 output
tokens; provider token usage was not instrumented. There is no matched baseline,
speed advantage, cost advantage or enterprise accuracy claim. The company
fixture and raw traces are retained locally, not published as a reproducible
public benchmark. This scoped reuse check does not replace the larger
[mixed Meridian journey](meridian-onboarding-diagnostics-2026-10-19.md).

## What the live testing caught

- The adapter reused an experimental sampled synthesis. SQL-only evidence could
  disappear, and unrequested role classifications appeared as unresolved facts.
  It now uses the ordinary Jev path's fact-preserving projection.
- Input estimation counted JSON string escaping twice. It now estimates the
  decoded evidence and questions, without raising the 12,000-token default.
- Oversized judgments now retain evidence in a deferred, pageable receipt for
  the frontier agent instead of inventing a result or dropping facts.
- Setup wrote a newline-terminated OpenAI credential file that offline health
  then rejected. Setup, rotation and validation now agree on the file format.

No owner thresholds, confidence floors, source permissions or expected outcomes
were relaxed. Discovery, SQL, investigation and the human report remain the
frontier agent's job.

## Northstar: the existing 48-case policy register

One fixed, expert-authored card was evaluated over eight synthetic periods and
six decision situations: quiet, modest movement, an isolated channel decline,
a corroborated decline, conflicting sources and unavailable data. Each case
contains nine observations from four supplied sources. This is a known,
small-fixture development replay—not 48 independent enterprises, fresh human
onboarding, live Superset queries, or a comparison against a Luna agent.

| Attempt, retained separately | Exact policy outcome | Qualifying notifications | Errors or local blocks |
| --- | ---: | ---: | ---: |
| Original sampled adapter | 30/48 | 0/8 | 8 input-budget blocks |
| Fact-preserving packet, old escaping estimator | 8/48 | 0/8 | 48 local blocks; zero provider calls |
| Corrected packet and estimator | 46/48 | 8/8 | 1 TLS transport failure |

The corrected run made 48 provider attempts, produced no spurious `notify`,
and matched the configured route in 46 cases. One quiet case selected `ignore`
with 0.57 support and was routed to `investigate` by the unchanged confidence
floor. The other mismatch was a TLS `bad record mac` failure; it was not retried
or removed from the denominator. Missing-source outcomes are also subject to
code-owned checks, so this is not pure model accuracy.

Median completed evaluation latency was 326 ms, excluding source-query latency,
installation, agent analysis and delivery. Provider token usage was not captured;
legacy zero `jev_metrics` are not zero OpenAI cost. Modeled minutes in the old
harness are not measured savings. No agent or recipient acted in this replay.
The first two failed attempts remain intact; this is not a clean holdout study.

## Reproduce

These commands are opt-in live checks and incur provider usage. Use a private
file containing an OpenAI API key; do not put a key in shell arguments.

```sh
uv run python scripts/check_binary.py --binary dist/signalweave \
  --live --decision-provider openai-decisions --key-file /private/path/openai.key

uv run python -m evaluations.northstar_growth_history_trial \
  --decision-provider openai-decisions --openai-key-file /private/path/openai.key \
  --seed-dir evaluations/data/northstar-multistep-seed \
  --output artifacts/northstar-openai-replay.json
```

The binary checker requires a freshly built, fingerprint-matching executable.
It seeds a synthetic approved card: it does **not** test expert card authoring.
The policy replay writes local details; do not confuse its typed route/bundle
checks with actual report delivery or a whole-agent benchmark.

OpenAI's [Decisions guide](https://developers.openai.com/api/docs/guides/decisions)
documents the dedicated endpoint and `gpt-6-luna` typed question contract. This
is distinct from ChatGPT-plan Responses; Codex sign-in is not reused as an API key.
