# SignalWeave architecture

## Product boundary

SignalWeave answers “given the owner’s definition of what matters, what should happen next?” while leaving facts in the company’s existing data systems. Superset is the first source adapter, not the product boundary.

The service has four separable layers:

1. **Source adapter** — authenticates to Superset, discovers dashboard layout, and executes the saved chart query definition through the chart-data API.
2. **Observation layer** — normalizes scalar, categorical, and time-grained chart results into typed observations with current value, baseline, change percentage, dimensions, freshness, and source URL.
3. **Decision layer** — compiles natural-language intent into a bounded operation list, then selects an allowed outcome and recipient from evidence.
4. **Trigger boundary** — exposes MCP tools for agents and a small webhook endpoint for push-based schedulers or alert relays.

```text
             existing company assets
     existing data assets, owners, source definitions
                         │
                         ▼
                 source adapter (read-only)
                         │
                         ▼
       DashboardSnapshot → Observation[] → Evidence[]
                         │
              owner MonitorCard + plan
                         │
              ┌──────────┴──────────┐
              │                     │
       HeuristicJudger        JevJudger (optional)
              │                     │
              └──────────┬──────────┘
                         ▼
       safety gates → Decision → MCP / webhook caller
```

## Why this is not “just an LLM”

The workflow is designed so a language model is not responsible for the whole task:

- SQL and Superset calculate the facts.
- The card defines the allowed charts, comparison windows, recipients, and outcomes.
- The compiler emits a finite operation vocabulary; it cannot generate arbitrary SQL.
- TypeSafe receives structured state and answers typed questions with probabilities.
- Code enforces freshness, baseline availability, recipient allowlists, and confidence thresholds.
- The returned decision includes the observations and evidence that caused it.

Source failures are first-class state. A missing chart, Superset timeout, empty result, or ambiguous metric is represented as evidence and routed to `insufficient_data`/`investigate`; it cannot silently become `ignore`.

That separation gives the team a useful middle ground: more context-sensitive than a static alert, more deterministic and economical than repeatedly asking a general LLM to inspect a full dashboard.

## Monitor lifecycle

### 1. Draft

A dashboard owner provides:

- dashboard ID;
- a short title;
- what they care about and what should count as meaningful;
- optional chart IDs;
- explicit recipient groups.

The server creates a versioned `MonitorCard` and compiles it into a `MonitorPlan`. Drafting does not send anything.

### 2. Review

The plan is deliberately readable. It contains only known operations such as:

- `percent_change`;
- `baseline_comparison`;
- `freshness_check`;
- `seasonality_check`;
- `dimension_contribution`;
- `cross_chart_comparison`.

An approval UI or pull request can review the card and plan before a scheduler enables it.

### 3. Evaluate

Evaluation fetches only the selected chart IDs. The adapter preserves saved chart metrics, filters, groupings, and time grain where Superset exposes them. The engine then creates candidate observations and evidence statements.

### 4. Route

The judgment chooses only from card-approved outcomes and recipients. The engine applies hard rules after the judgment:

- stale data can escalate before interpretation;
- no comparable baseline cannot become an automatic no-op;
- low-confidence `ignore`/`notify` becomes `investigate`;
- non-action outcomes never retain a recipient.

The service returns a decision. Delivery remains with the caller so companies can use Slack, email, PagerDuty, tickets, an agent, or an existing workflow system.

## Operating modes

### Offline proof mode

`MONITOR_SOURCE=fixtures` uses deterministic synthetic dashboards representing common company environments. This is the fastest path for tests, CI, demos, and prompt/plan review.

### Superset mode

`MONITOR_SOURCE=superset` connects to a Superset instance, stores cards in the configured monitor store, and queries the selected saved charts. The Docker Compose stack uses this mode by default.

### Jev mode

`TYPESAFE_MODE=jev` swaps the decision implementation while preserving the same typed state, plan, evidence, and safety gates. The API key is loaded from an environment variable or external file and is never persisted by this repository.

## Enterprise integration shape

The proof uses local JSON because it keeps the repository easy to run. A production deployment should replace that boundary with:

- company identity and dashboard permissions;
- a reviewed monitor-card store with version history;
- a durable evaluation/audit store;
- a scheduler or Superset alert relay;
- delivery adapters with retries and idempotency;
- metrics for evaluation latency, action rates, confidence, and human feedback.

Those are deployment concerns, not reasons to expand the semantic monitor into another workflow engine.
