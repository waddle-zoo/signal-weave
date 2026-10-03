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

For a `fixed` card, an explicitly supplied source is a human anchor, not merely
the top result on the current search page. Review revalidates that anchor through
the adapter's authorization boundary and keeps it visible when pagination or a
bounded relevance pool would otherwise omit it. This authorization check does
not fetch the source data. The later workflow evaluation resolves the source
again and fails closed if it is stale, unavailable, unauthorized, or over budget.
Cards in `expand` mode still require review when bounded discovery leaves their
dynamic context incomplete.

### Resolve a source-selection ambiguity

Two resources can legitimately share a title. A warning is not a reason to change
the catalog or pretend both mean the same thing. Inspect their definitions and
populations, ask the owner which sources belong in this investigation, and create
a `fixed` card with `investigation_mode="none"` using those exact source refs.
Multiple selected sources are supported; dynamic retrieval is deliberately not
covered by this confirmation.

1. Call `review_insight_card(card_id)` and inspect its candidates and blockers.
2. Simulate the card and show the owner the selected scope, excluded alternatives,
   calculations, uncertainties and routes.
3. After explicit owner approval, call `approve_insight_card` with that review's
   `source_selection_fingerprint` and a `source_selection_reason` explaining the
   chosen definitions/populations and excluded alternatives.

This resolves only `definition-conflict` (the title-collision warning) and
`candidate-selection-review` (omitted Jev recommendations). It does not waive
health, authorization, missing intent/policy or incomplete dynamic scope.
The fingerprint binds the exact policy, source parameters, delivery destinations,
principal, and visible catalog. Changes require a fresh review and confirmation.
It is an integrity check, not a credential or evidence that an LLM actually asked
a human: your host must enforce its human-approval policy. The stored approval
review records the reason and confirmed blocker codes; it is excluded from Jev's
execution state. Ordinary correction feedback remains append-only and does not
silently resolve or approve anything.

Source freshness and authorization are checked again during execution. This
transition check does not yet provide continuous semantic-drift recertification.

For a tenant-level view across the bootstrap report, stored cards, workflow
certifications, retrieval certification, installed adapters, and configured
company context provider, call `get_enterprise_readiness`. It returns explicit
open gates and only reports `ready_for_shadow` when the minimum evidence exists;
it never means production delivery is safe by itself.

The readiness index compares each card's current version with the version
covered by its latest workflow certification. If the card changed after the
certification, the card is blocked until its labeled cases are replayed. This
prevents an old green report from being mistaken for proof about a newer card.

## 2. Certify a card/workflow

For a single current-data check, agents do not need to reconstruct source
snapshots. Use one case with `capture_current_sources: true`, an `id`, and the
owner's `expected_outcome` (plus explicit expected routes). The server fetches
the stored card's selected sources through the normal authorization boundary,
preserving source keys, parameters and tenant contracts. This can execute queries;
obtain the owner's read/query permission first. At most one current capture is
allowed per evaluation call. Never present it as several historical periods.

Alternatively supply `resources` as the exact normalized snapshot objects from
inspection or preview, including their contracts—not resource-name strings.
Explicit `resources: []` tests missing sources. These two input modes are mutually
exclusive, and every case is validated before current data is fetched or Jev called.
Labels remain outside Jev's state in both paths. A current check alone does not
cover the full policy or authorize delivery.

### Test onboarding, not just the prose

Retrieval labels distinguish what **must** be fetched from what **may** be fetched.
By default, `expected_retrieval_refs` is an exact set. When extra corroborating
context is legitimate, supply `allowed_retrieval_refs` as a bounded superset.
Required refs must still be present; unlisted refs still fail acceptance. Retrieval
recall measures required coverage, and precision measures permitted retrieval.
For example, require `metrics|daily` and permit both `metrics|daily` and
`changes|calendar`: fetching the calendar is neither mandatory nor a failure.
Define these owner labels before observing the model's selection, not to excuse
whatever it happened to fetch. They never grant access, change the card's source
selection or enter Jev's state. Admission-policy version 5 records these semantics;
older certifications must be rerun for current readiness.

Like expected outcomes and recipients, retrieval labels are caller-supplied.
The evaluator does not independently establish their correctness or prove a human
authored them. An agent can make a weak test by supplying weak labels. Keep owner
fixtures independently reviewed and immutable in your host workflow. Reports
retain both retrieval sets and their label digest for inspection; certification
does not approve a draft card or authorize delivery. Old reports retain their
historical status: use `get_enterprise_readiness`, not an old status alone, to
check current compatibility.

A successful preview means the engine ran. It does not mean it followed the
owner's rule. Likewise, approving a card authorizes it; that alone is not evidence
of correct behavior. The recommended onboarding path is:

1. Inspect the selected source exports and establish the population, comparison
   basis, completeness and source meanings needed by this investigation. Ask the
   owner about missing definitions; never manufacture coverage from a list of rows.
2. Have the owner supply expected outcomes for setup examples: an actionable
   change, a quiet situation, and missing or conflicting evidence. Cover additional
   intended routes too. These can be historical or explicitly synthetic examples;
   keep later evaluation periods out of this correction loop.
3. Call `evaluate_card_workflow` with `acceptance_outcomes` listing the intended
   outcomes. Each case needs explicit `expected_delivery_method_keys` and
   `expected_delivery_destinations` (a method-key-to-exact-endpoint object; `{}`
   means no delivery). Supply evidence and retrieval labels for the assertions
   being tested. Do not derive labels from Jev's response.
