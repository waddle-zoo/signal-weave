# Install and run SignalWeave locally

SignalWeave can run as a **standalone executable** or an installed Python CLI.
The standalone build bundles Python: its users do not need a Python installation
for SignalWeave itself. A separately configured company MCP may have its own
runtime requirements. No signed/downloadable release is claimed by this branch.

The production semantic core remains **Jev-only**; local setup does not add an
offline model or heuristic fallback. Local-first means configuration and durable
state live on your machine, while evaluation still uses configured sources and
TypeSafe Jev.

## Install this checkout

To build a standalone executable for the current platform:

```sh
uv sync --extra binary
uv run python scripts/build_binary.py
./dist/signalweave --help
./dist/signalweave init
```

Copy the executable to a persistent location before generating your agent config.
The current proof is macOS ARM64 only; Linux/Windows distribution, signing and
notarization still need release tests. This is a PyInstaller one-file executable,
not a cross-compiled Rust/Go binary. OS sandboxes that deny its extraction or
semaphore operations can prevent startup.

Alternatively, install the Python CLI (Python 3.11+):

Use a persistent virtual environment outside the checkout. Substitute the
absolute path to your SignalWeave checkout in the install command:

```sh
python3 -m venv "$HOME/.local/share/signalweave/venv"
"$HOME/.local/share/signalweave/venv/bin/python" -m pip install /absolute/path/to/signal-weave
export PATH="$HOME/.local/share/signalweave/venv/bin:$PATH"
signalweave --help
```

The PATH change affects this shell. Use the full executable path in a new shell,
or add the PATH setting to your own shell configuration. Reinstall from the
checkout to pick up later changes. Agent snippets use the absolute Python path
from this installation, so they do not depend on the agent's PATH or working
directory. Keep that virtual environment in place.

## Initialize a private local home

```sh
signalweave init
```

Enter the TypeSafe API key at the hidden terminal prompt. No echoed-input fallback
is allowed. For unattended setup, provide an existing UTF-8 file containing just
the key instead of putting the secret in command arguments:

```sh
chmod 600 /absolute/path/to/typesafe-key
signalweave init --key-file /absolute/path/to/typesafe-key
```

`init` copies the key into the local home; subsequent startup does not depend on
the input file. It never copies ambient source credentials or edits an agent's
configuration. The default home is `~/.signalweave`. `SIGNALWEAVE_HOME` changes
that default; an explicit `--home /absolute/path` takes precedence.

`init` **only prepares local configuration and storage directories**. It does
not connect, discover, onboard, or approve sources, and it does not create or
approve insight cards. Configure sources separately, then use the MCP
review/approval flow described in the [demo walkthrough](demo.md).

The home contains:

| Path | Purpose |
| --- | --- |
| `config.toml` | Versioned settings, using existing runtime environment names |
| `typesafe.key` | TypeSafe key, stored as plaintext with restricted permissions |
| `state/` | Durable SQLite database, cards, feedback, and decision receipts |

On POSIX systems, the home and state directory are created with mode `0700`, and
configuration/key files with `0600`. Existing paths must be owned by the current
user, private, and not symlinks. SignalWeave refuses unsafe paths instead of
changing permissions on unrelated files. On Windows, protect the home with an
owner-only ACL; POSIX permission checks are not an ACL implementation.

Repeating `init` preserves configuration, key, and stored decisions. Repeating
`init --key-file` with the same key also succeeds; a different key is rejected.
To rotate the key, update `typesafe.key` through your trusted secret workflow,
retain its private permissions, and restart the local process. A partially
completed init with a valid private key can be rerun without entering it again.

## Configure sources and check offline

Edit `[environment]` in the printed `config.toml`. Values must be TOML strings.
The generated `SIGNALWEAVE_ALLOW_EMPTY_SOURCES = "1"` permits local startup for
onboarding without a configured adapter. It does not provide evidence or permit
evaluation without approved sources. Remove this setting to require at least
one source at startup.

For an existing Superset instance, add its URL and credentials to that section:

```toml
SUPERSET_URL = "https://superset.example.com"
SUPERSET_USERNAME = "your-username"
SUPERSET_PASSWORD = "your-password"
```

Replace the examples with real values before running `doctor`. Superset may use
HTTP for a local instance and may omit both login fields when anonymous reads
are intentionally available. Its runtime does not support `SUPERSET_PASSWORD_FILE`.
Use the private configuration file or an injected environment value.

For Preset, use the existing deployment settings, including HTTPS URL, matching
tenant/principal, data policy, and either the access-token file or the API-token
name/secret files. See [hosted connectors](hosted-connectors.md) and
[Preset integration](preset-integration.md). Files referenced by local settings
are resolved relative to the local home. Keep source secrets private too.

