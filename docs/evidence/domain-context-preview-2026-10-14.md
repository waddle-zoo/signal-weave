# Domain-context preview evidence

Scope: `feat/domain-context-memory`, based on main `e8842ac`.
[Draft PR #19](https://github.com/waddle-zoo/signal-weave/pull/19) is not a
release or enterprise-readiness approval. The published rc3 download is unchanged.

## What ran

| Gate | Observed result |
| --- | --- |
| Clean `make verify` after the core repairs | 3,114 passed, 7 skipped; 217.86 seconds; Ruff passed |
| Final focused context, HTTP and pilot-integrity tests | 126 passed; 5.31 seconds; these are deterministic contract variations, not 126 business trials |
| Hosted identity middleware | Actual MCP HTTP requests with signed JWTs from a synthetic issuer: missing curation scopes rejected, authorized review completed, tenant separation retained; not a customer IdP |
| Native feature candidate | Clean build from `3cfd3b4`; fingerprint checked against the checkout before use |
| Native/local Superset | Isolated scripted CLI setup, 14-tool stdio MCP, draft and review, reuse by two task queries, and recovery after process restart; 5 metadata reads, 0 observed Jev POSTs; no analytical evaluation or delivery |
| Public opt-in native test | `tests/test_knowledge_superset_integration.py`: 1 passed in 26.41 seconds, with setup/server outside the checkout and automatic cleanup of generated private state |
| Independent engineering review | Scoped GO after repairing authorization-cache, ownership/sharing and bounded-retrieval defects; not enterprise approval |
| Independent docs/skill review | Accepted the opt-in boundary and distinction between review dates, source freshness, card approval and workflow certification |

The source suite initially retained one HTTP-test failure because its auth
settings were incomplete. The corrected test and clean full rerun passed; the
failed/mixed collection is not counted as a pass. Earlier Superset harness
attempts used an existing profile, the wrong setup flag, or non-private fixture
paths. They remain excluded; the final native proof uses explicit isolated setup.

## Live-agent canary: no demonstrated context benefit

One paired support case used live `gpt-6-luna`, medium effort, through Codex CLI
`0.162.0-alpha.2`. Both arms retained the same full company notes and fixture
source tools. Both made five tool calls, read two snapshots, and chose the
expected quiet outcome. Independent review found both reports supported by the
supplied data, without an invented cause or claimed delivery.

The treatment did not call either SignalWeave context tool. This cannot show
retrieval quality, context value, or a performance advantage. Its `recipients`
field conflated the requested report audience with alert recipients; it is not
evidence of an unsafe send. Protocol 2 separates those fields and was not rerun.
The original result is preserved, not relabeled as a passing route test.

Only two agent invocations ran, not the six defined by the three-case fixture.
They used 102,767 aggregate input tokens (76,544 cached) and 1,410 output tokens;
no further invocation started after the predeclared input stop was reached.
This was precurated component testing, not onboarding or Jev evaluation. The
actual guide/skill-driven product path must be tested before expansion.

## Reproduction and remaining gates

Run `make verify` and the focused `tests/test_knowledge*` plus
`tests/test_domain_context_agent_pilot.py`. The opt-in service is documented in
[shared domain context](../domain-context.md); the research runner and fixtures
are `evaluations/domain_context_agent_pilot.py` and
`evaluations/data/domain-context-pilot.json`. Live runs require explicit output
directories and never overwrite an earlier result. Full traces stay ignored.

To repeat the native/Superset protocol check, build the current checkout and
point it at an explicitly configured local fixture and an inspected asset:

```sh
uv sync --extra dev --extra binary
uv run python scripts/build_binary.py
RUN_CONTEXT_SUPERSET_INTEGRATION=1 \
SIGNALWEAVE_BINARY="$PWD/dist/signalweave" \
TYPESAFE_API_KEY_FILE=/private/path/jev.key \
SUPERSET_URL=http://127.0.0.1:18089 \
SUPERSET_CONTEXT_RESOURCE=chart:1 \
uv run pytest tests/test_knowledge_superset_integration.py -q
```

Set `SUPERSET_USERNAME`/`SUPERSET_PASSWORD` for the fixture if they differ from
its demo defaults. This test uses a temporary private home, does not register
with your personal agent, and makes no decision-provider call. The credential
is required for the normal server startup path, not used as evidence of Jev
evaluation. Without explicit opt-in the test is skipped by the offline suite.

Remaining after the initial substrate: revision-bound card context, source-identity/meaning
drift, dependency recertification, actual guide-driven onboarding and cross-agent
handoff, and a preregistered equal-information business-outcome trial. The
revision-bound follow-up below addresses the first three contract gaps. Lexical/source-anchor
retrieval is not semantic graph traversal. Review-due polling is not automatic
notification delivery, and a review date is not data freshness.

Production fingerprint: `ba0080106312fddb838f2a9291e2a8643292cafea015487232e1a24d8f3b464c`.
Native executable SHA-256: `1b38a1dc65cac146e06c020e5afb1b6d73f6efed5404bb48839d99b8dee30af3`.
Native proof report SHA-256: `1662d5f0ed8c68bf64336b2997a11c1b3d63989abc9b7a5087c542832963ae01`.
Canary report SHA-256: `f7e779a978933e8a2698fcc04d606e12fdd5d81a299ee7ab4a6f4c16becf1504`.
Canary trace SHA-256: `702be26c6378376d3220381937e29e5171e55906960cb4aabba0a42e04b34e3f`.

## Revision-bound follow-up — 2026-10-15

Implementation: `03b48ef2805c7b8f2b2b5965ed1ad1946e1e366b`. The opt-in extension
now exposes six context tools (sixteen total in the agent profile). Cards can
pin exact reviewed shared entries, distinguish advisory meaning from explicit
policy prerequisites, and surface changed dependencies without copying note
bodies into provider inputs or receipts.

Independent engineering reviewers found and reproduced gaps before giving a
scoped functional GO: preview bypass, mid-run dependency changes, unbinding while
inference was running, provider-derived-context replay mismatch, and a
claim-lost replay of a foreign legacy receipt. Regression tests now cover these
paths. CLI artifact tests also cover actual production replay, not just a mock
with unchanged receipt metadata. HTTP checks use signed synthetic identities and
verify owner/scopes, tenant isolation and absence of note bodies in card results.

Advisory changes preserve policy evaluation with warnings. A changed required
dependency produces no policy outcome but retains anchor evidence for agent
investigation. Historical receipts stay immutable; current action availability
is checked separately. Connector namespaces cover the five shipped adapter
families in contract tests, not live Hex/Looker/Trino deployments. Opaque company
MCP routing needs an operator-maintained, nonsecret `context_namespace`; it is
an assertion, not automatic discovery of hidden upstream identity.

The first full follow-up run failed 29 tests, primarily synchronous internal
receipt/readiness callers after those tools became async. Trial runners and
tests were corrected without changing labels or weakening assertions. The
subsequent suite passed; final settled-source and native results are recorded
below. Earlier native builds are not evidence for the final claim-race fix.

Final settled-source `make verify`: **3,186 passed, 9 skipped in 213.14 seconds**;
Ruff and `git diff --check` passed. This is the repository's offline regression
suite, not 3,186 independent business trials. The skipped native/live tests are
separate explicit checks; their results do not come from this offline total.

This remains contract and transport evidence. No additional frontier-agent
benchmark ran, and the original canary's negative mechanism result still stands.
The next required proof is actual guide/skill-driven owner onboarding and later
agent reuse, followed by the equal-information business-outcome comparison.

Final native checks: **2 passed in 56.79 seconds**, against a clean build from
`03b48ef`. The card lifecycle made nine MCP calls and observed nine Superset
metadata GETs and zero TypeSafe System One POSTs in process logs. It exercised
noninteractive isolated CLI setup, real selected-chart authorization, draft
onboarding, context review/binding, restart, supersession and rejection of draft
evaluation. It did **not** approve a complete business card, execute a Jev policy
evaluation, inspect analytical chart rows, or run an autonomous Codex session.
The separate native context-retrieval check also passed. Neither check modifies
the personal agent configuration or the existing Superset data.

Reproduce the current card lifecycle with the same build and fixture environment
above, setting `RUN_CONTEXT_CARD_INTEGRATION=1` and running
`tests/test_context_native_card_integration.py`. The test caps calls at fifteen
MCP tools and one observed provider POST. Normal offline runs skip it. Use
`-o junit_family=legacy --junitxml=artifacts/context-native.xml` to retain the
recorded build and request-count properties; raw logs and reports remain ignored.

Final production fingerprint: `ec780b76546a3ef6cc47ef1eff44e11140e6e94ea603aeed3bd284e17ede22bb`.
Final native SHA-256: `f3fe421610815b6f5d32f8a43025071548bd9d1dc82da513418c5ce155f3e6bc`.
Final native JUnit SHA-256: `1670e615633cd7daf5743d8f70011576cd3733a5b2d8241d53ec2e765c446858`.
This is an unreleased feature executable, not the published rc3 asset, despite
sharing its package version string. Identify it by the commit and fingerprints.

## Live cold-onboarding smoke — 2026-10-15

Three actual `gpt-6-luna`/medium Codex invocations ran, using CLI
`0.162.0-alpha.2`. The treatment used the actual native MCP, project-installed
skill bytes explicitly supplied as instructions, and a company-MCP source bridge.
Both arms retained source tools, scripted owner answers and independent notes.
This was not automatic skill discovery, a real human wizard, or live BI data.

| Attempt | Observed result |
| --- | --- |
| Protocol 1 baseline only | 18 tools, 36.80 s; invalid harness: the consent tool required an undocumented notes ID. It stopped honestly. The draft also had a real arithmetic error: $14k instead of $10k. The source lacked period/coverage declarations, so its caution about comparisons was correct. No treatment ran. |
| Protocol 2 baseline | 13 tools, 23.05 s; saved notes and a correct $10k/0% readout, with population details still unresolved. This was a handoff, not certified automation. |
| Protocol 2 SignalWeave | 24 tools, 79.09 s; used native context/source/card tools and saved a correct factual readout, but the card remained draft. The tool cap terminated the agent before complete usage was returned. No completed handoff or policy evaluation. |

Protocol 2 used the existing comparison-capable fixture, equally available to
both arms, rather than inventing dates or treating the sparse first export as
complete. Both artifacts preserve the net-sales definition, exclude bookings and
test stores, and avoid causal claims. Independent content review confirmed the
$10k comparison in the second attempt but found that the source's generic
population label referred to an unavailable glossary. The scripted owner could
not answer that question. Keeping the card draft was appropriate.

The attempted comparison is **not scoreable as an advantage**. Besides censored
treatment usage, the harness required an approved card plus duplicate working
notes from treatment while accepting baseline notes with unresolved population.
That is not an equivalent semantic-completion gate. The time/call counts above
describe the attempts, not a speed comparison or an accuracy rate. No Jev request,
notification or schedule occurred. Do not attribute these results to Jev quality.

Known usage across the first invalid invocation and the corrected baseline:
265,585 input tokens, including 211,200 cached (54,385 uncached), and 4,645 output.
Treatment usage is **unknown**, not zero and not included in those totals. No
further live invocation was started after the missing-usage stop.

Repairs after these runs (runner protocol 3): notes tools return their approval ID; the harness can
record an awaiting-owner-context handoff without requiring duplicate persistence
or pretending automation is ready. Production reviews now name both source scope
and population, and provide bounded existing approval arguments after owner
confirmation. They do not waive missing context, source checks or consent.
The existing metric glossary is also retrievable on demand in both arms; it was
withheld from the opening but accidentally unavailable through any source tool.
Retrievability does not establish that the glossary resolves every population question.
These repairs have offline regression coverage; **they were not live revalidated
in this cohort**. Full cross-session reuse, complete onboarding and business lift
remain open gates. Later trials need an accessible source glossary/expert and
equivalent semantic review of both arms, not just a more permissive finish tool.

Trial production fingerprint: `9511def1418e4d7d4b06d58a072b8db60ebd84912bfd41472d572d3b4406e8fa`.
Trial native SHA-256: `57f5fb85240bd0aaa1a476cf7036450941f2bcc01cda9560af47cf8ec3d1e31e`.
This candidate was built from a dirty checkout with updated skill content; the
fingerprint was verified before use. It predates the approval-handoff repairs.
Protocol 1 report SHA-256: `3016e4adf62bdd31cb51a336de53d6da9b2a4f3ef1fc61a0a6f1f5ea54f4bac7`.
Protocol 2 report SHA-256: `381a8bdff78dc6a785645e065be5e1b04ac539f3346391c817562ebb445708a8`.
Raw reports and traces stay ignored under `artifacts/context-onboarding-live-*`.

The post-trial production repair has a separate native check: **2 passed in
54.73 seconds** on a clean build of `12a95585cb1366b22fde86abde63e1e3f76a70f4`.
It verifies the new approval arguments are present on actual native onboarding,
without an owner reason filled in, alongside context binding/restart behavior.
The card lifecycle recorded nine calls, nine observed Superset metadata reads
and zero Jev POSTs. This is protocol verification, **not another live-agent
onboarding or a test that the owner can resolve population ambiguity**.

Repair source fingerprint: `fba93c9f0b329e271793b24f867dea2989c8a58ab75c7c772e5a9f60ea0c68f5`.
Repair native SHA-256: `222ec11ea35e4f73d609aa664429987c29914ee6046889ac3900bf523a0544a4`.
Repair native JUnit SHA-256: `2f0b2fb57e8e941770712efc58f18faeeda519353a5e3e845508d29c344b1dd0`.

After the glossary repair, `make verify` passed **3,208 tests, with 9 opt-in
checks skipped, in 211.27 seconds**, and Ruff passed. Protocol 3's native
preflight also completed on the repair binary: identical analytical fields
survived the company-MCP round trip, with zero agent invocations and zero
provider attempts. Its baseline/treatment tool schemas serialized to
2,601/35,401 bytes. This is setup integrity and schema size, not token usage,
onboarding success, or a measured business benefit.

## Native hosted-context check — 2026-10-15

`tests/test_context_native_http_integration.py` passed **11 checks in 27.92
seconds**: ten local-fixture URL boundary cases and one actual native HTTP
lifecycle. It uses the repair binary/fingerprint above, a private temporary
home, a synthetic signed loopback issuer, and the existing local Superset
fixture. No personal agent registration or inference is involved; the startup
provider key is synthetic and the provider endpoint rejects every call.

The HTTP lifecycle verified missing/invalid/expired/wrong-audience token
rejection, curator identity from the JWT rather than the local setup identity,
reviewed context reuse by a second client subject, read-only write rejection,
foreign-tenant exclusion, and persistence after server restart. After the
curator changed the note into an overdue draft, default retrieval did not fall
back to its older reviewed revision; review-due polling returned the new draft.
Superset metadata authorization was observed; analytical chart data was not read.

An independent reviewer identified a remote-URL override risk in the test.
The corrected check validates loopback-only fixture URLs before setup and no
longer reads a real provider key. The reviewer gave a scoped GO after those
repairs. This is not customer SSO validation, reminder delivery, an autonomous
agent trial, or evidence of better reports/alerts.

Reproduce against a deliberately selected local synthetic Superset fixture:

```sh
RUN_CONTEXT_HTTP_INTEGRATION=1 SIGNALWEAVE_BINARY="$PWD/dist/signalweave" \
  uv run pytest tests/test_context_native_http_integration.py -q \
  -o junit_family=legacy --junitxml=artifacts/context-native-http.xml
```

The executable must match the current production fingerprint. The HTTP test
requires no real provider key. Native HTTP JUnit SHA-256:
`455b7d5166ac450757009366bc338f0a8eb146e67280e9de4be05bc9213bedc2`.

## Scripted approved-card/live-Jev check — 2026-10-15

The existing six-company fixture supplied one retail company's three periods,
transported through the actual native company-MCP bridge. The script saved a
card, reviewed and pinned its definition, and used the public review/approval
calls. A fixture-owner reason authorized only the supplied synthetic scopes;
this was not conversational onboarding, real BI data, or human sign-off.

The first attempt received the expected first outcome but failed because the
test assumed completed results have the deferred-only `judgment` field. It used
one Jev request: 3,740 input/57 output tokens. The corrected invocation passed in
26.07 seconds, matching `insufficient_data`, `ignore`, and `notify` across the
three periods, using three requests: 15,020 input/163 output tokens. A subsequent
required-context draft caused a no-outcome handoff without another Jev request.
Explicit-source authoring used no inference, and pins were absent from provider
states. Final outcomes include local execution guards; they are not solely raw
Jev choices. Routes are resolved from the saved card, not invented by Jev.

The **four-request total includes the failed attempt**: 18,760 input and 220
output tokens, no provider errors/rejections and no frontier-agent invocation.
These are observed provider counts, not billed cost or comparative speed.
No additional live request was made after that cap.

Adversarial review found two missing assertions: exact destination correctness
and nonempty, provenance-bearing deferred source content. The test now checks
both, has nine offline mutation cases, and retains native result packets.
Those stronger assertions **were not live revalidated in this series**; the
original trace retained provider/source calls but not the returned native
packets, so it cannot retrospectively prove them. Copied credentials now live
inside an automatically cleaned private temporary directory. This lifecycle
check does not complete the onboarding or final-agent outcome gates.

The observed executable is the `12a9558` repair build identified above; it
predates the subsequent default-profile onboarding-instruction correction.
First trace SHA-256: `1515ab09f073c516c1a15293b070f8f185e95fc223369016d9300955d5fedc49`.
Corrected trace SHA-256: `aab5bfbc64ca6336b9ef86e99006195891594e45811f78c9a449b65fc700e60f`.
Corrected JUnit SHA-256: `c1ca1d603d9f7d3d1567f63fe7c73d741f599581f2a8fc994c9bba5b7ba0c78e`.
Raw files remain ignored under `artifacts/context-native-jev-*`.