4. Inspect any failed case's `evidence_plan`, `workflow`, and failure reasons.
   A required question that cannot be answered is not automatically a contradiction.
   Fix the source contract, ask the owner to clarify the rule, or mark a detail
   advisory **only if it is genuinely not a prerequisite**. Do not lower confidence
   thresholds or rewrite expected outcomes merely to get a passing test.
5. After a passing acceptance replay and explicit owner approval, call
   `approve_insight_card(card_id, workflow_report_id=certification_report_id)`.

Acceptance is strict about tested outcomes, recipients and endpoint strings.
Coverage follows the owner's declared outcomes, not a fixed alert taxonomy:
an always-investigate policy can legitimately route quiet situations for review.
The evaluator cannot infer whether those declared outcomes cover the entire
business policy; the owner must review that coverage as well as the labels.
It binds the saved report to the executable card, source parameters, plan and
destinations. Changing those requires another replay, including same-version
edits. No message is delivered by the evaluator. Owner labels are used for scoring
only, never sent as Jev instructions or evidence.

The low-level approval call remains available without a report for caller-managed
review, but reports `workflow_acceptance.status="unassessed"`. Enterprise readiness
does not treat that or a partial diagnostic replay as successful onboarding.
A passing setup set is still not proof of generalization: follow it with an
independent holdout and shadow monitoring. Neither the service nor a model review
authenticates the owner's labels or guarantees upstream data completeness.
This replay evaluates the supplied snapshots. It does not certify live connector
fetches or dynamic catalog retrieval; validate those through the existing adapter
bootstrap, retrieval evaluation and live shadow tools separately.

Keep `watch_for` specific to the owner's required business conditions. Each item
is assessed on every run and unresolved required evidence can block notification.
Do not copy a general analysis checklist into it: an inapplicable decomposition
can turn an otherwise answerable investigation into an incomplete one. Reporting
preferences belong in `decision_guidance`; test the draft on both actionable and
quiet snapshots before approval.

Separate setup from recurring investigation. "What counts as material?" is a
setup question for the owner; its answer belongs in `decision_guidance`.
"Did the approved materiality condition occur, and what evidence explains it?"
is a recurring question. Free-form wording remains supported, including changing
ownership, workflow state and other non-numeric evidence. Nothing is silently
rewritten or waived by the service.

Check the actual `delivery_methods` entries against the owner's words. A rule
that says investigate with Operations needs an `investigate` entry for that
destination; a `notify` entry is not interchangeable. Prose does not create
missing routes. Simulate each intended disposition, including quiet and missing
evidence, rather than approving solely because a draft was saved successfully.
The authoring MCP schemas expose these distinctions directly to local agents.

Jev can return `insufficient_data` for semantic gaps even when every source is
reachable, such as an undefined population or comparison basis. This reserved
outcome does not invent a recipient: delivery still uses only the card's configured
methods. A confident judgment is not a substitute for evidence or certification.

MCP simulation and evaluation responses include active card policy, source
resources, the compiled plan and the complete result. They omit repeated
authoring reviews/corrections and the receipt's duplicate result. Full audit data
remains available through `get_insight_card` and `get_decision_receipt` and is
unchanged in storage; consumers should read the top-level evaluation `result`.
Authoring responses likewise return active card policy without repeated history:
the current review and compiled plan remain at top level where applicable.
Optional caller context exposes the `ContextSnapshot` schema (`provider`,
`version`, and optional facts); it is not an arbitrary scheduling object, and
caller-supplied context is always marked unverified.

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
95% evidence recall, 95% retrieval recall, zero unsafe outcomes, zero runtime
errors, exact delivery-method keys on every successfully executed case with
explicit delivery labels, and at least one labeled case. A report that misses a threshold is
`shadow`, not `approved`; a runtime failure or empty evaluation set is
`blocked`.

`expected_delivery_method_keys: []` explicitly requires no route. Omitting that
field leaves delivery unassessed/unconstrained; its legacy `delivery_exact=true`
value must not be counted as evidence of correct recipients. Supply labels for
every intended outcome, including investigate and insufficient_data, before
claiming routing quality. Correct outcome or an allowed conservative disposition
cannot waive a labeled delivery mismatch, even with relaxed numeric thresholds.
These labels check method keys, not independent correctness of endpoint contents
or actual delivery. The existing `unsafe_action_rate` is outcome-only; it does not
include recipient errors or causal/explanation errors.

Promotion policy version 3 fixes an earlier omission: delivery mismatches were
recorded but did not prevent an approved report. Version-2 and older reports stay
readable but are stale for readiness. Re-evaluate the unchanged owner-labeled
cases; do not edit historical report versions to make them current. Certification
does not itself approve a card or authenticate the owner's labels.

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

Certification reports are durable in the configured JSON or SQLite store and
can be retrieved through `get_certification_report` and
`list_certification_reports`. Reports include the evaluated card version,
tenant scope, dataset IDs, source/context digests, Jev request counters, and the
owner-label digest. A later report therefore cannot silently be treated as proof
for a different tenant, card, or snapshot.

The repository also includes a generalized Jev-only synthetic trial with
disjoint train/holdout/adversarial partitions and a separate adversarial
reviewer; see [`generalized-readiness-trial.md`](generalized-readiness-trial.md).
That trial proves the contracts compose over several BI and data-platform
shapes. It is not proof of universal enterprise readiness. A deployment still
needs customer-owned labels, real permission-aware catalog search, source
freshness/lineage coverage, query-cost telemetry, and live shadow traces before
production push.
