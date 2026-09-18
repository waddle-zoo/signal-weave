# Post-fix Luna agent trial

This trial answers a narrow question: after tenant-aware catalog enforcement,
can a general-purpose Luna agent reliably onboard itself to messy enterprise
monitoring workflows through MCP alone?

The run used the real `gpt-5.6-luna` Responses API, the real SignalWeave MCP
registry, and the real Jev-backed discovery and evaluation path. The agent saw
only the task brief and MCP tool schemas. Expected source refs remained in the
scorer and were not sent to the agent.

## Trial design

- 20 available enterprise/scenario combinations from the three-company fixture.
- Northstar Commerce, Harbor Bank, and OrbitWorks SaaS.
- Corroborated notification, explained ignore, contradictory investigation,
  stale escalation, missing baseline, source failure, and definition/grain
  mismatch cases.
- Superset, SQL, Airflow, table-quality, incident, and calendar-shaped sources.
- Typed tenant contracts and `SourceRegistry(authorized_tenants={...})` on every
  session.
- Serial sessions to avoid rate-limit or transport concurrency effects.
- Independent labels held outside the MCP surface.

## Results

| Measure | Result |
| --- | ---: |
| Sessions | 20 |
| Exact outcome + source decision | 3/20 |
| Complete MCP workflows | 15/20 |
| Complete cards | 18/20 |
| Complete provenance | 15/20 |
| Exact selected source sets | 4/20 |
| Average required-source recall | 25% |
| Wrong-tenant attempts reaching data | 0 |
| Wrong-tenant data leaks | 0 |
| Catalog leaks | 0 |
| Would-be unsafe automatic routes | 3 |
| Trace integrity | valid; 1,034 events |

The agent usually produced a syntactically complete card, but it often chose
extra related sources, omitted one of the required sources, or selected the
wrong related workflow. It also produced three automatic `notify`/`escalate`
outcomes that were wrong under the hidden labels. Delivery remained disabled,
so these were blocked would-be actions rather than external side effects.

## What this proves

The tenant boundary is effective even when a general agent is imperfect: the
agent never received another tenant's catalog, and direct opaque inspection is
now catalog-checked as well as card evaluation. The trace is independently
scorable and complete enough to identify the failure mode.

It does **not** prove reliable autonomous onboarding. The bottleneck is source
set construction and workflow semantics, not just final Jev classification.
The current public claim should therefore be: SignalWeave can provide a safe,
typed decision boundary for an agent, but the agent still needs guided source
selection or human confirmation before automatic operations.

## Next product gate

Add a guided source-resolution step that returns a proposed source set with
per-source reasons, required/optional status, and an explicit confirmation
boundary before approval. Then rerun this same hidden-label cohort. Do not
enable delivery merely because a card is syntactically complete or because Jev
returned a confident final judgment.

The raw ignored artifacts are in:

```text
artifacts/enterprise/postfix-luna-21-v2.report.json
artifacts/enterprise/postfix-luna-21-v2.trace.jsonl
```
