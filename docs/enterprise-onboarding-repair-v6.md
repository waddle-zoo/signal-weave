# Shadow onboarding is not production certification

Status: prospective; the six-company acceptance gate is still unproven.

The v5 probe demonstrated the intent-validator repair: the fresh free-form
card's current preview returned `ignore` with Jev support 0.83. But onboarding
stopped after synthetic owner review passed because the agent interpreted
approval as requiring unavailable historical certification. The trial remains
failed: no later treatment observations ran. The preview is not a substitute.

The guide and approval tool already permit owner-authorized, unassessed shadow
evaluation. Global MCP guidance and the research transport must distinguish that
path from certified unattended use. Both trial arms now receive explicit
delivery-disabled shadow framing. No production authorization, health, scope,
simulation, confidence or certification check is waived; no historical cases
are invented. Synthetic owner approval is not actual human authorization.

Retest retail with fresh notes/cards, the same public sources, policies, private
labels, three later periods and Luna baseline. Freeze code and keep all failures.
Cap live Jev at 32 attempts, SDK retries disabled. Passing requires complete
onboarding and three correct native/final outcomes, recipients, required numbers
and provenance. Narrative review follows only if structured gates pass. The
full six-company acceptance gate and comparative-value claim remain separate.

```sh
python -m evaluations.enterprise_onboarding_journeys --live \
  --company-index 0 --jev-budget 32 \
  --jev-key-file /secure/path/to/key \
  --output artifacts/enterprise-onboarding-repair-v6-probe-01
```

Do not report blocked periods as cost savings. Repeated known-family repair
probes are not independent holdouts or proof that real users can self-onboard.

## Retail probe result

The structured gate passed under revision `7703b0d`: both arms completed setup
and all three later observations. Both returned 3/3 correct final outcomes,
recipients, required numeric claims and provenance. Native SignalWeave decisions
were also 3/3 correct; the reporting agent changed none of their outcomes.
The run used 17 Jev attempts and 10 Luna invocations including two owner reviews,
with no provider errors or budget censoring. All eight planned records and
request/response counts were validated by the complete exporter.

| Measurement | Luna BI | Luna + SignalWeave |
| --- | ---: | ---: |
| Setup, seconds | 59.79 | 97.45 |
| Three later full reports, seconds | 70.78 | 79.10 |
| Later report median, seconds | 24.49 | 25.20 |
| Source reads, setup plus reports | 10 | 20 |

This is not a speed or cost win for the full reporting workflow. In this probe
Jev supplied correct reusable decisions, but both arms still invoked Luna for
every final report. A policy that skips quiet-period report generation might
save work; this run did not test that comparison and does not establish it.

Evidence: [execution audit](evidence/enterprise-onboarding-repair-v6-probe-01/execution-audit.json),
[structured results](evidence/enterprise-onboarding-repair-v6-probe-01/results.json),
[full report](evidence/enterprise-onboarding-repair-v6-probe-01/report.json.gz),
and [trace](evidence/enterprise-onboarding-repair-v6-probe-01/trace.jsonl.gz).
An independent internal narrative review and the other five companies remain
separate gates. See the [staged cohort protocol](enterprise-onboarding-repair-v6-cohort.md).

### Narrative qualification

The [internal blinded review](evidence/enterprise-onboarding-repair-v6-probe-01/narrative-review.md)
found five supported narratives and one materially qualified narrative. The
SignalWeave-assisted material-decline report overstated company-wide population
completeness despite correct numbers and routing; the source contract did not
establish that coverage. The reviewer judged this material to alert trust.
The shared delivery-disabled execution context supports its no-notification
statement, but does not resolve the population claim. Therefore the retail
**structured** gate passes; the overall narrative gate does not yet pass.
No output was rewritten to hide this finding, and the running cohort remains
frozen while the separate reporting problem is investigated.
