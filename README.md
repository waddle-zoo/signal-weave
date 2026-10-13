<p align="center">
  <img src="assets/signalweave-logo.svg" alt="SignalWeave" width="430">
</p>

<p align="center"><strong>Give your agent repeatable BI investigations—with evidence.</strong></p>

SignalWeave is a local MCP for Codex and Claude. Save a human-reviewed brief
once; your agent can revisit its approved BI sources, analyze fresh evidence,
and explain what changed. Your agent does the discovery and reasoning. SignalWeave
keeps the source scope and decision policy reusable.

## Get started

For the currently downloadable preview on macOS or Linux, install and start
setup in one terminal line:

```sh
set -o pipefail; curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' https://github.com/waddle-zoo/signal-weave/releases/download/v0.2.0rc1/install.sh | sh -s -- --version v0.2.0rc1 && "$HOME/.local/bin/signalweave" setup
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

## How it works

```text
Human intent → reviewed card → fresh BI evidence → agent analysis and report
```

A card records what to watch, why it matters, questions to investigate, and the
approved source references. On a later run, SignalWeave retrieves those sources
and returns evidence plus the selected decision provider's judgment. Your agent
can investigate beyond the card, explain likely drivers, and prepare a report.
Scheduling and delivery stay with your agent or workflow runner.

SignalWeave supports Superset, Preset, Trino, and reviewed read-only MCP source
manifests. An MCP connection does not make an unsupported source automatically
understandable; see the [source adapter contract](docs/source-adapters.md).

## Honest status

This is a local preview, not a customer-proven enterprise product. In one
synthetic six-company onboarding trial, the guided SignalWeave path did not
pass; direct use of company tools by the same agent performed better. See the
[trial and evidence](docs/enterprise-onboarding-journeys-2026-10-02.md) and
[known limits](docs/local-investigations.md).

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