For an approved Trino catalog, set `TRINO_URL` and `TRINO_CATALOG_FILE` together;
see [metric query cards](metric-query-cards.md). For the MCP source bridge, set
`SIGNALWEAVE_MCP_SOURCES_FILE` to a deployment-owned JSON manifest; see
[MCP source bridge](mcp-source-bridge.md). `doctor`
reuses the bridge's manifest schema validation without launching a source MCP
process or making a request. Referenced source credentials and remote tool
contracts still need separate verification. Source subprocess commands and
their arguments should use absolute paths.

The bridge is read-only and requires an explicit manifest of approved resource
identities, tenant contracts, fixed tool calls, and arguments. Its source tool
must return the normalized SignalWeave snapshot contract. Registering an
arbitrary MCP server does not automatically turn its tools or raw responses into
SignalWeave sources; provide that normalization and read-only contract first.

```sh
signalweave doctor --home "$HOME/.signalweave"
```

This is an **offline configuration check**. It reads key/configuration files,
checks relevant credential/source settings, parses source manifests/catalogs,
and reports onboarding-only mode when no adapter is configured. Exit status is
zero for successful offline checks and one for invalid or missing configuration.
It does not create a runtime/database, send a Jev request, validate a key with its
issuer, or test source connectivity/access. A pass is not evidence of live
readiness. Diagnostic output never includes credential values or config contents.

## Launch and configuration precedence

```sh
signalweave serve --home "$HOME/.signalweave"
```

Stdio is the default transport. An agent launches this command and communicates
over stdin/stdout; a silent terminal is expected. Startup emits no setup banners
on stdout. Setup failures go to stderr and exit nonzero.

`serve --home` and `serve` with `SIGNALWEAVE_HOME` load local settings before
constructing the runtime. Plain `serve` without either retains the existing
environment-only deployment behavior, including its requirement for sources;
it does not discover a local home implicitly. `init`, `doctor`, `agent-config`,
and `run` default to the local home.

Existing process environment settings override local settings. Selecting a
secret value or its `*_FILE` variable overrides the whole local credential pair,
so a local key file does not shadow an explicitly injected key. Setting both
TypeSafe key sources is rejected for local commands. An explicitly empty
environment setting also overrides the local value. In local mode, relative
state, catalog, manifest, and credential paths (including environment overrides)
are relative to the selected home. Default JSON store paths are also under
`state/` if the JSON backend is selected. An explicit absolute storage path
remains absolute.

For existing HTTP deployments, `--transport streamable-http` keeps its bearer/OIDC
and trusted-principal requirements. Local setup does not disable HTTP security.
See [security](security.md). Local storage does not make Jev evaluation offline:
evaluation sends the configured evidence to TypeSafe and can access configured
source services.

## Connect Codex or Claude Code

Print the matching snippet from the installed CLI:

```sh
signalweave agent-config --agent codex --home "$HOME/.signalweave"
signalweave agent-config --agent claude --home "$HOME/.signalweave"
```

The Codex output is a `[mcp_servers.signalweave]` TOML block with `command` and
`args`. Merge it into your user `~/.codex/config.toml`, preserving existing
settings. The Claude output is a JSON `mcpServers` object; merge the
`signalweave` entry into a project `.mcp.json`, or use Claude Code's user-scope
CLI registration. Do not overwrite existing agent configuration with the whole
output. SignalWeave only prints snippets and never edits those files.

For manual registration using the installation above:

```sh
codex mcp add signalweave -- "$HOME/.local/share/signalweave/venv/bin/signalweave" serve --home "$HOME/.signalweave"
claude mcp add --transport stdio --scope user signalweave -- "$HOME/.local/share/signalweave/venv/bin/signalweave" serve --home "$HOME/.signalweave"
```

These optional commands are run by you and do change agent configuration.
The command forms and snippet schemas were checked against the official
[Codex MCP documentation](https://developers.openai.com/codex/mcp/) and
[Claude Code MCP documentation](https://code.claude.com/docs/en/mcp) on
2026-09-30. Snippets include no secrets; the local process reads them from its
configured home. Restart/reconnect the agent after registering the server.

## Run an approved card once

```sh
signalweave run CARD_ID --run-key daily:2026-09-30 --home "$HOME/.signalweave"
signalweave run CARD_ID --run-key daily:2026-09-30 --output ./reports --home "$HOME/.signalweave"
```

`run` invokes the production card-evaluation path once and prints its JSON
result. The optional `--output` is a directory, resolved from your current
working directory, for rendered artifacts. Use a stable run key to retry the
same evaluation idempotently; use a new key for a new evaluation. The card must
already have completed review and approval and have approved source evidence.
Live evaluation can make source and Jev requests. SignalWeave does not install
a scheduler; scheduling and delivery remain with your existing caller.
