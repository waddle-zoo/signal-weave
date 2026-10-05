# Local installation reference

Start with the [short setup guide](local-install.md). This page covers source
builds, manual configuration, credentials, and deployment behavior.

## Release builds

The [native release workflow](../.github/workflows/release.yml) builds on
`macos-15` (ARM64), `macos-15-intel` (x64), and `ubuntu-22.04` (x64). These are
[documented GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
The Linux executable targets glibc 2.35+ (not Alpine/musl); macOS builds are
tested on macOS 15, not every older OS. Every target runs installer tests and
starts the frozen executable in a private temporary home: non-interactive setup
with private Jev/source credential files, persisted source/identity settings,
doctor, agent configuration, and an actual MCP initialize/list-tools handshake.
The installer then repeats that smoke against the installed executable, outside
the checkout. These checks use dummy credentials,
make no Jev call, and do not prove source credentials or analytical quality.

Pushes to `main` or `feat/local-investigation-runtime` and manual
`workflow_dispatch` runs upload three `native-*` Actions artifacts without
publishing a release.
Use the Actions UI to download the artifact for your system, unzip the Actions
download, and check its archive before extracting in a new directory:

```sh
shasum -a 256 -c signalweave-vVERSION-darwin-arm64.tar.gz.sha256
tar -xzf signalweave-vVERSION-darwin-arm64.tar.gz
./signalweave --help
./signalweave setup
```

Replace `vVERSION` and the platform with the actual artifact filename. Keep the
executable at a persistent path and use that absolute path when registering
your agent; the short guide's `~/.local/bin` commands apply to installer-based
installs. Branch archives use the current package version but are **not stable
releases**. `build-info.json` records their source commit and platform. Builds
bundle Python, not source-server runtimes or company credentials.

Only a pushed `vMAJOR.MINOR.PATCH` or `vMAJOR.MINOR.PATCHrcN` tag matching
`pyproject.toml` can publish. The `rcN` form follows Python's release-candidate
version spelling (for example `v0.2.0rc2`). All three builds must pass.
Use an annotated tag: its annotation becomes the release notes.
Publication creates a new draft, uploads
archives, per-file checksums, `SHA256SUMS`, and the installer, and only then
publishes it. Existing releases/assets are never overwritten. A failed draft
requires manual review; the workflow does not delete or replace it on rerun.
Release candidates are marked prerelease and never replace GitHub's stable
latest release. Publishing a preview does not certify analytical quality.

Actions are pinned to verified upstream commits. Dependencies use `uv.lock`.
Release files have GitHub build-provenance attestations; verify an archive with
an authenticated GitHub CLI:

```sh
gh attestation verify ./signalweave-vVERSION-darwin-arm64.tar.gz --repo waddle-zoo/signal-weave
```

Checksums detect corruption; they do not independently authenticate a compromised
release account. The installer downloads only HTTPS URLs under this repository,
restricts archive members to three regular files, and streams the binary without
extracting archive paths. It smoke-tests before installing. It does not enforce
attestation verification automatically. macOS binaries are not Developer-ID
signed/notarized. Do not disable security controls to make them run.

## Installer versions and upgrades

Download `install.sh` from a published release (or inspect it in the repository),
then select a stable or preview version explicitly. For a stable release, the
short path is:

```sh
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
  https://github.com/waddle-zoo/signal-weave/releases/latest/download/install.sh | sh
```

For a pinned or preview version:

```sh
sh install.sh --version vVERSION
sh install.sh --version vVERSION --replace
```

For this local preview, replace `vVERSION` with `v0.2.0rc2`. Default `latest`
never accepts a prerelease; it does not silently opt users into preview builds.

`--replace` opts into replacing an existing regular executable; without it the
installer refuses an existing destination. Configuration and cards are untouched.
Stop running agents before upgrading, then restart them. There is no automatic
rollback/migration promise; back up local state before a breaking release.

`SIGNALWEAVE_INSTALL_DIR=/absolute/path` overrides `~/.local/bin`. Relative paths
and symlink destinations are rejected. Installation uses an atomic same-filesystem
rename (or no-clobber link for first install); failed download, checksum, archive,
or startup checks leave the existing executable unchanged. The installer does
not edit PATH, shell profiles, agent configuration, or local credentials.

SignalWeave can run as a **standalone executable** or an installed Python CLI.
The standalone build bundles Python: its users do not need a Python installation
for SignalWeave itself. A separately configured company MCP may have its own
runtime requirements. The native release workflow builds macOS ARM64/x64 and
Linux x64 artifacts; a branch build is not a published release.

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
./dist/signalweave setup
```

Copy the executable to a persistent location before generating your agent config.
Each release target must pass its native runner's offline smoke test before
publication. Windows is not a release target. macOS signing/notarization is not
configured; do not bypass your company's endpoint-security policy. This is a PyInstaller one-file executable,
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

`setup` is the normal onboarding entry point: it also establishes local identity
and source settings. The lower-level `init` command below only creates key/config
storage; by itself it does not establish the tenant/principal needed for card approval.

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
are intentionally available. The setup wizard stores `SUPERSET_PASSWORD_FILE`;
the local-home loader reads that private file into the process environment for
the Superset client. Bare environment-only deployments still expect an inline
`SUPERSET_PASSWORD` (or a deployment-owned secret loader).

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
signalweave health --home "$HOME/.signalweave"
```

This is an **offline configuration check**. (`signalweave doctor` is retained as
an alias.) It reads key/configuration files,
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

The normal path is to let the official agent CLI register SignalWeave:

```sh
signalweave connect codex
signalweave connect claude
```

These commands never pass credentials to the agent. They use the official MCP
CLI, leave conflicting entries untouched, and print a manual command if the
agent CLI is unavailable. To inspect the exact entry without changing anything,
print the matching snippet from the installed CLI:

```sh
signalweave agent-config --agent codex --home "$HOME/.signalweave"
signalweave agent-config --agent claude --home "$HOME/.signalweave"
```

The Codex output is a `[mcp_servers.signalweave]` TOML block with `command` and
`args`. The Claude output is a JSON `mcpServers` object. If you manage agent
configuration yourself, merge only the `signalweave` entry and preserve all
existing settings; do not overwrite a whole config with the output.

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
