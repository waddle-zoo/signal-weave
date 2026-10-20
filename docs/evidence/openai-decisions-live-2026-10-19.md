# OpenAI Decisions: live integration and Northstar policy replay

OpenAI Decisions now exercises the same saved-card workflow without a Jev key.
A fresh local native candidate completed setup, offline health, normal-profile
MCP startup, a live typed `notify` judgment and receipt replay across process
restart. This is integration proof, not an enterprise-readiness certification.

The frozen local `rc4` candidate was built from `b155de0`, production-source
fingerprint `054ef3d6fb9a544a4e4154fcce6734407c6061622e5646b1ac1e1fa23e5f9a57`
and executable SHA-256 `8b691244a81270b7f6dc5f0a70d98f63cc5e9768c7f9ddcd5acfd7b8dafa5513`.
Its isolated installer/reinstall/uninstall check passed, as did 5,162 offline
tests (13 skipped). These are local-candidate checks, not a public-download claim.

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
