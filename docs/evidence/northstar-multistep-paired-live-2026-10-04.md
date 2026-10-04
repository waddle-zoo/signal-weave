# Northstar live Jev-assisted multi-step comparison

On 2026-10-04, the same `gpt-5.6-luna` agent ran six Northstar Outfitters
scenarios twice: once with the shared cards/connectors/tools alone, and once
with a live Jev preflight bundle from SignalWeave. Both arms performed the
frontier-model analysis. Jev was not asked to infer the business cause; it
provided bounded typed retrieval guidance before the agent's staged workflow.

| Measure | Luna only | Luna + SignalWeave/Jev |
| --- | ---: | ---: |
| Initial exact outcomes | 6/6 | 6/6 |
| Final exact outcomes | 2/6 | 5/6 |
| Unsafe automatic actions | 2 | 1 |
| Mean required-evidence recall | 0.833 | 0.917 |
| Median end-to-end time | 3.98s | 6.30s |
| Median agent-only time | 3.98s | 6.06s |
| Jev requests | 0 | 6 |
| Jev input/output tokens | 0 / 0 | 37,369 / 680 |

The cases covered ordinary no-change, modest movement, an isolated online
regression with diagnostic context, a corroborated broad decline, a conflicting
metric definition, and an unavailable primary source. Jev-assisted Luna was
better on three paired cases, tied on three, and worse on none. The main tradeoff
was roughly 261ms mean Jev preflight latency and additional provider usage.

The independent reviewer reconstructed all 12 raw runs, verified one baseline
and one treatment per case, identical shared input/prompts/tool schema/model,
private labels and diagnostic facts, valid provenance, and exact stored-summary
recalculation. This is evidence for the Jev-as-retrieval/preflight boundary on
this fixture, not proof of production reliability or causal truth in arbitrary
enterprise data.

Raw report: `/private/tmp/signalweave-northstar-multistep-paired-live-20261004-v2/report.json`.
Independent review: `/private/tmp/signalweave-northstar-multistep-paired-live-20261004-v2/review.json`.
