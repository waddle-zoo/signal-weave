# SignalWeave on your laptop

Connect SignalWeave to your agent, describe an investigation, review its source
scope, and use the saved card on recurring runs. Codex or Claude does broader
discovery, causal investigation, and narrative; your selected decision provider
applies the card's policy. No Python or Docker is required for the native
executable; an external company MCP may have its own requirements.

Supported builds: macOS Apple Silicon/Intel (macOS 15+; tested on 15), and Linux
x64 with glibc 2.35+ (not Alpine/musl). macOS builds are not Developer-ID signed
or notarized; company device-management policies may block them. Do not disable
those controls—use an administrator-approved installation path instead.

> **Published preview:** `v0.2.0rc1` is available for trying the local runtime.
> Installation, guided setup, local agent handoff, and source retrieval have been
> tested. This preview is not a claim of enterprise analytical quality.
> The published `v0.2.0rc1` binary predates the provider choices in this
> checkout and the installer's `--setup` option. A newer release built from
> this source is required for the one-line flow and newer provider integrations.

## 1. Install once, then use the guided setup

Use the exact published preview below. It downloads the native binary, checks
its release checksum, installs to `~/.local/bin`, then starts setup. No Python,
Docker, or `sudo` is required. This preview has the older Jev-only wizard:

```sh
set -o pipefail; curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' https://github.com/waddle-zoo/signal-weave/releases/download/v0.2.0rc1/install.sh | sh -s -- --version v0.2.0rc1 && export PATH="$HOME/.local/bin:$PATH" && "$HOME/.local/bin/signalweave" setup
```

If your organization does not permit curl-to-shell installation, download and
inspect `install.sh` from that release first, then run it locally. The installer
does not edit shell profiles or agent configuration; setup asks before agent
registration.

The command puts `~/.local/bin` first in this terminal's PATH so an older binary
does not silently shadow the download. The installer does not change shell
startup files. In a new terminal, follow its PATH instruction if needed; use
`type -a signalweave` to check for an old binary, alias, or function.

The remaining instructions describe the newer **unpublished source candidate**.
They require a native build from this checkout, not the `v0.2.0rc1` download.
Do not use a `releases/latest` URL for this prerelease: the latest stable release
is older and does not provide this installer flow.

In the source candidate, bare `signalweave` opens guided setup on first run and
shows local status on subsequent runs.

That one guided command walks through setup in this order:

1. Decision provider (Jev, OpenAI Decisions, or ChatGPT-plan Responses)
2. One or more source connectors and their credentials
3. Optional browser sign-in for ChatGPT-plan access
4. Codex or Claude Code handoff, with confirmation before changing agent config

## Choose a decision provider

- **Jev** uses TypeSafe's typed decision API. Setup asks for a Jev key and keeps
  it in `typesafe.key`.
- **OpenAI Decisions** calls OpenAI's dedicated typed Decisions endpoint. Setup
  asks for an OpenAI API key and keeps it in `openai.key`.
- **ChatGPT plan** opens a browser for explicit Sign in with ChatGPT consent,
  then uses Responses structured output. It does not call the Decisions endpoint;
  its probabilities are model estimates, not native Decisions API distributions.
  Eligible users can use this local open-source integration without providing an
  API key. SignalWeave does not inspect or reuse Codex CLI credentials.

Use `--decision-provider` for a scripted choice. For example,
`signalweave setup --decision-provider chatgpt-plan --source preset` saves local
setup, then opens browser consent.

The normal `agent` profile exposes the card-and-agent workflow;
`signalweave setup --profile full` adds advanced metric-query, evaluation,
certification, and webhook tools.

It writes a private local home at `~/.signalweave`; TOML editing is not needed.
Tenant and principal default to the private local identity `local`. After each
connector, the wizard offers to add another, so a person can connect Superset
plus Trino or a reviewed company MCP manifest in one pass. The agent supplies
source discovery, deeper analysis, and narrative; SignalWeave stores the
reviewed card, fetches its fixed sources, and returns a policy result from the
selected provider.

The installer selects macOS Apple Silicon/Intel or Linux x64, verifies the
archive's SHA-256 checksum, and installs without `sudo`. A provider credential
or ChatGPT-plan authorization is required for card decisions. Each evaluation
sends the approved card and bounded source evidence to the selected provider;
the full evidence receipt is kept locally. The pinned version
explicitly opts into this preview; previews are never selected by the
installer's default `latest` lookup.

