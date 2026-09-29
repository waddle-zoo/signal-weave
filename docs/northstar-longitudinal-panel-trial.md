# Northstar longitudinal panel trial

This trial tests whether SignalWeave is useful as a persistent operating layer,
not just as a classifier on isolated dashboard snapshots.

It replays one human-authored growth card over eight simulated months. Each
month contains six recurring situations:

- ordinary no-change;
- ordinary/modest movement;
- an isolated online decline with a checkout regression;
- a broad corroborated decline;
- a conflicting finance definition; and
- an unavailable primary source.

That produces 48 workflows. The same card remains active across every month.
The expected dispositions, month assignments, and feedback notes are external
owner rubrics in
[`examples/northstar-longitudinal-panel.json`](../examples/northstar-longitudinal-panel.json)
and are never sent to Jev.

## Panel roles

The trial has eight caller-owned role agents around the production
`InsightEngine`:

- card curator;
- analytics investigator;
- Data Trust;
- operations coordinator;
- executive briefing/communications;
- growth leadership;
- feedback steward; and
- independent adversarial reviewer.

These are simulated role participants, not eight competing model opinions. Jev
is the only semantic decision provider. The panel checks whether the typed
result is safe and useful for each role's responsibility, while the independent
reviewer recomputes the report from the external fixture.

## Multi-step behavior

For isolated declines, the simulated analytics agent first returns diagnostic
facts. If Jev still returns `investigate`, the agent retrieves a second
independent incident/data-trust bundle and submits a new trusted context
snapshot. This is a caller-owned loop over the existing SignalWeave handoff;
SignalWeave does not become a scheduler, agent runtime, or delivery system.

The run observed:

- 32 terminal single-step workflows;
- 11 workflows completed after one diagnostic context stage; and
- 5 workflows requiring a second diagnostic stage.

## Latest live result

The latest report was produced with live Jev over the local Northstar seed
rows:

| Measure | Result |
| --- | ---: |
| Workflows | 48 |
| Months | 8 |
| Initial exact outcomes | 48/48 |
| Final exact outcomes | 48/48 |
| Exact typed handoffs | 48/48 at both stages |
| Panel agreement | 48/48 |
| Evidence source recall | 100% |
| Unsafe automatic actions | 0 |
| Missed expected automatic actions | 0 |
| Movement-only automatic alerts | 25 |
| Movement-only unnecessary alerts | 11 |
| Movement-only automatic precision | 56% |
| SignalWeave automatic actions | 14 |
| SignalWeave unnecessary actions | 0 |
| SignalWeave automatic precision | 100% |
| Modeled minutes saved | 1,208 |

The generated report and markdown companion are ignored trial artifacts. Run
the trial with:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python -m evaluations.northstar_longitudinal_panel_trial \
  --seed-dir /absolute/path/to/northstar/warehouse/init \
  --typesafe-key-file /absolute/path/to/apikey_typesafe \
  --output artifacts/northstar-longitudinal-panel.json \
  --strict
```

Then run the independent audit:

```bash
uv run python -m evaluations.northstar_longitudinal_panel_adversarial_review \
  --report artifacts/northstar-longitudinal-panel.json \
  --fixture examples/northstar-longitudinal-panel.json
```

## What this proves—and what it does not

This is strong evidence that the current card, evidence shape, Jev judgment,
handoff contract, and caller-owned multi-step loop work together over repeated
periods without introducing unsafe automatic actions in this simulated
company.

It is not a customer production claim. The Northstar rows, dispositions,
feedback, role agents, acknowledgements, and delivery are simulated. The
modeled time savings are assumptions, not measured query or response latency.
A real adoption still needs the customer to author the card, validate the
source scope, replay historical decisions, and run a shadow period before
enabling delivery.
