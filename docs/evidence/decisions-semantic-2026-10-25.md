# Decisions and shared metric meaning

Working study, October 25. [Protocol](../../evaluations/protocols/decisions-semantic-2026-10-25.json).
This tests existing cards, reviewed context and source exports—not a new semantic
engine. The frontier agent discovers definitions and writes the analysis;
OpenAI Decisions applies the saved policy.

## Installation and actual runtime

The published Apple Silicon `v0.2.0rc5` passed isolated live OpenAI setup,
normal 11-tool MCP startup, a synthetic `notify`, and receipt replay after
restart without Jev credentials. That seeded-card check does not prove onboarding.

The semantic journeys use a **local native candidate**, not that published
download. Its production fingerprint is
`d177942409f2c41d4441ca61824b5d00adf15e5ffc402dbc8a0d6d74d3e27e1a`;
executable SHA-256 is
`dc55afe4ab9692bf87ca141822ec2c214a018a1677bd0ac41e8cb9514d31b4c4`.
It was built from `f712485`, still carrying the `0.2.0rc5` candidate version.
Each run verifies the executable and complete adjacent runtime, and freezes
research hashes. Research-only edits do not change the production fingerprint.

The complete candidate archive passed install, native setup/MCP initialization,
uninstall with data retained, reinstall, and purge in disposable homes. Its
scripted terminal wizard also passed. A separate isolated person completed
interactive OpenAI-key setup, company-source connection, **actual Codex CLI
registration**, bundled skill installation and live source health.
No personal agent configuration was changed. This is scripted process proof,
not a novice-human usability panel or a newly published download.

Two setup-driver mistakes are retained: a non-default manifest tenant was
supplied to the default-local wizard, then a health helper was pointed at the
person's home rather than its configured `.signalweave` home. Neither counts
as successful setup or a provider failure. The native PTY test also initially
omitted `_internal`; the corrected test packages the complete runtime and is
now included in the native-release gate.

## Companies and fair comparison

Three SQLite companies model retail, subscription software and a marketplace.
Each has six identically titled Revenue exports with different net/gross/GMV/
run-rate/draft/retired meanings, source-owned revisions, currencies, populations
and period definitions. Actual SQL reads seeded ledger rows; independent Decimal
calculations and hand controls check amounts, FX, fee-versus-GMV scope and
tax-inclusive field conventions.

These use the existing normalized MCP bridge, **not live dbt, Cube or LookML
integrations**. Each native home starts without cards. A Luna Codex analyst
discovers and reads sources, saves/reviews a shared definition, pins it to a card
and approves under explicit fictional-owner technical delegation. That is not
evidence of real human consent or usability.

Both arms retain all company source tools, source definitions and the same
reviewed card/context in searchable notes. Treatment adds the actual native MCP
and its workflow skill. Readers use new run keys. Marketplace uses authenticated
loopback HTTP MCP; the other companies use stdio.

The unchanged-snapshot cohort requests ten equivalent prompt pairs per company.
The handoff contains the original figures in both arms' notes. Fresh source
reads are audited, but agreement alone does not prove independent derivation
or stale-note robustness. A separate forward-change stage updates the ledger
after onboarding while retaining old notes and the same definition/card. It
checks new values and the now-non-alerting policy without exposing the oracle.

## Results and retained stops

The primary cohorts stopped with **53 of 60 planned canonical readers** completed,
plus eight gross/conflict agent reports. All 53 canonical readers reported the
correct amounts, metric, currency and periods; one failed the exact revision-field
format. Both arms fetched current evidence. This is not a completed 60-reader
benchmark or a superiority result.

| Company | Ordinary context, strict checks | SignalWeave, strict checks | Median reader seconds, ordinary / SignalWeave |
| --- | ---: | ---: | ---: |
| Retail | 10/10 | 10/10 | 28.86 / 27.27 |
| SaaS, interrupted cohort | 6/7 | 6/6 | 29.95 / 33.90 |
| Marketplace, authenticated HTTP | 10/10 | 10/10 | 28.73 / 29.40 |

These timings exclude onboarding and are descriptive, not a significant speed
advantage. Fresh onboarding took 166.92, 110.87 and 169.67 seconds respectively,
with 20, 21 and 21 agent tool calls. Both gross contrasts in retail and marketplace
selected the correct separate metric and did not apply the net-revenue policy.

| Attempt | What happened |
| --- | --- |
| Canary v1, published rc5 | Fresh onboarding chose correct source/amounts; reporter falsely required decomposition for valid scalar evidence. Stopped after one baseline reader; no completed pair. |
| Canary v2, first candidate | Four readers passed checks. Baseline 29.75/26.00 seconds; treatment 32.86/52.28 seconds. Eight policy contrasts completed; conflict labels/routes varied. No speed or deterministic-label win. |
| Canary v3, current candidate | Four canonical readers passed. Gross baseline returned correct facts but flagged reversal treatment requested by the test and not defined by the source. Resolved-status gate failed. Retained without rescoring; prospective questions use source-declared gross meaning, and independent prose review assesses material caveats separately. |
| Primary SaaS v1 | Stopped at reader 13: baseline put `saas.net_revenue r3; Finance reviewed definition revision 2` in the exact revision field. Figures, meaning, policy and human brief were correct. Independent review passed the human answer; structured-field failure remains, with seven readers and later contrasts unexecuted. |
| Primary retail / marketplace v1 | Each completed 20 canonical readers and four semantic contrasts. Treatment's conflict briefs correctly separated r3/r4 and attributed correct amounts, but described both revisions in the exact source-revision field. Strict sensitivity gates failed; later direct policy/edit checks were not executed in these original runs. |
| Forward SaaS v1 | Both first readers fetched the updated USD 18,070.59 versus USD 17,716.12 (+2%) rather than repeating onboarding's USD 14,817.88. Baseline chose ignore. Native Decisions also chose ignore on the new snapshot, but the treatment agent investigated the unexplained same-period restatement after reading the older receipt. Outcome/recipient gate failed; the remaining pair and contrasts were not run. |

