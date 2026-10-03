# SignalWeave on your laptop

Connect SignalWeave to your agent, describe an investigation, review the proposed
card, and rerun it against fresh evidence. You need a **TypeSafe Jev API key**
and access to your company's data sources. No Python or Docker required for the
native executable; an external company MCP may have its own requirements.
Your existing agent supplies its own model access. SignalWeave does not require
a separate OpenAI key for this local MCP workflow.

Supported builds: macOS Apple Silicon/Intel (macOS 15+; tested on 15), and Linux
x64 with glibc 2.35+ (not Alpine/musl). macOS builds are not Developer-ID signed
or notarized; company device-management policies may block them. Do not disable
those controls—use an administrator-approved installation path instead.

> **Local preview:** `v0.2.0rc1` is a prerelease for trying the local runtime.
> Installation and bounded live-Jev execution have been tested. The paired
> [Codex/Jev trial](codex-bootstrap-trial-2026-10-01.md) exposed unresolved
> card-approval gaps; easy onboarding and comparative benefit are not proven.
> The stable v0.1.0 release has no native assets.

## 1. Install and set up

```sh
installer="$(mktemp)"
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
  https://github.com/waddle-zoo/signal-weave/releases/download/v0.2.0rc1/install.sh -o "$installer" &&
  sh "$installer" --version v0.2.0rc1
```

```sh
"$HOME/.local/bin/signalweave" setup
```

The installer selects macOS Apple Silicon/Intel or Linux x64, verifies the
archive's SHA-256 checksum, and installs without `sudo`. Setup keeps your key
and state private under `~/.signalweave`. Your Jev key is not your BI credential:
source access must be configured too. Jev evaluations send configured evidence
to TypeSafe; this is local storage, not offline inference.
The pinned version explicitly opts into this preview; previews are never selected
by the installer's default `latest` lookup.

## 2. Connect your agent

The **unpublished rc2 development binary** can register with Codex during setup:

```sh
signalweave setup --agent codex --register-agent
```

For an already configured local home, use `signalweave connect --agent codex`.
Registration is opt-in and uses the installed Codex CLI. A conflicting existing
entry is left untouched; registration errors preserve your local setup. Close
concurrent agent-configuration edits while connecting. Registration is not a
live source test. Claude Code currently receives a manual registration command,
not an automatic configuration edit. The published rc1 still uses the commands
below; do not pass rc2-only flags to rc1.

Run **one** command for the agent you use:

```sh
codex mcp add signalweave -- "$HOME/.local/bin/signalweave" serve --home "$HOME/.signalweave"
```

```sh
claude mcp add --transport stdio --scope user signalweave -- "$HOME/.local/bin/signalweave" serve --home "$HOME/.signalweave"
```

Restart or reconnect the agent. In rc2, ask:

> Use SignalWeave's getting-started guide. Help me understand what changed in
> my business using the BI sources I already have. Start with one useful report,
> show your evidence, and ask me only for context you cannot find.

The `get_signalweave_guide` MCP tool is bundled in the binary. It explains three
paths to the agent without making source or model requests:

| What you want | What your agent does with SignalWeave |
| --- | --- |
| Query a metric | Finds reviewed metric definitions, proposes a plan, and previews time-bounded SQL for your authorized executor. |
| Explain a change | Inspects evidence, drafts the investigation, and previews checked measurements, contributions and gaps. |
| Keep watching | Tests your intended outcomes, asks for approval, and reuses the investigation with fresh evidence and saved receipts. |

You explain the business intent; the agent writes the card. Existing sources
must supply the definitions and measurement contracts. It should not ask you to
fill in a large JSON form or invent a definition that your BI stack cannot support.
For rc1, describe the same investigation directly; its MCP does not contain the
new getting-started tool.

The agent helps author the card; you approve its meaning and evidence. Connecting
an arbitrary MCP is not automatic normalization of its responses. Scheduling and
delivery stay with your agent or existing scheduler.

Before a recurring workflow is considered active, agree on **what matters, who
receives which outcome, what silence means, and who runs the schedule**. Test a
meaningful change, a quiet period and missing evidence. An approved card alone
does not schedule work or send an alert. Query compilation alone does not execute
a warehouse query, and descriptive contributions are not proof of cause.

**Trouble?** Run `"$HOME/.local/bin/signalweave" doctor` for an offline config
check. See the [reference](local-install-reference.md) for supported source
connections, private paths, explicit versions/upgrades, release verification,
and source builds. There is no automatic updater.
