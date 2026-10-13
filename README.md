<p align="center">
  <img src="assets/signalweave-logo.svg" alt="SignalWeave" width="430">
</p>

<p align="center"><strong>Give your agent repeatable BI investigations—with evidence.</strong></p>

Stop checking the same dashboards by hand. SignalWeave helps Codex and Claude
turn your business questions into reusable **cards**: what matters, where to
look, and when someone should hear about it. On later runs, your agent gets fresh
evidence and a typed policy decision—not another blank-page investigation.

Keep your BI stack and your agent. SignalWeave runs locally as an MCP server;
the agent still owns discovery, analysis, charts, and the explanation you read.

## Get started

For the currently downloadable preview on macOS or Linux, install and start
setup in one terminal line:

```sh
set -o pipefail; curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' https://github.com/waddle-zoo/signal-weave/releases/download/v0.2.0rc1/install.sh | sh -s -- --version v0.2.0rc1 && export PATH="$HOME/.local/bin:$PATH" && "$HOME/.local/bin/signalweave" setup
```

Supports macOS 15+ (Apple Silicon/Intel) and Linux x64 with glibc 2.35+.
The macOS preview is not notarized; managed devices may require an approved
install method.

The wizard asks for your Jev key, BI connection, and whether to connect Codex
or Claude. It stores credentials in your private `~/.signalweave` directory.
After setup, ask your agent: **“Use SignalWeave to help me understand what
changed in online sales. Show me the evidence and ask for missing context.”**

> **Preview limitation:** the published `v0.2.0rc1` is Jev-only. OpenAI Decisions,
> ChatGPT-plan sign-in, and the installer's single `--setup` option are in this
> `v0.2.0rc2` source candidate but not in a downloadable release yet. The next native
> release will have a one-command install that opens the expanded wizard.

## Describe the investigation once

A card is a reusable business brief, not a rigid list of metric thresholds.
For example:

> **Watch:** online sales and their contribution to net sales.
>
> **Why:** catch unexpected revenue losses before the weekly review.
>
> **Look for:** a meaningful drop, excluding planned promotions and reporting gaps.
>
> **Investigate:** which channels, products, or funnel stages explain the change?
>
> **Delivery:** involve Analytics and Data Trust first; send Leadership the
> findings once the investigation supports them.

Your agent finds the relevant dashboards and charts, checks their definitions,
and helps turn that brief into a card with explicit sources and decision guidance.
You resolve business ambiguity and approve what should repeat. Cards can span
multiple sources; they do not require every team to monitor the same metrics or
use the same notification rules.

## Evidence, decisions, then explanation

```text
Your brief → reviewed card → fresh evidence → typed decision → agent investigation/report
```

SignalWeave keeps the card, retrieves its approved sources, and returns the
evidence, source references, decision probabilities, and a saved receipt.
Your agent uses that bundle to investigate likely drivers, prepare a concise
report, and decide what further source work is needed. Evidence is inspectable;
large bundles can be read in pages rather than dumped into the agent's context.

The decision layer answers a narrower question: **given this evidence and our
policy, should we ignore, investigate, notify, or report missing information?**
[TypeSafe's Jev](https://docs.typesafe.ai/introduction/coding-agents) applies
plain-English criteria through typed questions and probability distributions.
The source candidate also supports the
[OpenAI Decisions API](https://developers.openai.com/api/docs/guides/decisions).
This makes decisions usable in workflows without parsing a generated essay.
It does not make a probability proof, establish causality, or replace the
frontier agent's reasoning. ChatGPT-plan Responses is another candidate backend;
its probabilities are model estimates, not native Decisions distributions.

Use cards for a daily sales check, a customer-health digest, or a recurring
operational investigation. The benefit to aim for is fewer repeated instructions,
consistent business context, and useful evidence-backed messages—not more alerts.
Scheduling and actual delivery stay with your agent or workflow runner;
evaluating a card does not itself send a message.

SignalWeave supports Superset, Preset, Trino, and reviewed read-only MCP source
manifests. An MCP connection does not make an unsupported source automatically
understandable; see the [source adapter contract](docs/source-adapters.md).

This is a preview. See [evaluations and evidence](docs/enterprise-onboarding-journeys-2026-10-02.md)
and [current limits](docs/local-investigations.md) before relying on unattended
workflows. Synthetic trials are not proof of success in your company.

## Develop

```sh
git clone https://github.com/waddle-zoo/signal-weave.git
cd signal-weave
uv sync --extra dev
make verify
```

See the [full setup guide](docs/local-install.md), [contributing](CONTRIBUTING.md),
[agent instructions](AGENTS.md), and [roadmap](ROADMAP.md). Licensed under
[Apache 2.0](LICENSE).
