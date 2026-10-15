# Run SignalWeave on a server

SignalWeave supports two transports for the same card workflow: stdio for a
local agent and Streamable HTTP MCP for a server. A server can read an existing
Superset instance, hosted Preset workspace, or another configured source; the BI
system does not need to run on the same host.

## Native executable

Install the native executable using the [local installation guide](local-install.md),
or use the container deployment below. See [release compatibility](local-install-reference.md#release-compatibility)
before upgrading an older executable.
Run these commands as the operating-system account that will own the service:

```sh
signalweave setup --home "$HOME/.signalweave" --no-register-agent
signalweave health --live --home "$HOME/.signalweave"
```

Choose a decision provider and configure the sources the service may read.
For an unattended service, use a provider API credential and source service
credentials approved by your organization. Setup saves a tenant/principal
identity and persistent card/receipt storage in the selected private home.
The live health check tests source access; review an actual card run separately.

Create a strong, unique API token through your secret manager and make it
available in a private, service-readable file. Start a single-identity sidecar:

```sh
SIGNALWEAVE_API_TOKEN_FILE=/absolute/path/to/private/api-token \
  signalweave serve --home "$HOME/.signalweave" \
    --transport streamable-http --host 127.0.0.1 --port 8000
```

The file contains the token value, not a variable assignment. Configure either
`SIGNALWEAVE_API_TOKEN_FILE` or `SIGNALWEAVE_API_TOKEN`, not both. Clients send
`Authorization: Bearer <token>` on requests to `/mcp`.

| Endpoint | Purpose |
| --- | --- |
| `/mcp` | Authenticated Streamable HTTP MCP |
| `/healthz` | Public, non-secret runtime health |
| `/readyz` | Public startup/configuration readiness; not a live analytical quality check |

Keep the loopback binding behind a TLS reverse proxy when connecting remote
clients. Run the command under your service manager and preserve the private
home across restarts. Agents use their client's remote-MCP configuration to
connect to the HTTPS `/mcp` endpoint; local stdio registration is a separate path.

## Docker and hosted Preset

The repository includes a Dockerfile and a Preset Compose deployment with a
persistent SQLite volume. The [Preset quickstart](preset-integration.md#self-hosted-quickstart)
covers workspace credentials and mounted-secret overlays. This connects to the
customer's existing Preset workspace; it does not install Superset again.

For a custom `docker run` deployment, set `MCP_HOST=0.0.0.0` inside the
container and publish the port only to the host's loopback interface
(`-p 127.0.0.1:8000:8000`) behind your TLS proxy. The supplied Compose files
already set this bind address. Source configuration, provider credentials,
tenant/principal, and authentication are still required; publishing a port
alone is not a complete deployment.

For other sources, configure the container's runtime environment and mount its
credential and catalog files according to the [source adapter guide](source-adapters.md).
The general `docker-compose.yml` includes a **local development Superset** and
demo credentials; use the dedicated Preset deployment or a reviewed container
configuration for an existing business environment.

## Shared deployment

A static bearer token represents one configured tenant/principal. For
request-scoped identities, use `SIGNALWEAVE_AUTH_MODE=oidc` and your organization's
OIDC issuer, audience, tenant claim, and required scopes. See the
[security configuration](security.md#defenses-in-the-repository).

Deploy one evaluator process with durable storage and backups. The default
SQLite store is a single-process deployment; multiple replicas require a
separately implemented shared transactional store and recovery design.
Configure TLS, secret rotation, source permissions, and a data-egress policy:
evaluations send bounded evidence to the selected decision provider.

## Run recurring work

Connect your agent to `/mcp`, onboard and review a card, then approve it. On
each scheduled run, the agent calls `evaluate_insight_card` with a stable
idempotency key, reads the result and evidence, investigates when needed, and
uses its own delivery tools to send the appropriate message.

Scheduling and Slack/email delivery belong to the agent or workflow runner.
SignalWeave persists the card, decision, and evidence receipt. The optional
`full` profile also exposes the [webhook evaluation contract](shadow-pilot-contract.md).
See the [example remote investigation agent](../examples/investigation_agent/README.md#run-against-a-deployed-signalweave)
for a caller-owned HTTP client and investigation loop.
