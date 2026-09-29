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

Cards without `follow_up_guidance` retain the existing single-evaluation
outcome and delivery behavior. They receive only the additive workflow
metadata. This is intentional: a multi-step handoff is opt-in through the
human-authored card, while source retrieval and action execution remain outside
SignalWeave.

The live proof for this contract is in
`evaluations/northstar_multistep_trial.py` and
`examples/northstar-multistep-trial.json`. It uses live Jev over the same local
Northstar rows as the single-step historical replay; expected dispositions stay
outside the Jev state.
