# Bootstrap and certification

SignalWeave's enterprise readiness path has three separate checks:

1. bootstrap the source boundary;
2. certify the card/workflow over owner-labeled snapshots; and
3. certify retrieval over owner-labeled asset references.

This is intentionally a library and MCP contract. SignalWeave does not own the
company UI, scheduler, workflow engine, knowledge graph, or delivery sink.

## 1. Bootstrap the source boundary

Use the MCP tool `assess_bootstrap` or `BootstrapService` with a deployment-owned
manifest. The probe goal should be a real phrase a card author would use, not a
synthetic keyword.

```json
{
  "name": "Northstar analytics boundary",
  "tenant_id": "northstar",
  "adapters": [
    {
      "adapter": "superset",
      "probe_goal": "growth conversion and acquisition health",
      "required_capabilities": [
        "catalog",
        "search",
        "inspect",
        "tenant_scope",
        "freshness",
        "lineage"
      ],
      "minimum_resources": 1
    }
  ]
}
```

The result is `ready`, `needs_review`, or `blocked`. A native bounded adapter
search is required when `search` is in the manifest. A local full-catalog scan
is reported as a warning and cannot be used as evidence of large-catalog
readiness. The check also verifies that a returned sample is authorized for the
manifest tenant and can be inspected through the adapter boundary.

Bootstrap does not prove that a card is semantically correct. It proves that
the deployment can provide the bounded, authorized inputs needed to test one.

## 2. Certify a card/workflow

Use `CardWorkflowEvaluator` directly or the MCP tool `evaluate_card_workflow`.
The MCP form takes a stored `card_id` and cases without repeating the card
policy:

```json
{
  "card_id": "card-growth-pulse",
  "cases": [
    {
      "id": "2026-09-01-regression",
      "resources": [
        {
          "source_key": "growth-dashboard",
          "adapter": "superset",
          "resource": "dashboard:42",
          "title": "Growth overview",
          "observations": [],
          "evidence": []
        }
      ],
      "expected_outcome": "notify",
      "allowed_outcomes": ["notify", "investigate"],
      "expected_delivery_method_keys": ["growth-leadership"],
      "required_evidence_source_keys": ["growth-dashboard"],
      "expected_retrieval_refs": ["superset|dashboard:42"],
      "tags": ["regression", "historical-holdout"]
    }
  ]
}
```

Owner labels are used only after the Jev run to score it. They are never added
to the card state or provider request, which prevents a benchmark from leaking
the answer into the judgment. `allowed_outcomes` is explicit because a
conservative `investigate` result may be safe even when the exact expected
outcome was `notify`.

The evaluator reports:

- exact outcome and delivery-method correctness;
- evidence recall for source keys the owner says are required;
- retrieval precision/recall for resources materialized in the run;
- unsafe-action and runtime-error rates; and
- latency and evaluator identity for every case.

Default promotion thresholds are deliberately strict: 95% outcome accuracy,
95% evidence recall, 95% retrieval recall, zero unsafe actions, zero runtime
errors, and at least one labeled case. A report that misses a threshold is
`shadow`, not `approved`; a runtime failure or empty evaluation set is
`blocked`.

## 3. Measure retrieval before blaming the decision

`RetrievalQualityEvaluator` runs goals through the same
`InsightAuthoringService.discover` path used during onboarding. Each case keeps
its expected resource refs outside Jev and reports:

- candidate recall: did the adapter-owned bounded pool contain every labeled
  relevant resource?
- recommended precision and recall: did Jev mark the right resources as
  recommended?
- reciprocal rank and no-match accuracy; and
- latency, evaluator, and errors.

This decomposition matters at enterprise scale. If candidate recall is low, fix
the source adapter's search index, aliases, lineage, or graph relationships.
If candidate recall is high but recommended recall is low, inspect the Jev
question and candidate metadata. If both are high but outcome accuracy is low,
inspect the card's decision guidance, materialized observations, or safety
policy.

## What this does not certify yet

These checks are the promotion seam, not proof of universal enterprise
readiness. A deployment still needs customer-owned time-split holdouts, native
permission-aware catalog search, source freshness/lineage coverage, query-cost
telemetry, and shadow traces from real workflows. SignalWeave should remain
shadow-only until those labels exist and the report is approved for that card
version and source boundary.
