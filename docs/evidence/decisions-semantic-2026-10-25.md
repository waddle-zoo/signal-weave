# Decisions and shared metric meaning

Working study, October 25. [Protocol](../../evaluations/protocols/decisions-semantic-2026-10-25.json).
This tests existing cards, reviewed context and source exports—not a new semantic
engine. The frontier agent discovers definitions and writes the analysis;
OpenAI Decisions applies the saved policy.

## Verified v0.2.1 security rebuild

[`v0.2.1`](https://github.com/waddle-zoo/signal-weave/releases/tag/v0.2.1) was
published from merged `main` commit `4fd7ee1bda87569d323b45259044f0daf6fcbb5f`.
All three tag builds and publication passed in
[40224554790](https://github.com/waddle-zoo/signal-weave/actions/runs/40224554790).
Local and both CI Python suites passed **5,365 tests, 13 skipped**; container
runtime and pip-vendored CA checks, Preset replay contracts and the real local
Superset chart matrix passed. Independent review found and then cleared an
additional system-store/cross-sign gap before merge.

All three downloaded public archives passed checksums, clean tag/source identity,
actual CA-file checks and GitHub build-provenance verification. Their production
fingerprint is `b0fd21415085ba9d03926765197ab96b6c616e6560829d08d17a503b3c33279b`.
All contain certifi 2026.10.23 and the same CA bundle
`2ef52ad56b4803e264045c915e55c236cbfa045b84b81efefc218a19eb44bd2b`.
That bundle rejects all fourteen public incident chains offline, including AAA
cross-signs; the retained v0.2.0 bundle accepts seven. OpenSSL 3.6.3 used explicit
CA files with system stores disabled; all fixed failures were issuer-trust
errors, not expiry. Ordinary unauthenticated PyPI HTTPS returned 200. This is
targeted incident verification, not general TLS assurance; see [security](../security.md).

The actual public HTTPS installer passed hidden-key OpenAI setup, company-source
connection, real isolated Codex registration, bundled skill and source health.
One fresh native Decisions evaluation returned `notify` for exactly Finance,
with delivery disabled; process restart replayed its receipt. Uninstall removed
only the disposable install, preserved local configuration/cards/receipts, and
public reinstall restored healthy use. No Jev credential or personal agent
configuration was used. Raw records remain in ignored `published-v0.2.1-wizard-v1`,
`published-v0.2.1-download` and `incident-chains-v1` artifacts.

Only dependencies, build checks and version metadata changed from v0.2.0;
`src/` and the canonical skill did not. This is release/integration proof, not
a fresh novice-human panel or a rerun of the larger analytical cohorts below.
All nine v0.2.0 release assets retain their IDs, hashes, sizes and timestamps.

## Prior published stable release

[`v0.2.0`](https://github.com/waddle-zoo/signal-weave/releases/tag/v0.2.0)
was published from merged `main` commit `53a24e3fcb25d28229233dcb5b903f1e1223e73b`.
All three actual tag builds passed in
[run 40220404230](https://github.com/waddle-zoo/signal-weave/actions/runs/40220404230).
At publication it was non-draft, non-prerelease and latest; it is now superseded
by v0.2.1 for the [CA trust exposure](../security.md). No rc5 asset was changed.

The actual public HTTPS installer completed hidden-key OpenAI setup, company-MCP
connection, real Codex CLI registration, bundled skill and source health in an
isolated home. Its native runtime SHA-256 is
`feca5ce632ead44fa99c490087ff45115ab4bb45f256d48107e80e102613e22d`;
the production fingerprint matches the local 0.2.0 study candidate below.
Archive/installer checksums and GitHub build-provenance attestation passed.
An initial manual checksum command used the wrong working directory and could
not find the checksum file; checking in the download directory passed. The
installer's own checksum verification had already passed.

Using that installed command, a scripted integration card produced one fresh
native `openai-decisions` result: `notify`, exactly Finance, delivery disabled.
Restarting the process and reusing its run key replayed the same receipt.
Uninstall removed only the disposable installation, preserved its exact local
configuration/cards/receipts, and public reinstall restored healthy use of that
configuration. No Jev credential, personal agent config or external notification
was used. Raw output is in `published-stable-wizard-v1` under the ignored study
artifacts. This checks the actual release; scripted card authoring is not a new
agent-onboarding trial or a novice-human usability panel. The larger journeys
below used the matching-source local candidate, not this later published file.

## Publication-aware follow-up

The initial studies below exposed two different gaps: a changed closed-period
measurement lacked source-owned correction evidence, and onboarding preserved
the business-alert recipient without completing the owner's data-review routes.
Neither is solved by forcing a conservative judgment into a business alert.

The prospective owner brief now explicitly names Finance for data/definition
review as well as qualifying business alerts. MCP and bundled-skill guidance
explain that required-evidence failures may produce `insufficient_data`; preserve
an intended review route or make caller-owned repair explicit. No engine gate,
threshold, automatic recipient fallback or new mandatory card schema was added.
The source fixture separately publishes an inspectable correction with its exact
superseded/current data snapshots, unchanged metric revision and query hash.
Both arms can inspect the same publication; it supplies no oracle or causal story.

A fresh SaaS canary (`published-refresh-v3-saas-canary`) completed four reader
reports, four agent-authored gap/conflict review handoffs, eight fresh native
OpenAI Decisions evaluations and one required-definition-edit deferral.
Independent review checked all eight human briefs, the four actual local-inbox
messages, phase source evidence and routes: no material numerical, causal or
routing error. Corrected revenue was USD 18,070.59 versus USD 17,716.12 (+2%).
One delivered body omitted the synthetic-fixture caveat present in its supporting
uncertainties/final reply; that presentation miss remains recorded.

The earlier v2 canary was interrupted after three completed reader reports while
the research grader was corrected to accept both owner-permitted review enums
symmetrically. Its fourth reader is censored with unknown usage; it is not pooled
with the completed canary or relabelled a provider failure.

The larger prospective cohort uses the **0.2.0 native candidate** built from
`81181a8`, production fingerprint
`cf58379fe3598260c552661f6fc2d7d32110c6da19a88258273956d0e19f4d80`.
All three fresh onboardings preserved the approved canonical source, shared
reviewed definition and intended business/review routes. **All 60 canonical
reader reports passed the structured figure, scope, revision and policy checks**
against changed measurements, not the older onboarding figures. Each treatment
reader called the native evaluator. Actual SQLite inputs are backed up and
hashed before each phase, outside agent access.

| Company | Ordinary / SignalWeave correct readers | Median seconds, ordinary / SignalWeave | Fresh onboarding seconds |
| --- | ---: | ---: | ---: |
| Retail | 10/10 / 10/10 | 33.23 / 40.56 | 180.61 |
| SaaS | 10/10 / 10/10 | 30.97 / 45.27 | 122.10 |
| Marketplace, authenticated HTTP | 10/10 / 10/10 | 31.87 / 38.49 | 172.72 |

These timings exclude onboarding; the three company processes ran concurrently.
SignalWeave added overhead, not a measured speed advantage, and the equal-context
baseline also answered correctly. Provider cost remains uninstrumented.

The review stages stopped separately, without rescoring:

- Marketplace baseline gap: delivered to Finance but submitted `recipients=[]`.
- SaaS treatment conflict: delivered to Finance but submitted `recipients=[]`.
- Retail treatment gap: attempted an invalid inbox label, finalized the report,
  then could not retry. It accurately reported that nothing was delivered.

Seven review episodes completed; six actually delivered. Four passed every
strict check. Independent review found a contradictory test instruction:
"Recipients are empty when no alert is warranted" conflicts with an owner-requested
data review that is not a business alert. The two empty-audience submissions
followed that instruction while delivering correctly. Retail's missed delivery
is a real caller-workflow failure, not a provider or card-onboarding failure.

A prospective research-only correction makes review audiences explicit, declares
the test sink's sole valid address in its schema, and explains that report
finalization closes delivery. Both arms get the same corrected contract; no
argument is auto-corrected and no grader is relaxed. Original failures remain.
The separate `review-supplement-v1-{retail,saas,marketplace}` runs reused clones
of those actual successful onboardings, not new prebuilt cards or rerun reader
cohorts. A scripted fictional source operator revalidated the new isolated
endpoints through public bind/review/approve tools without changing the policy.
All three supplements completed: **12/12 actual local-inbox review deliveries**,
**24/24 fresh native policy contrasts** and **3/3 required-definition-edit
deferrals** passed the strict checks. Every report matches its delivered text;
every native result checks top-level non-replay and its new idempotency key.
The existing source publication is retained, not regenerated to justify a new
result. Independent final message review passed the scoped human/content/delivery
checks for all three companies, with citation/presentation caveats. Reviewers
checked all twelve submitted briefs, delivered bodies and final replies, phase
backups, actual ordering and fresh native receipts; none found a release blocker
within this scope. In the SaaS treatment gap message, the agent drops a character from a
snapshot hash; a marketplace baseline conflict report retains a duplicated
publication prefix from the older shared material. Canonical source references,
original evidence and phase backups remain inspectable, but those particular
references are malformed. These are separate results,
not a retrospective pass for the stopped original journeys or a published
stable-download claim.

Independent prose review covered all 60 canonical reports and seven completed
review episodes. The canonical figures and supported implications were sound in
both arms. Citation/presentation limits remain: some briefs omit population or
fixture qualifiers or include operator chatter, and a SaaS baseline gap message
contains an incorrect snapshot ID despite correct figures. Nineteen marketplace
submissions inherited a duplicated publication-reference prefix from the source
fixture itself, rather than inventing it. The prospective fixture fixes that
prefix without changing measurement or publication records. Source-owned
references still need checking; a typed decision is not citation validation.

The 0.2.0 candidate passed all three native platform gates in
[run 40216114409](https://github.com/waddle-zoo/signal-weave/actions/runs/40216114409),
including real archive install and PTY setup. The local full suite passed
5,340 tests, with 13 skipped, when granted its required terminal/loopback access.
An earlier sandboxed run retained three permission-related failures; it is not
reported as a product pass. The packaged interactive wizard also registered
with the actual Codex CLI and checked source health in a disposable home.

The frozen protocol records the main research modules. Its source-hash list
omits the imported audit/redaction helper; that helper is recoverable at clean
commit `81181a8` as `evaluations/bootstrap_agent_trial.py`, SHA-256
`01ee8ad009f7b33c5fec6c21f2b6334007f5a8b3dc997a16a2aba063ab3c4e7b`.
This supplementary identity does not rewrite the captured protocols.

## Earlier installation and runtime checks

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

## Earlier results and retained stops

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

**Those broad gates are not exact policy or investigation-delivery proof.** Final
adversarial review found them too permissive to establish that operational
claim: all six gap cases returned `insufficient_data`, while the cards say to
investigate incomplete coverage. Only three of six conflict cases returned
`investigate`; the others returned `insufficient_data`, including marketplace
with no Finance route. Against literal `investigate` wording, final exact-label
agreement is 15/24, not 24/24. Evidence/comparability safety gates also affect
these final results, so that is not raw provider accuracy. The missing-owner
handoff is a substantive onboarding/workflow gap, not something to hide behind
the broad review-outcome category. No downstream agent or recipient was tested
in this direct-call supplement.

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

Those earlier results left a requirement to distinguish and test the owner-approved paths for
a business signal, a data-quality problem and a definition disagreement. Prove
that the calling agent follows up with the right person, not merely that the
API returns a conservative enum. Do not remove evidence safety checks or force
an action just to match a label. Also finish the publication-aware forward
test and the remaining fresh-reader cases; these results do not complete those
requirements. The separate publication-aware follow-up above addresses those
stages; it does not retroactively complete these original stopped runs.

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
`--review-handoffs` adds paired actual local-inbox gap/conflict deliveries. The
separate [review supplement](../../evaluations/semantic_review_supplement.py)
requires a closed matching `stable-v2-COMPANY` run with twenty successful readers
and valid onboarding; `--help` lists its explicit paid opt-in and exclusive output.
These commands incur real Codex and OpenAI API usage. No automatic retry turns
failures into successes. Raw traces remain in ignored
`artifacts/decisions-semantic-2026-10-25/`, not committed bulk evidence.
