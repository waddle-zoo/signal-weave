# Northstar retrieval ablation

This exploratory trial isolates the gap found in the scaled Northstar retrieval run: the current cold-start authoring path searches from the natural-language goal, while a real monitoring workflow already has a human-approved anchor and may have graph relationships around it.

The harness uses one Jev request for each of seven messy variants: corroborated movement, explained movement, contradictory evidence, stale evidence, definition mismatch, missing baseline, and source failure. It holds the adapter-owned candidate set fixed and asks Jev for typed probabilities across five independent questions per candidate:

- overall relevance to a cold-start goal;
- relatedness to the approved anchor and graph context;
- diagnostic value;
- data-quality value;
- owner or routing value.

The offline evaluator then compares three policies:

1. `goal_only`: select the top ten by overall relevance;
2. `anchor_aware`: select the top ten by anchor/context relatedness;
3. `role_aware`: assemble up to two candidates per evidence role above a threshold.

The expected resource groups never enter the Jev state. The request contains only the goal, anchor descriptor, adapter-owned descriptors, and lineage-derived graph context. This is important: the experiment tests retrieval and bundle assembly, not whether Jev can reconstruct missing business intent from a vague prompt.

Run it with:

```bash
PYTHONPATH=src:. .venv/bin/python -m evaluations.northstar_retrieval_ablation \
  --output artifacts/northstar-retrieval-ablation/report.json
```

## Live result

The live run on 2026-09-22 used seven Jev requests—one per variant—with 240
typed questions per request. The adapter boundary exposed 600,000 virtual
resources across six adapters while only 48 candidates per variant were sent
to Jev. No full catalog scan or evaluator-label leakage was used.

| Policy | Mean required-group recall | Mean acceptable precision | Complete bundles |
| --- | ---: | ---: | ---: |
| `goal_only` | 0.310 | 0.610 | 0/7 |
| `anchor_aware` | 0.381 | 0.675 | 0/7 |
| `role_aware` | 0.167 | 0.607 | 0/7 |

This is a useful negative result. A human-approved primary anchor improves the
retrieval signal, but it does not create missing cross-dashboard relationships.
The role classifier also does not solve bundle assembly by itself: independent
role scores selected plausible same-domain sources but missed required
cross-domain context. The separate DocumentDB trial reached 100% related-source
recall because its fixture supplied explicit deployment, incident, runbook, and
ownership relationships around the CloudWatch anchor. The generalized pattern
is therefore not “ask Jev to rank harder.” It is:

1. preserve human-approved anchors;
2. make card-declared cross-context relationships explicit and traversable;
3. let adapters return a bounded graph neighborhood, not just lexical search;
4. use Jev for typed role and relevance judgments over that neighborhood;
5. assemble bundles with coverage constraints, not a single global threshold.

The result does not justify promoting the current role-aware policy. It justifies
testing an explicit relationship-expansion policy next.

The result is a hypothesis test, not a production threshold. Anchor-aware ranking
is directionally better but not complete, so the next product experiment should
be a small internal bundle planner: preserve card anchors, expand through
explicit adapter relationships, and ask Jev for role judgments in one bounded
request. The gap is in relationship expansion and constrained assembly—not
something Jev should be expected to invent from an underspecified graph.

One experimental caveat: the ablation keeps all candidate metadata in one Jev
state and asks the global questions to ignore the anchor/context fields. That is
an efficient directional comparison, not a perfectly isolated causal estimate;
the next benchmark should use separate request states if the result becomes a
release gate.
