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

Remaining: revision-bound card context, source-identity/meaning drift, dependency
recertification, actual guide-driven onboarding and cross-agent handoff, and a
preregistered equal-information business-outcome trial. Lexical/source-anchor
retrieval is not semantic graph traversal. Review-due polling is not automatic
notification delivery, and a review date is not data freshness.

Production fingerprint: `ba0080106312fddb838f2a9291e2a8643292cafea015487232e1a24d8f3b464c`.
Native executable SHA-256: `1b38a1dc65cac146e06c020e5afb1b6d73f6efed5404bb48839d99b8dee30af3`.
Native proof report SHA-256: `1662d5f0ed8c68bf64336b2997a11c1b3d63989abc9b7a5087c542832963ae01`.
Canary report SHA-256: `f7e779a978933e8a2698fcc04d606e12fdd5d81a299ee7ab4a6f4c16becf1504`.
Canary trace SHA-256: `702be26c6378376d3220381937e29e5171e55906960cb4aabba0a42e04b34e3f`.
