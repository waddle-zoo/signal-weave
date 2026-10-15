# Local and deployed proof record — 2026-10-04

This is the current evidence record for the local binary and the Docker
deployment. It is a bounded engineering proof, not a claim of universal
enterprise accuracy or a real-customer production certification.

## Result at a glance

| Surface | Result |
| --- | --- |
| Repository regression suite | 2,363 passed, 5 skipped |
| Ruff | Clean |
| Native binary on this Mac | Built and passed the real-binary installer smoke |
| Docker runtime | Postgres, Redis, Superset, and SignalWeave healthy |
| Public readiness | `/readyz` returned 200 with Jev, adapter, stores, and identity checks |
| Protected MCP | Unauthenticated `/mcp` returned 401; authenticated initialize/tools worked |
| Local Superset matrix | 9 dashboards, 102 charts, 8,633 observations, 37 viz types, 0 silent-loss issues |
| Live Northstar multi-step Jev trial | 6/6 initial outcomes, 6/6 final outcomes, 6/6 typed handoffs, 6/6 context bundles |
| Independent Northstar reviewer | Passed with zero findings |
| Automatic-route onboarding gate | Fresh deployed notify card blocked before approval when its source comparison contract was undeclared |
| Delivery in all proof runs | Disabled; no Slack, webhook, or remediation side effect |

## What was actually exercised

### Deployed HTTP runtime

The running container used the real local Superset service as its source. A
fresh human-authored card was created through MCP, reviewed, explicitly
approved, evaluated through the production runtime path, and replayed with the
same idempotency key. This particular HTTP shadow trial uses a deterministic
synthetic TypeSafe transport so it spends no Jev credits; live Jev semantic
quality is proven separately by the Northstar trial below.

The receipt contained 22 observations and 33 evidence items. The typed result
was `notify` at confidence 0.93, while delivery remained disabled. Exact replay
returned the same decision without another Jev or provider evaluation. The
provider telemetry recorded 10 bounded saved-chart-query fallbacks because the
local charts did not expose saved query contexts; that limitation was retained
as an explicit warning rather than hidden.

The same rebuilt container was then exercised through an authenticated HTTP MCP
session with the real mounted Jev key. Live onboarding ranked the selected
`Sales Dashboard` at 0.91 relevance, live Jev returned `investigate` at 0.47
over the same 22 observations and 33 evidence items, and the persisted receipt
reported `delivery_disabled`. Repeating the identical idempotency key returned
`replayed` with the same outcome and confidence. This is the deployed live-Jev
path; the synthetic shadow result above is intentionally kept separate from it.

The onboarding boundary is now stricter. The fresh automatic-route card first
returned `blocked / needs_human_input` because its source comparison contract
was undeclared. An explicit owner confirmation of that bounded gap moved the
card to `ready_for_approval`, after which approval succeeded. This proves the
human admission gate and identifies the source-contract work still required
before a dashboard can be treated as a reliable unattended monitor.

The onboarding boundary is now stricter. After rebuilding the container, a
fresh live `onboard_insight_card` request with an automatic `notify` route
returned `blocked / needs_human_input` before approval, with the exact blocker
`comparison-window-mismatch`:

> Required sources do not declare compatible comparison windows for automatic
> notify routes. Verify a source-owned comparison contract before approval.

Investigation-only cards may still be drafted and approved with the undeclared
window warning. This keeps exploratory analysis usable while preventing an
unverified dashboard snapshot from entering an unattended notification path.

### Northstar held-out multi-step trial

The current-branch run used live Jev over six externalized scenarios: four
single-step cases and two caller-owned investigation cases. Expected labels
were held in the fixture/scorer rather than sent to Jev.

The run produced:

- 6/6 exact initial outcomes and typed handoffs;
- 6/6 exact final outcomes and typed handoffs;
- 6/6 safe initial stages with no premature leadership delivery;
- 6/6 context-return checks;
- 9 Jev requests, with a 367.5 ms median stage latency; and
- a passing independent adversarial review with zero findings.

The multi-stage checkout case supplied all five facts returned by its bounded
diagnostic agent, including cohort validation and the confirmed deployment
cause. The trial proves the reusable card → Jev judgment → caller-owned
evidence collection → Jev re-evaluation contract on the current code. It does
not prove that SignalWeave itself discovers arbitrary company facts or sends
the final notification.

### Adapter and onboarding breadth

The live local onboarding probe covered Looker-style complete/partial contracts
and a Trino-style complete contract. It achieved 3/3 exact onboarding and
handoff results with delivery disabled. The partial contract became
`insufficient_data / repair_source`, rather than business work.

The live local Superset chart matrix covered unfamiliar visualization families,
including big-number, area, time-series bar, heatmap, horizon, pie, and table
charts. One unlabeled multi-number table remained explicitly `partial`; it was
not silently discarded.

## Reproduction

From the repository root, with the local Docker stack and a real TypeSafe key
available:

```sh
./.venv/bin/pytest -q
./.venv/bin/ruff check .
./.venv/bin/python scripts/superset_chart_matrix.py \
  > artifacts/deployed-local-superset-chart-matrix.json
./.venv/bin/python evaluations/northstar_multistep_trial.py \
  --seed-dir /path/to/northstar/warehouse/init \
  --typesafe-key-file /private/path/apikey_typesafe \
  --output artifacts/northstar-multistep-trial-current.json \
  --strict
./.venv/bin/python evaluations/northstar_multistep_adversarial_review.py \
  --report artifacts/northstar-multistep-trial-current.json \
  --fixture examples/northstar-multistep-trial.json
```

The deployed MCP smoke artifacts are retained locally under `artifacts/` and
contain no secret values. The compact readiness response is available from:

```sh
curl http://127.0.0.1:18000/readyz
curl -i -H 'Authorization: Bearer <deployment-token>' \
  http://127.0.0.1:18000/mcp
```

## What is not proven

This record does not establish cross-platform binary certification, a real
customer's operator-labeled usefulness, hosted Preset/Looker/Hex credentials,
multi-replica transactional deployment, or whole-report cost savings. The
repo's honest shipping boundary remains a controlled, delivery-disabled pilot.

The immediate product gap exposed by the deployed run is source onboarding:
recurring monitoring needs an adapter-declared or human-verified comparison
contract, not only a dashboard title and current observations. SignalWeave
already fails safe when that contract is uncertain; the next implementation
should make that requirement explicit in the onboarding preview and provide a
clean path for a source adapter or caller-owned context provider to prove it.
