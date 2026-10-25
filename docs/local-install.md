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

For available builds and command compatibility, see the
[release reference](local-install-reference.md#release-compatibility).

## 1. Install once, then use the guided setup

Use the published native release below. It downloads the binary, checks
its release checksum, installs to `~/.local/bin`, then starts setup. No Python,
Docker, or `sudo` is required:

```sh
set -o pipefail; curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' https://github.com/waddle-zoo/signal-weave/releases/download/v0.2.0/install.sh | sh -s -- --version v0.2.0 --setup && export PATH="$HOME/.local/bin:$PATH"
```

If your organization does not permit curl-to-shell installation, download and
inspect `install.sh` from that release first, then run it locally. The installer
does not edit shell profiles or agent configuration; setup asks before agent
registration.

To upgrade an existing installation, add `--replace` before `--setup`. Stop
running SignalWeave servers first; configuration and cards are preserved.

Setup runs the newly installed executable by its exact path. On completion,
the command puts `~/.local/bin` first in this terminal's PATH. The installer does not change shell
startup files. In a new terminal, follow its PATH instruction if needed; use
`type -a signalweave` to check for an old binary, alias, or function.

Bare `signalweave` opens guided setup on first run and
shows local status on subsequent runs.

### Terminal and automation output

The current installer shows download, verification and startup-check stages.
Interactive terminals also get curl's download progress bar. In pipes or CI,
progress is plain text on stderr; add `--quiet` to suppress installer progress
and success messages, while keeping errors. Setup prompts are not suppressed.
`NO_COLOR=1` disables color, and `TERM=dumb` disables terminal effects.
Use `status --json` and `health --json` for machine-readable results. MCP stdio
keeps stdout reserved for its protocol—no banners or progress are added there.

The current native build keeps its runtime in `.signalweave-runtime` beside
the installed command. `signalweave` remains the stable command registered with
your agent. Older runtime versions stay available across upgrades for running
processes and are reclaimed by explicit uninstall; local cards and credentials
are separate and remain unless you choose `--purge`. Older published one-file
builds still extract their runtime at each launch; see the
[release reference](local-install-reference.md#release-compatibility).

That one guided command walks through setup in this order:

1. Decision provider (Jev, OpenAI Decisions, or ChatGPT-plan Responses)
2. One or more source connectors and their credentials
3. Optional browser sign-in for ChatGPT-plan access
4. Codex or Claude Code handoff, with confirmation before changing agent config

Already connected Superset or Preset to your agent? SignalWeave does not import
that connection. Connect the workspace directly in this setup, or use the
reviewed, normalized [MCP source bridge](mcp-source-bridge.md) for a
company-specific source. Keep the existing MCP for broader investigation.

## Choose a decision provider

- **Jev** uses TypeSafe's typed decision API. Setup asks for a Jev key and keeps
  it in `typesafe.key`.
- **OpenAI Decisions** calls OpenAI's dedicated typed Decisions endpoint. Setup
  asks for an OpenAI API key and keeps it in `openai.key`. Choose option **2**
  in the wizard; no Jev account is needed. This uses your OpenAI API account,
  not your Codex subscription or its saved credentials.
- **ChatGPT plan** opens a browser for explicit Sign in with ChatGPT consent,
  then uses Responses structured output. It does not call the Decisions endpoint;
  its probabilities are model estimates, not native Decisions API distributions.
  Eligible users can use this local open-source integration without providing an
  API key. SignalWeave does not inspect or reuse Codex CLI credentials.

Use `--decision-provider` for a scripted choice. For example,
`signalweave setup --decision-provider chatgpt-plan --source preset` saves local
setup, then opens browser consent.

To switch an existing installation to OpenAI Decisions, run:

```sh
signalweave setup --update --decision-provider openai-decisions
signalweave health
```

Enter the API key at the hidden prompt; no Jev key or TOML editing is needed.
`signalweave credentials set openai` rotates that credential later. Reconnect
your agent after changing provider. Card discovery, review and recurring runs
use the same workflow; your agent still writes the useful report or alert.
See the [live integration checks](evidence/openai-decisions-live-2026-10-19.md).

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
the full evidence receipt is kept locally. The command pins stable `v0.2.0`;
the installer's default `latest` lookup selects stable releases, never previews.

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

Reconnect SignalWeave in your agent after changing connections or credentials;
already-running servers may still use their startup configuration. If you switch
BI workspaces, review existing cards before reuse: the same chart ID can mean
something different in another workspace.

## 2. Connect your agent

The native executable can register with Codex during setup:

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

Approve the requested SignalWeave tool access in your agent. Registration does
not grant that permission: an unattended client that denies all tool approvals
can connect successfully but still block card reads and evaluations. Before
scheduling, run the same card interactively once, then configure only the tool
permissions your runner needs. Evaluations fetch source evidence, send it to
your chosen provider and save a local receipt; they do not send team messages.
Keep sending permissions separate, and follow your organization's client policy.

The default MCP exposes a short repeated-analysis path:

```text
search_catalog → inspect_resource → onboard_insight_card → owner approval
                                                   recurring:
                                      evaluate_insight_card(card_id)
```

You explain the intent in plain language. The agent finds and inspects candidate
assets, drafts the card with exact source references, and asks you to resolve
important ambiguity before approval. On later runs, the selected provider
applies the approved policy to fetched evidence and, on success, SignalWeave
returns the typed decision, evidence, probabilities, and durable receipt. Check
measurement dates and coverage; a recent fetch does not prove fresh business
data. Oversized judgments return a deferred evidence handoff with no policy
decision, so the agent can continue from the saved evidence. OpenAI Decisions
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

For an existing card, ask your agent to use the guide's `monitor` path. The normal
run needs only the approved card ID and a stable run key: SignalWeave fetches its
sources. The agent need not rediscover the dashboards or copy their observations
into a `context` argument. It can read omitted evidence from the saved receipt
and use its existing company tools for deeper investigation when needed.
The saved receipt includes the inspected source contracts, not just the numbers.
When your brief requires a complete/comparable period, the agent can bind a known
scalar coverage key during onboarding; you do not need to fill out a numerical
analysis form. It should keep example-period findings separate from the rule
that repeats on later runs.

Once those checks work, give your agent a concrete scheduling request:

> Run my approved **[card name]** each weekday at **[time and timezone]**.
> Follow its delivery rules and send one short evidence-backed message to
> **[destination]** when it matters; send nothing for quiet runs. Include what
> changed, why it matters, and the next step. Confirm the schedule and delivery
> access before activating it. If you cannot schedule or deliver, tell me what
> is missing—do not say the automation is running.

Use your agent or workflow runner's supported scheduler. A laptop-based runner
may need the machine awake; SignalWeave itself does not run this schedule.

## Uninstall

Stop any running SignalWeave server and remove its connection using the agent
you registered:

```sh
codex mcp remove signalweave                     # Codex
claude mcp remove --scope user signalweave        # Claude Code
signalweave uninstall
```

Uninstall shows the exact executable and data paths and asks for confirmation.
It removes the native executable but keeps your local configuration,
credentials, cards, and receipts for a reinstall. To permanently remove the
selected private home as well:

```sh
signalweave uninstall --purge
```

Use `--home /absolute/private/home` for a non-default data directory and `--yes`
only when you have reviewed the plan. Purge cannot be undone without a backup.
It refuses homes inside repositories and does not follow symlinks, delete
external credential files, revoke remote authorizations, or edit agent settings.
Remove installed workflow skills from the exact paths reported by
`signalweave skills install` if you no longer want them; user-modified skills are
never removed automatically. Restart your agent after removing the MCP connection.
Python installations should be uninstalled with the package manager used to
install them, not with native self-uninstall.

**Trouble?** Run `"$HOME/.local/bin/signalweave" doctor` for an offline config
check. See the [reference](local-install-reference.md) for supported source
connections, private paths, explicit versions/upgrades, release verification,
and source builds. There is no automatic updater.
