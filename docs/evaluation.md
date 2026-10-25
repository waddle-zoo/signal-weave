# Tests and proof guide

Use the evidence index at [`evaluations.md`](evaluations.md) for current
product-path and whole-agent study results. This page separates what automated
tests protect from what a workflow study actually demonstrates.

## Active product contracts

Run the regular offline suite and lint together:

```bash
make verify
```

This runs Ruff and pytest discovery under `tests/`. These tests protect source,
policy, safety, reporting, runtime, and current journey-harness contracts. They
do not by themselves establish model accuracy, agent usefulness, or customer
outcomes. Current native and whole-workflow regression tests remain in this
suite.

## Actual whole-agent journeys

Completed agent-run workflows and their results are indexed in
[`evaluations.md`](evaluations.md), with retained records under
[`evidence/`](evidence/). Read each report’s protocol, original failures,
censoring, and limitations; a passing harness test is not a substitute for a
fresh agent run. Keep different study attempts and denominators separate.

For a retained JSONL provider audit, run
`uv run python -m evaluations.provider_accounting artifacts/<study>/<arm>.jsonl`.
This read-only reconciliation separates forwarded requests from local research
budget rejections. It does not change the original result, undo a censored run,
or infer billing cost from token counts.

Fresh native journey studies freeze the executable identity and its external
runtime inventory before paid actors. Later checks reject missing or changed
runtime contents before executing the binary. Use an older report's pinned
method revision to inspect its original study; a newer harness guard does not
retroactively certify or rescore earlier runs.

## Historical harness tests

Five older fixture/scoring cohorts are kept outside default pytest discovery.
Run them explicitly when changing their evaluation code:

```bash
make historical-eval-tests
```

These are offline evaluation-harness tests, not live model or connector proofs.
Their reports and exact pre-move source hashes are in
[`archive/research/README.md`](archive/research/README.md) and
[`archive/research/MOVE-MANIFEST.md`](archive/research/MOVE-MANIFEST.md).

## Source, model, delivery, and human boundaries

- **Sources:** unit tests commonly use fixtures or injected adapters. The
  Superset integration test is a separate, explicitly enabled local-service
  check; a mocked connector does not prove a live account integration.
- **Models:** regular unit tests do not establish semantic model quality.
  Provider-backed trials are explicit runs; follow the linked report for the
  configured model, inputs, credentials, and retained failures.
- **Delivery:** simulated outboxes and delivery-disabled runs are not external
  Slack, email, or incident delivery. A report must say which sink actually
  ran.
- **People:** scripted owners, personas, and simulated recipients are not a
  real-human usability panel. Treat human-review steps according to the
  evidence the report actually retained.

The previous long-form guide is preserved byte-for-byte as
[`evaluation-legacy.md`](archive/research/evaluation-legacy.md). For its
original navigation and neighboring docs, use the immutable
[repository snapshot at `437ab297`](https://github.com/waddle-zoo/signal-weave/blob/437ab297bb621c724edc71b138b5ff774759c51f/docs/evaluations.md).
