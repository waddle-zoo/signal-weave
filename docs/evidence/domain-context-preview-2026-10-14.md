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
