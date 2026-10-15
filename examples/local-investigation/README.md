# Company MCP → repeatable investigation

`company_mcp.py` is a small example source gateway. It opens a synthetic SQLite
database read-only, executes separate total and segment queries, and exposes one
reviewed tool returning SignalWeave's typed comparison contract. It is not bundled
into SignalWeave and it does not accept caller-supplied SQL.

Run the opt-in live trial from the repository root:

```sh
uv run python -m evaluations.local_investigation_trial \
  --key-file /private/path/to/typesafe-key
```

The trial creates six synthetic situations, reuses an approved card, calls **live
Jev**, checks numerical expectations and routing, and verifies saved-result replay.
Artifacts go under `artifacts/local-investigation-live/`. No notifications are sent.
The script seeds the approved card to isolate execution; it is not an example of
skipping human approval in a deployed onboarding flow.

For your company, the equivalent source tool must establish the measurement
definition, periods, controlling totals and coverage. Do not merely sum the visible
chart rows and declare the result complete. Return query/run references that an
analyst can inspect, and use the source data's real freshness timestamp.

See [MCP registration](../../docs/mcp-source-bridge.md),
[measurement requirements](../../docs/local-investigations.md), and
[proof and limitations](../../docs/local-investigation-proof.md).
