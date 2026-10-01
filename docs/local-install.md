# SignalWeave on your laptop

Connect SignalWeave to your agent, describe an investigation, review the proposed
card, and rerun it against fresh evidence. You need a **TypeSafe Jev API key**
and access to your company's data sources. No Python or Docker required for the
native executable; an external company MCP may have its own requirements.

Supported builds: macOS Apple Silicon/Intel (macOS 15+; tested on 15), and Linux
x64 with glibc 2.35+ (not Alpine/musl). macOS builds are not Developer-ID signed
or notarized; company device-management policies may block them. Do not disable
those controls—use an administrator-approved installation path instead.

> **Local preview:** `v0.2.0rc1` is a prerelease for trying the local runtime.
> Installation and bounded live-Jev execution have been tested; the new paired
> Luna onboarding benchmark is not complete. This is not an enterprise-readiness
> or comparative-performance claim. The stable v0.1.0 release has no native assets.

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

Run **one** command for the agent you use:

```sh
codex mcp add signalweave -- "$HOME/.local/bin/signalweave" serve --home "$HOME/.signalweave"
```

```sh
claude mcp add --transport stdio --scope user signalweave -- "$HOME/.local/bin/signalweave" serve --home "$HOME/.signalweave"
```

Restart or reconnect the agent. Then ask:

> Use SignalWeave to onboard a recurring investigation of why online sales
> changed and how that affected net sales. Show me the sources, measurement
> definitions, missing context, and a test result before I approve the card.

The agent helps author the card; you approve its meaning and evidence. Connecting
an arbitrary MCP is not automatic normalization of its responses. Scheduling and
delivery stay with your agent or existing scheduler.

**Trouble?** Run `"$HOME/.local/bin/signalweave" doctor` for an offline config
check. See the [reference](local-install-reference.md) for supported source
connections, private paths, explicit versions/upgrades, release verification,
and source builds. There is no automatic updater.
