# SignalWeave release-readiness review — 2026-09-27

## Decision

**Conditional GO for merging as a controlled, delivery-disabled alpha. NO-GO
for an autonomous production service, a shared multi-tenant offering, or a
claim of measured warehouse cost savings.**

This distinction matters. SignalWeave's core product is the Jev-backed decision
layer between human-authored analytical intent and an existing agent, scheduler,
or delivery system. The repository now has credible proof of that path. It does
not yet own the distributed state, delivery, identity operations, or customer
labels required to claim a complete enterprise service.

## Review method

Nine independent adversarial roles reviewed the current branch:

| Role | Focus | Result |
| --- | --- | --- |
| Security | tenant isolation, source boundaries, SSRF, secrets | found release-hardening issues; the static-token HTTP boundary and Trino pagination were fixed in this review |
| Provider generalization | Superset, Preset, Hex, Looker, Trino and messy catalogs | core adapter contract is sound, but provider completeness and pagination remain deployment gates |
| Jev contract | real model selection, payloads, typed judgments, retries | found that the SDK model was not explicitly pinned; fixed and regression-tested |
| Onboarding | free-form cards, review, approval, certification | onboarding is usable, but approval is not a full workflow certification gate |
| Evaluation integrity | hidden labels, baselines, cost/speed claims | live Jev proof is valid as bounded shadow evidence; cost savings remain unproven |
| Reliability | retries, receipts, stores, concurrency, operational failure | single-process shadow pilot is supported; crash recovery, shared state, quotas, and HA remain open |
| Open-source release | quickstart, packaging, docs, reproducibility | README evidence and quickstart wording were corrected; release packaging still needs a blessed main/tag |
| Enterprise buyer | adoption value and pilot boundary | conditional pilot approval; no autonomous rollout or ROI claim |
| Test/CI | regression and reproducibility | full local regression is green; live Jev/provider runs remain explicit deployment gates |

The panel converged on the same boundary rather than treating a passing unit
suite as enterprise proof.

## Evidence that supports the alpha merge

The current proof uses the real TypeSafe transport where Jev is claimed:

- **Everything-tracking live Jev replay:** 60 cases across six company shapes,
  12 workflows, 36 source adapters, 7–8 sources per case, and unrelated decoys.
  It achieved 53/60 exact outcomes, 100% required-evidence recall, 0 unsafe
  automatic actions, median Jev latency of 532 ms, and p95 of 662 ms. The
  independent adversarial recomputation passed with no findings.
- **Live onboarding replay:** 8 heterogeneous cases achieved 8/8 required
  candidate recall, 8/8 safe review-preserving outcomes, 6/8 exact recommended
  sets, and 0 tenant leaks. The two non-exact recommendations stayed in human
  review rather than being promoted automatically.
- **Northstar local Superset path:** the production runtime completed discovery,
  free-form onboarding, persisted review, approval, live Jev evaluation, and
  idempotent replay. It normalized 10 charts into 25 observations and 36
  evidence items. A clarified owner policy passed 6/6 counterfactual cases with
  0 false or missed notifications.
- **Agent value signal:** the paired research replay is directionally positive
  for evidence packaging and safety, but is not a cost proof. It is reported as
  research evidence, not as a production guarantee.

Full details are in [`live-jev-proof-2026-09-27.md`](live-jev-proof-2026-09-27.md).

## Changes made during this review

- Streamable HTTP with token auth now fails closed unless an explicit static
  tenant and principal are configured. An intentionally unscoped local process
  remains available through stdio.
- The MCP factory has an explicit `require_principal` boundary, and the CLI
  enables it for every HTTP deployment; direct embedding must provide its own
  identity middleware or remain a local/stdio integration.
- Jev calls explicitly pass `model="jev-latest"`; setting `TYPESAFE_MODE=jev`
  can no longer silently inherit a different SDK default model.
- Draft and metric-card IDs are service-owned UUID-suffixed identifiers; callers
  cannot choose an identifier that could race with a store upsert or overwrite
  another card.
- Evaluation fingerprints now include the executable card payload and tenant,
  not just an ID and version label.
- Trino `nextUri` pagination is restricted to the configured origin, rejects
  unsafe URL components and repeated cursors, and has a bounded page count.
- Jev retry count and exponential backoff are bounded by configuration
  validation, preventing a copied deployment value from creating an unbounded
  retry storm.
- README evidence now reports the current live numbers and clearly separates
  real Jev shadow proof, synthetic trials, and unproven cost claims.
- A regression test covers reserved card IDs, Jev model pinning, cross-origin
  Trino pagination, and repeated Trino cursors.

## Conditions before calling it enterprise production-ready

These are not hidden failures; they are the explicit next acceptance gates for a
real customer:

1. Run a customer-authorized shadow pilot with a real IdP, source credentials,
   owner labels, and a time-split holdout. Measure useful-alert precision,
   investigation rate, false-notify rate, time-to-decision, source-fetch cost,
   and delivery reliability.
2. Replace single-process SQLite assumptions for any multi-replica deployment:
   supported shared transactional storage, migrations, backups, retention,
   stale-`PREPARED` receipt recovery, and crash/restart tests.
3. Add operational budgets beyond per-evaluation fan-out: end-to-end deadlines,
   process/tenant concurrency limits, provider query/page budgets, and bounded
   retry behavior with observable failures.
4. Define the customer adapter contract for freshness timestamps, completeness,
   native authorization, bounded pagination, resource identity, and typed
   provider errors. Jev cannot recover a relevant asset removed by provider-side
   candidate pruning.
5. Bind approval/certification to an immutable card digest, exact source scope,
   context version, and catalog identity. Re-enter review when expand-mode
   evidence changes materially.
6. Keep delivery caller-owned for the first pilot, then separately prove the
   customer's destination authorization, retry, dead-letter, and audit path.

For simple one-metric threshold alerts, native BI alerts or SQL are cheaper and
easier. SignalWeave earns its complexity when the decision needs multiple
artifacts, definitions, ownership, freshness, corroboration, investigation
context, and a bounded “notify / investigate / ignore” judgment.

## Merge recommendation

Merge this reviewed branch to `main` only with the release label **alpha /
shadow pilot**, preserving the conditions above in the release notes. Do not
market the merge as autonomous enterprise readiness. The correct next proof is
one real tenant, 20–50 human-approved cards, one or two adapters, delivery
disabled, and operator feedback attached to durable decision receipts.