For an interactive setup, SignalWeave offers to connect the selected agent at the
end. Press Enter to accept. It invokes only the selected agent's official MCP
CLI; if that CLI is not installed or refuses an existing entry, SignalWeave
prints the exact command to review and run. To make the choice explicit in
scripts, use `--register-agent` or `--no-register-agent`.

After setup, the normal human path is:

```sh
signalweave status
signalweave connections add       # add another source without editing TOML
signalweave connections update    # change a source endpoint or credential mode
signalweave credentials set NAME  # rotate one secret without editing config
signalweave health --live         # test catalog access; does not spend a Jev judgment
signalweave connect codex          # or: signalweave connect claude, if skipped during setup
signalweave ui --open              # optional local health page in your browser
```

If you want to change one secret later, use a hidden prompt or a private file:

```sh
signalweave credentials list
signalweave credentials set typesafe # configure or rotate the Jev key
signalweave credentials set openai   # configure or rotate the OpenAI API key
signalweave auth login              # connect or reconnect ChatGPT-plan access
signalweave auth status             # check local ChatGPT-plan connection
signalweave auth logout             # remove locally saved ChatGPT tokens
signalweave credentials set superset-password --file /private/path/password
```

`connections add` and `connections update` are interactive when you omit
`--source`; they keep the other configured sources and only ask for the fields
that belong to the selected connector:

| Connector | Human enters | Stored privately |
| --- | --- | --- |
| Superset | URL, username, password | Superset password file |
| Preset | workspace URL, API-token pair or bearer token | Preset credential file(s) |
| Trino | URL, catalog JSON, optional catalog/schema/user | Catalog path and bounds |
| Company MCP | reviewed read-only manifest path | Manifest path; provider secrets stay with the MCP |

For example, `signalweave connections update` is the normal way to change a
workspace URL or switch a Preset credential mode; `signalweave credentials set
preset-access-token` (or `preset-api-token-secret`) rotates one secret without
editing configuration.

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
Registration is opt-in and uses the installed Codex or Claude CLI. A conflicting
existing entry is left untouched; registration errors preserve your local setup.
If an entry conflicts, inspect it in your agent's MCP settings. Remove or rename
it only if you intend to replace it, then retry `signalweave connect codex` or
`signalweave connect claude`. Repeating the printed add command will not resolve
an existing-name conflict.
Close concurrent agent-configuration edits while connecting. Registration is
not a live source test. If the official CLI is unavailable, run **one** command
for the agent you use:

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

The default MCP exposes a short repeated-analysis path:

```text
search_catalog → inspect_resource → onboard_insight_card → owner approval
                                                   recurring:
                                      evaluate_insight_card(card_id)
```

You explain the intent in plain language. The agent finds and inspects candidate
assets, drafts the card with exact source references, and asks you to resolve
important ambiguity before approval. On later runs, the selected provider
applies the approved policy to fresh evidence and SignalWeave returns the typed
decision, evidence, probabilities, and durable receipt. OpenAI Decisions
provides its typed distribution; ChatGPT-plan Responses provides model-estimated
probabilities instead. The agent—not the decision provider—owns deeper source
discovery, causal investigation, explanation, schedule, and delivery. New
sources require an owner-reviewed card update. Arbitrary MCP responses are not
automatically normalized or understood.

The selected provider makes a card-bounded policy decision; it does not
establish causality or replace the agent's investigation.
`evaluate_insight_card` runs in shadow mode: it never sends a message. The
advanced `full` profile adds query, certification, and webhook capabilities;
it uses the configured decision provider just like the normal `agent` profile.

Before relying on a recurring workflow, agree on **what matters, which sources
are in scope, who receives the agent's report, and who runs the schedule**. Test
a meaningful change, a quiet period, and missing evidence. An approved card
alone does not schedule work or send an alert.

**Trouble?** Run `"$HOME/.local/bin/signalweave" doctor` for an offline config
check. See the [reference](local-install-reference.md) for supported source
connections, private paths, explicit versions/upgrades, release verification,
and source builds. There is no automatic updater.
