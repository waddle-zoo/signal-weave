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

## v5 probe results

Status: complete export, but the treatment stage failed and this is not a pass.
The eight-record denominator was retained: the Luna BI baseline completed
onboarding and all three monitoring periods; treatment onboarding did not
complete, so its three later monitoring results are unassessed rather than
failed business decisions.

| arm | onboarding | monitoring complete | final exact | final outcome | final recipients | provenance |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Luna BI baseline | 1/1 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| Luna + SignalWeave Jev | 0/1 | 0/3 | unassessed | unassessed | unassessed | unassessed |

The baseline took 32.085 seconds cold and 79.447 seconds across warm monitoring,
with a 28.775-second warm median. Treatment onboarding took 88.641 seconds;
there was no completed treatment monitoring run. The export retained four
treatment runtime failures and three safety-unassessed monitoring episodes.

The treatment preview correctly represented the quiet-period `ignore` result.
The acceptance stage nevertheless rejected the current-only test because it did
not provide independent historical certification. The author reasonably refused
to treat that preview as unattended certification. A simulated owner review then
approved the policy binding, but setup still did not complete; approval does not
convert the failed acceptance stage into a pass.

The archive records 18 observed model invocations: 7 Luna invocations (including
two owner-review invocations) and 11 Jev invocations. Jev recorded one failed
attempt and one unknown-usage attempt. The report's `api_attempts=11` field is
the Jev counter, not the total model-invocation count. Known usage is
illustrative API-equivalent accounting, not subscription pricing.

## Read-only control critique

The frozen run exposed a wording conflict, not a reason to waive runtime checks.
Preview itself worked. The ambiguity is that `approve_insight_card` can be read
as permitting later shadow observations without certification, while the global
MCP text and Codex transport phrase “only after acceptance” describe a stricter
sequence. The corrected contract should state the states explicitly: preview,
simulation, review, and owner-review may operate in shadow before certification;
approval must not be presented as certification merely because later shadow
observations are technically possible. The distinction must be identical in the
guide, global MCP instructions, and transport instructions.

The shared `COMMON_SYSTEM` delivery-disabled shadow setting applies to both arms,
and the Codex owner review authorizes trial shadow only. Production runtime
currently permits approved-but-uncertified evaluation; that behavior must not be
described as a hard runtime certification gate. Safe-use instructions should
require full acceptance before making claims or performing actual unattended
delivery. Caller-owned delivery was never exercised, so production MCP explicit
owner authorization without a certified report remains unassessed. No runtime
checks were waived in this interpretation.

This v5 result is not a pass. A new v6 run is required after the wording fix to
demonstrate the safe-use boundary: shadow observations may be previewed, but
claims and actual unattended delivery wait for full acceptance.