One independent reviewer judged that forward investigation reasonable: the fixture
changed a closed month's values without a source-owned publication revision,
supersession record or correction explanation. It does not prove a SignalWeave
policy error or justify forcing the agent to ignore contradictory receipts.
The failed expected-ignore gate remains unchanged. The next forward trial needs
inspectable publication/correction evidence in both arms before asserting that
the new snapshot resolves the discrepancy.
The other reviewer agreed with the figures and discrepancy but viewed the
agent's investigation route as beyond the intended within-snapshot threshold
policy. This disagreement is not a consensus pass: the native judgment and the
agent's additional cross-snapshot recommendation answer different questions.

## Separate live saved-policy supplement

The original runs stopped before their planned policy/edit phases. A separate
supplement cloned their actual agent-authored homes and exercised **24 fresh
native OpenAI Decisions evaluations**, not additional frontier-agent reports:
two each of quiet, decline, incomplete coverage and conflicting definitions in
each company. All 24 passed the pre-existing outcome/route/provider/shadow
checks, with no receipt replays. All three required-definition edits produced a
new draft, deferred policy with no outcome/routes and retained source evidence.

Quiet cases were all `ignore`; qualifying declines all `notify` Finance.
Missing data and definition conflicts remained review handoffs. SaaS conflict
repeats varied between `investigate` and `insufficient_data`; this is **not**
deterministic-label proof. No messages were sent, and provider cost is unmeasured.

The cloned local bridge endpoints have new identities. A scripted test-source
operator explicitly rebound the unchanged reviewed definitions and re-reviewed/
approved the cards through public MCP tools before inference. This is an
operator-assisted connector migration, not fresh onboarding or a bypass.
Earlier supplement attempts remain retained: two correctly deferred on changed
source identity; one approval attempt used descriptive rather than exact scope
confirmations and was rejected. None of those attempts reached provider judgment.
The completed supplement is in `policy-supplement-v4`, separate from the
unchanged original reports and their failures.

Independent review covered all 20 retail canonical briefs and four contrasts,
and all 20 marketplace canonical briefs plus two gross contrasts. It found no
material numerical, causal or claimed-send errors in those reviewed sets.
Retail review flagged omitted synthetic-fixture disclosure in 15/20 briefs and
two misleadingly rendered internal-reference links. They are not safe to market
as real-company results; source IDs are inspectable MCP references, not web URLs.
The full 13-message SaaS primary set has not received the same final prose audit.

The small scalar-report fix recognizes a unique authorized healthy contract
with complete comparable evidence for the selected window. It does not invent
a decomposition or engine-verified numeric claims; the report remains a partial
source-evidence handoff. Tests include incomplete coverage, wrong identity/window,
access/health failures, duplicates, missing measurements, invalid decompositions,
explicit decomposition conditions, and compact/full MCP responses.

The revision field now explicitly distinguishes the exact source revision from
SignalWeave context revisions. The original failed SaaS run is not relabelled
or pooled into a repaired attempt.

## Interpretation boundaries

Check metric/revision, periods, unit and values against the independent oracle;
review the actual brief for scope, useful implications, evidence, caveats,
unsupported causes and claimed delivery. Structured self-labels are not report
quality. A quiet policy result alone does not prove delivery of a useful digest.

These are clustered synthetic cases, not independent enterprises or authenticated
employees. No Slack/email was sent. Static-token HTTP is a single-identity
sidecar, not employee SSO or managed hosting. Native provider token usage is not
instrumented: legacy zero metrics are not zero cost. No customer readiness,
calibration, general superiority or cost/speed advantage follows.

## Reproduce

Build the current native bundle and choose an exclusive new directory:

```sh
uv run python -m evaluations.decisions_semantic_trial \
  --binary dist/signalweave/signalweave \
  --key-file /private/path/openai.key --codex /absolute/path/to/codex \
  --output artifacts/semantic-retail-unique \
  --readers 10 --companies retail --sensitivity --live
```

For the separate updated-ledger test, choose another directory and add
`--refresh-after-onboarding --readers 2`. For marketplace HTTP, add
`--transport streamable-http`. Both modes also run eight direct policy contrasts
and a required-definition-edit check; `--sensitivity` adds four agent episodes.
These commands incur real Codex and OpenAI API usage. No automatic retry turns
failures into successes. Raw traces remain in ignored
`artifacts/decisions-semantic-2026-10-25/`, not committed bulk evidence.
