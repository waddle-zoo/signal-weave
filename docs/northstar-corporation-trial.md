# Northstar Outfitters corporation trial

This evaluation extends the local Northstar Outfitters Superset trial into a
small analytical organization. It asks a more useful question than “can one
card classify one dashboard?”:

> Can a company define many monitoring workflows once, let different analytical
> roles use them, and route only evidence-backed decisions up to operators and
> executives?

The trial keeps SignalWeave’s boundary intact. The corporation, role graph, and
handoffs are evaluation fixtures. SignalWeave performs the MCP workflow, source
resolution, evidence construction, Jev judgments, safety gates, and inspectable
receipts. No Slack, email, or incident destination is contacted.

## Organization model

The editable roster contains 40 role agents:

- 12 dashboard curators, one for each Northstar analytical domain;
- 12 domain analysis leads;
- 6 enterprise operations roles;
- 6 executives;
- 4 communications partners.

The 48 workflows cover all 12 domains with four states each:

- corroborated movement that should notify an owner;
- explainable movement that should be suppressed;
- contradictory evidence that should go to investigation;
- stale data that should escalate to the data or operating owner.

The role chain is curator → analyst → cross-domain operations → routed executive
or investigation owner → simulated communication acknowledgement.

## Live Jev result

Generated from the local TypeSafe run on 2026-09-21:

| Measure | Result |
| --- | ---: |
| Workflows | 48 |
| Exact outcomes | 48/48 |
| Provenance-complete results | 48/48 |
| Unsafe automatic actions | 0 |
| Fully automatable decisions | 36/48 |
| Human investigation decisions | 12/48 |
| Jev-backed evaluation latency | 606 ms median; 731 ms p95 |
| Hash-chained trace | 1,352 events; valid |
| Simulated handoffs | 36; delivery disabled |

The corresponding movement-only baseline—representing the common current state
where a dashboard movement alone creates an alert—was:

- 12/48 exact outcomes;
- 24 false automatic alerts caused by explainable or contradictory movement;
- 12 missed stale-data escalations;
- human review required for all 48 workflows.

The live output is in
[`artifacts/northstar-corporation/jev-report.md`](../artifacts/northstar-corporation/jev-report.md).
Those generated artifacts are ignored by Git because they can contain local
trial data and should not be treated as source code.

## Run it

The live trial requires a TypeSafe credential in the environment. The command
below keeps the key in a file and does not write it to the report:

```bash
TYPESAFE_API_KEY_FILE=/path/to/apikey_typesafe \
PYTHONPATH=src:. \
.venv/bin/python -m evaluations.northstar_corporation_trial \
  --evaluator jev
```

Use `--evaluator research` for a local wiring run without network access. That
mode is explicitly a test double and is not evidence for Jev quality.

The organization configuration lives in
[`evaluations/data/northstar-corporation.json`](../evaluations/data/northstar-corporation.json).
The production package is not changed by this simulation.

## What this proves—and what it does not

This is stronger than the single-dashboard trial because it exercises many
domains, role handoffs, repeated cards, multiple adapters, suppressions, and
investigations in one trace. It provides evidence that the current SignalWeave
contracts can support an organization-shaped operating model.

It does not prove that 40 independent agents would curate good cards, that the
Northstar labels match a real company’s judgment, or that all BI analysis can be
automated. Cards are pre-curated and the role participants are simulated. The
next credible step is a time-split shadow replay with real domain-owner labels:
start with one team, then expand domain by domain only when useful-alert rate,
false-action rate, provenance, and human correction remain within agreed limits.
