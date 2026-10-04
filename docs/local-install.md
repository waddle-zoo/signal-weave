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

> **Local preview:** `v0.2.0rc2` is a prerelease for trying the local runtime.
> Installation, guided setup, local agent handoff, and bounded live-Jev execution
> have been tested. This preview is not a claim of enterprise analytical quality.

## 1. Install once, then use the guided setup

```sh
installer="$(mktemp)"
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
  https://github.com/waddle-zoo/signal-weave/releases/download/v0.2.0rc2/install.sh -o "$installer" &&
  sh "$installer" --version v0.2.0rc2
```

```sh
"$HOME/.local/bin/signalweave" setup
```

That one guided command walks through the setup in this order:

1. TypeSafe Jev key (hidden input)
2. Local tenant and principal identity (safe defaults are `local`)
3. One or more source connectors and their credentials
4. Codex or Claude Code handoff (with an explicit confirmation before changing agent config)

It writes a private local home at `~/.signalweave`; it does not require TOML
editing or an OpenAI key. After each connector, the wizard asks whether to add
another one, so a team can connect Superset plus Trino or a reviewed company MCP
manifest in one pass. Jev is the SignalWeave decision runtime, while your agent
supplies frontier-model reasoning when a workflow needs investigation or
narrative analysis.

The installer selects macOS Apple Silicon/Intel or Linux x64, verifies the
archive's SHA-256 checksum, and installs without `sudo`. Your Jev key is not a
BI credential: the setup wizard separately configures source access. Jev
evaluations send configured evidence to TypeSafe; this is local storage, not
offline inference. The pinned version explicitly opts into this preview;
previews are never selected by the installer's default `latest` lookup.

For an interactive setup, SignalWeave offers to connect the selected agent at the
end. Press Enter to accept. If the agent CLI is not installed, or if you choose
Claude Code, it prints the exact command to review and run. To make the choice
explicit in scripts, use `--register-agent` or `--no-register-agent`.

After setup, the normal human path is:

```sh
signalweave status
signalweave connections add       # add another source without editing TOML
signalweave connections update    # change a source endpoint or credential mode
signalweave credentials set NAME  # rotate one secret without editing config
signalweave health --live         # test catalog access; does not spend a Jev judgment
signalweave connect codex          # or: signalweave connect claude, if skipped during setup
signalweave ui                     # optional local health page at 127.0.0.1:8765
```

If you want to change one secret later, use a hidden prompt or a private file:

```sh
signalweave credentials list
signalweave credentials set typesafe
signalweave credentials set superset-password --file /private/path/password
```

`signalweave status` and the local UI never print credential values. `health`
without `--live` is an offline configuration check; `doctor` remains an alias.
`health --live` performs a bounded catalog probe for each configured source and
explicitly does not call Jev. The local UI's **Check sources** button runs the
same probe and renders only secret-free results. Run an approved card or the
agent's workflow when you want to test the provider judgment path.

The local wizard supports Superset, hosted Preset, Trino with a normalized
catalog JSON file, and reviewed read-only MCP source manifests. For Preset,
the wizard supports either an API-token name/secret pair or a bearer access
token. For example:

```sh
signalweave setup --source preset --url https://workspace.app.preset.io \
  --preset-auth bearer --access-token-file /private/path/preset-access-token \
  --agent codex --register-agent
```

Other company systems can be brought in through the reviewed MCP bridge without
teaching the local CLI to store arbitrary provider secrets. To add or repair one
connector later, rerun `signalweave connections add` or use `connections update`;
to rotate one secret, use `signalweave credentials set NAME`. Run
`signalweave --help` at any time for the complete command list.

## 2. Connect your agent

The native preview can register with Codex during setup:

```sh
signalweave setup --agent codex --register-agent
```

For an already configured local home, use `signalweave connect codex` (the
older `--agent codex` spelling remains accepted).
Registration is opt-in and uses the installed Codex CLI. A conflicting existing
entry is left untouched; registration errors preserve your local setup. Close
concurrent agent-configuration edits while connecting. Registration is not a
live source test. Claude Code receives the exact registration command to review
and run because SignalWeave must not silently edit a user's Claude configuration.
Run **one** command for the agent you use:

```sh
codex mcp add signalweave -- "$HOME/.local/bin/signalweave" serve --home "$HOME/.signalweave"
```

```sh
claude mcp add --transport stdio --scope user signalweave -- "$HOME/.local/bin/signalweave" serve --home "$HOME/.signalweave"
```

Restart or reconnect the agent. Then ask:

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
