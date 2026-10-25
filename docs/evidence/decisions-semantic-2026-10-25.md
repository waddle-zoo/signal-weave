# Decisions and shared metric meaning: working investigation

This study is in progress. Its protocol is
[`decisions-semantic-journey-v1`](../../evaluations/protocols/decisions-semantic-2026-10-25.json).
It tests the existing card/context workflow, not a new semantic engine.

## What has actually run

The published Apple Silicon `v0.2.0rc5` binary passed an isolated live OpenAI
Decisions smoke check: private setup without Jev credentials, the normal
11-tool MCP profile, a synthetic typed `notify`, and receipt replay after a
process restart. This uses an OpenAI API key, not the user's Codex subscription.
Its source fingerprint is
`c2aa02884e1a79d41293b678b195e21fcbb71475dfc74f7d3be84f59fedc9f67`.
This check seeds a card; it does not prove fresh card onboarding.

The separate first semantic journey (`canary-v1`) did start from empty native
state. A live Luna Codex analyst discovered the synthetic retail semantic
exports, selected `retail.net_revenue` revision `r3`, saved a shared reviewed
definition and approved a source-bound historical comparison card. It took
200.69 seconds and 19 tool calls. Owner technical sign-off was explicitly
delegated by the fictional owner; this was not a human usability panel.

That journey **did not pass**. The engine's policy judgment was `notify`, but
the investigation report incorrectly demanded an analytical decomposition for
a valid scalar comparison contract. The ordinary-context reader inherited that
blocker from the shared handoff. It returned the independently verified amounts
correctly—USD 2,828.54 for September and USD 3,381.70 for August—but chose
`insufficient_data`. The run stopped after that first reader; there was no
treatment reader or completed paired comparison. This is not evidence that
either arm outperformed the other.

The candidate fix makes report coverage recognize a unique, authorized,
healthy scalar contract with complete comparable evidence for the selected
window. It does not invent a decomposition, weaken data-gap handling or create
numeric analysis claims. Regression tests include invalid/duplicate contracts,
identity and access failures, partial coverage, window mismatch, missing
measurements, decomposition substitution and normal compact/full MCP responses.
A fresh fingerprint-matching candidate binary and a new live journey are still
required; the published `rc5` download does not contain this fix.

## Scope and reproduction

The companies are test-owned SQLite semantic exports for retail, subscription
software and a marketplace, with gross/net/GMV/run-rate/draft/retired name
collisions. Independent Decimal calculations check SQL output; expected labels
are not supplied to agents. They are not live dbt, Cube or LookML integrations.

Both arms retain company source tools and the same reviewed business brief.
Treatment adds the actual native MCP and its workflow skill. Ten equivalent
prompts test fresh-agent consistency; separate explicit-gross and conflicting-
definition cases test that reuse does not force the wrong meaning.

After building the candidate, start with a new small canary directory:

```sh
uv run python -m evaluations.decisions_semantic_trial \
  --binary dist/signalweave/signalweave \
  --key-file /private/path/openai.key --codex /absolute/path/to/codex \
  --output artifacts/semantic-canary-unique --readers 2 --companies retail --live
```

This incurs provider usage. Do not run the larger `--readers 10 --companies
retail saas marketplace --sensitivity` cohort before reviewing the canary's
actual messages, onboarding and failures. Original attempts stay in their
exclusive ignored directories. A repaired attempt is not silently substituted
for a failed one. Human usefulness, semantic-vendor compatibility, authenticated
employee access and cost/speed superiority remain separate claims to prove.
