# Free-form policy regression

Status: prospective. The v4 retail probe completed onboarding but failed the
native decision gate (one of three outcomes/routes correct). This is not a
product success, even though every episode returned a report.

Its trace exposed a production contract contradiction: the first authored card
had the complete decision rule and no extra watch/question. Onboarding emitted
`intent-detail-required` anyway, directing the agent to add a watch or question.
The replacement card added a required population/completeness assessment, which
later blocked a quiet period. The agent was following the product's instructions.

## Change

Nonempty `decision_guidance` satisfies the structural intent-presence check, just
as a watch item or question does. This does not validate that the rule is correct:
owner review, source authorization, scope confirmation, confidence controls,
preview and acceptance requirements remain intact. Cards with no rule, watch or
question still require clarification. No required assessment is removed from an
authored card, and no card is repaired automatically or for a particular company.

## Frozen retest

Use the same retail company and every later period, both arms, unchanged labels,
owner answers and data. Start fresh; do not reuse or edit the failed card. Preserve
all attempts. Cap live Jev at 32 attempts, with SDK retries disabled. The expected
result remains complete onboarding plus all three native and final decisions,
recipients, required numerical claims and provenance correct. Narrative review
still applies. Passing this probe does not satisfy the full six-company gate.

```sh
python -m evaluations.enterprise_onboarding_journeys --live \
  --company-index 0 --jev-budget 32 \
  --jev-key-file /secure/path/to/key \
  --output artifacts/enterprise-onboarding-repair-v5-probe-01
```

This is a targeted known-family regression, not a new holdout, a causal estimate
of one patch's effect, or real-user/provider proof. Compare costs only for completed
matched work and keep setup separate from recurring analysis. No mid-run edits,
lowered confidence floor, private-label guidance or manual card repair.
