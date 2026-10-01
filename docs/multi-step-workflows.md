# Multi-step workflows

SignalWeave does not become a workflow runner. It gives a caller-owned agent a
small typed handoff after each Jev judgment so the agent knows what to do next
without turning the card into a hidden prompt or allowing an early notification.

The human-authored card stays free-form:

- `what_to_watch` describes the business signal or operating question.
- `why_watch` describes the intended decision.
- `watch_for` and `questions` add useful focus without requiring a schema for
  every company's vocabulary.
- `decision_guidance` defines the policy the team is willing to automate.
- `follow_up_guidance` tells a caller-owned agent what to inspect when the first
  evidence is not enough.

## The handoff contract

Every `InsightResult` now has an additive `workflow` field:

| Outcome | Handoff action | Meaning |
| --- | --- | --- |
| `ignore` | `suppress` | Record the result; no delivery is required. |
| `investigate` with guidance | `retrieve_evidence` | The agent may gather the named diagnostic context and submit it back for re-evaluation. |
| `investigate` without guidance and a configured route | `deliver` | Preserve the existing single-step delivery behavior. |
| `investigate` without guidance or a configured route | `request_review` | The system refuses to invent the next step. |
| `insufficient_data` | `repair_source` | Fix or validate the source, then re-evaluate. |
| `notify` / `escalate` | `deliver` | The caller may deliver to the card's configured destinations. |

The handoff is derived from the final Jev outcome and safety gates. Jev does
not get to invent destinations, source keys, or arbitrary actions. The caller
must still own source access, tool execution, Slack/email/ticketing side
effects, and any remediation.

## Evidence plan

Each result and workflow handoff also carries an `evidence_plan`. SignalWeave
compiles it from the card's approved sources, `questions`, and `watch_for`
items. A slot includes:

- a stable key and role (`primary`, `diagnostic`, `question`, `watch`, `quality`,
  or `ownership`);
- the concrete question the agent should answer;
- authorized source keys and full source references, including adapter parameters;
- whether the slot is required; and
- its current status: `pending`, `fulfilled`, `conflicting`, or `unavailable`.

This makes the agent's retrieval work inspectable and bounded. The agent does
not need to turn a prose instruction into an investigation from scratch. It
executes tools for the pending slots and returns facts tagged with the slot key
when it can. SignalWeave resolves those facts against the plan and carries the
missing or conflicting slots into the next handoff. A source adapter still owns
the actual query and permission boundary; SignalWeave does not generate
arbitrary SQL or grant access to a source.

Each evaluated observation also receives an `evidence_finding` when the Jev
provider returns one. Its typed role is `driver`, `corroborates`, `diagnostic`,
`contradicts`, `quality`, `unrelated`, or `unknown`, with a probability and optional
`suggested_role` when the classification is below the advisory threshold. The
advisory threshold is separate from the threshold used to permit an automatic
outcome; showing a weighted lead does not authorize delivery.
These are ranked explanations for the current evidence, not causal proof. They
are available on ordinary cards as well as bounded investigations, so a caller
can show why a push happened without making the extra-source selector part of
the core decision.

For example, a card asking why online sales fell can produce slots for the
sales source, channel breakdown, acquisition change, purchase conversion, and
ownership context. The final evidence bundle can therefore show which slots
were fulfilled and which remain uncertain, rather than presenting a single
opaque “investigate” instruction.

## Caller-owned loop

The intended sequence is:

1. Call `evaluate_insight_card` with the approved card and current source data.
2. Inspect `result.workflow`.
3. If the action is `retrieve_evidence`, use the caller's authorized tools to
   inspect the sources named by `required_source_keys` and the free-form
   `instructions`.
4. Create a versioned `ContextSnapshot` containing only the evidence the agent
   is authorized to return, including provenance for each fact.
5. Call `evaluate_insight_card` again with that context. Pass the first
   receipt's `parent_receipt_id` and a stable `workflow_step_key` such as
   `investigate` when using the MCP server.
6. Deliver only when the new handoff action is `deliver`.

The caller should use `workflow.evidence_plan.missing_slot_keys` to decide
which authorized tools to run. A fact can set `slot_key` to the corresponding
plan key so SignalWeave can show exactly which request it fulfilled.

If the second result is still `retrieve_evidence`, the agent can continue the
bounded loop. If it is `repair_source` or `request_review`, no leadership
delivery is implied. A parent receipt mismatch is rejected before evaluation.

## Northstar example

For “online sales fell; explain why and notify Analytics + Data Trust before
Leadership” the card can say:

> Inspect checkout failures, payment deployments, traffic, campaign changes,
> inventory, and ownership context. Return authorized evidence with time
> relationship and provenance, then re-evaluate before leadership delivery. Do
> not treat one correlated signal as proof of causation.

The first evaluation can return:

```json
{
  "outcome": "investigate",
  "workflow": {
    "action": "retrieve_evidence",
    "status": "pending",
    "step_key": "investigate"
  }
}
```

After the agent returns evidence that checkout failures rose after a payment
deployment, the same card can return `notify` with a `deliver` handoff and the
configured leadership destination. If the returned evidence instead shows a
finance posting lag or remains inconclusive, the result stays `investigate`;
SignalWeave does not manufacture certainty.

## Compatibility and boundaries

Evidence admission policy version **1** is a breaking change. Required semantic
slots always gate automatic `notify` and `escalate`, whether or not the card has
`follow_up_guidance`. That prose describes follow-up after an inconclusive result;
adding or removing it must not change evidence admission. Multi-step handoff
instructions remain opt-in, and source retrieval and action execution remain
outside SignalWeave.

Cards declare `evidence_requirements: dict[str, StrictBool]`, defaulting to `{}`.
Only exact keys for existing, one-based `question:N` and `watch:N` slots are
accepted. Unspecified slots remain required. For example,
`{"question:2": false}` makes only the second question advisory. Values must be
JSON booleans, not strings or numbers. An advisory unknown remains visible in the
evidence plan and missing-slot list but does not block admission. `false` is an
unconditional advisory designation, not "required when applicable" or a
conditional policy. Neither prose such as "when supported" nor a model judgment
silently waives a requirement. Required-source and comparison checks cannot be
waived through this map; other safety and confidence gates still apply.

Review which slots are core decision evidence and which are advisory before
migrating existing cards. Policy-map changes and question/watch edits or reordering
require a new card version, fresh owner review/approval, and recertification over
owner-labeled snapshots. The positional keys belong to that reviewed card version;
do not carry a waiver onto a different question merely because its index matches.
Even unchanged cards without follow-up prose may now conservatively withhold an
automatic route when required evidence is unresolved.

New `CardEvaluationReport` objects emitted by `CardWorkflowEvaluator` record
`evidence_admission_policy_version=1`. Reports lacking the field load as legacy
version `0`; they remain readable audit evidence, not current certification.
Readiness must require the current policy version in addition to the existing
card-version, approval, and certification gates. Re-run certification rather than
relabeling an old green report. Retain old reports, receipts, and reviews unchanged;
the policy version is compatibility metadata, not proof of semantic correctness.

The historical live trial for the earlier handoff contract is in
`evaluations/northstar_multistep_trial.py` and
`examples/northstar-multistep-trial.json`. It uses live Jev over the same local
Northstar rows as the single-step historical replay; expected dispositions stay
outside the Jev state. Those retained results do not certify policy version 1.
