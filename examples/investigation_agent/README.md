# SignalWeave investigation agent

This is an optional caller-owned agent showing how to turn SignalWeave's typed
workflow handoffs into a bounded multi-stage investigation:

```text
evaluate card → retrieve authorized evidence → re-evaluate same card → deliver
```

The example is intentionally outside `src/signalweave`. SignalWeave remains the
decision boundary. The agent does not choose the final outcome, invent Slack
destinations, generate SQL, or treat an LLM explanation as evidence.

## What is included

- `agent.py` — the bounded loop and typed extension points;
- `mcp_gateway.py` — a streamable-HTTP MCP client for a deployed SignalWeave;
- `context_tools.py` — a safe JSON fixture loader for local testing;
- `delivery.py` — stdout delivery and an opt-in Slack channel adapter;
- `briefing.py` — an optional caller-owned final-message writer boundary;
- `cli.py` — a small deployable entry point; and
- `fixtures/` — a replaceable sales → campaign → conversion example.

The agent consumes SignalWeave's `workflow.evidence_plan` when it is present.
That plan contains the pending questions, required source keys, and full source
references. The agent's tools execute those requests and return facts tagged
with the slot they fulfilled; the agent does not derive a new investigation
plan from the card prose.

The OpenAI-compatible planner is optional. If configured, it can select among
the caller's already-authorized read-only evidence tools. Its output is a
closed-set list of tool keys. It cannot select an outcome, destination, or
action. Any other OpenAI-compatible gateway can be used by setting its base URL.

## Drafting from approved context

The caller can bridge flat business intent to the existing
`draft_insight_card` MCP tool. `approved_sources` is the caller's bounded
workflow shortlist, not the entire enterprise catalog; every `required=True`
source is included, while optional sources may be omitted. Selectors must match
approved keys exactly, and route destinations come from the approved directory.
The helper returns ordinary kwargs for the existing tool—there is no new MCP
endpoint and no persisted-card input:

```python
from examples.investigation_agent.onboarding import DraftIntent, RouteIntent, draft_arguments

kwargs = draft_arguments(
    DraftIntent(
        title="Sales pulse",
        what_to_watch="Online sales and checkout conversion.",
        why_watch="Help Revenue Operations decide whether to respond.",
        decision_guidance="Investigate material movement; notify only when supported.",
        source_keys=["sales-dashboard"],
        routes=[RouteIntent(destination_key="revenue-operations", outcome="notify")],
    ),
    approved_sources,       # caller-owned bounded shortlist
    approved_destinations,  # caller-owned exact key/label/endpoint directory
)
await existing_mcp.call_tool("draft_insight_card", kwargs)
```

## Run against a deployed SignalWeave

The card must already be onboarded, reviewed, and approved in SignalWeave. The
example fixture is a starting point for onboarding; it is not silently inserted
into the service.

```bash
PYTHONPATH=src python -m examples.investigation_agent.cli \
  --card-id sales-campaign-health \
  --signalweave-mcp-url http://127.0.0.1:8000/mcp \
  --signalweave-token "$SIGNALWEAVE_API_TOKEN" \
  --evidence-file examples/investigation_agent/fixtures/sales-campaign-evidence.json
```

Without `OPENAI_API_KEY` and `OPENAI_BASE_URL`, the agent uses Jev's explicit
`required_source_keys` and the caller-approved tool catalog. With them, it uses
the configured gateway only to narrow that catalog:

```bash
OPENAI_API_KEY=... \
OPENAI_BASE_URL=https://api.openai.com/v1 \
OPENAI_MODEL=gpt-4o-mini \
PYTHONPATH=src python -m examples.investigation_agent.cli \
  --card-id sales-campaign-health \
  --evidence-file examples/investigation_agent/fixtures/sales-campaign-evidence.json
```

The default delivery sink prints the evidence bundle. Slack is explicit and
requires a bot token. Existing-channel posting works without channel creation;
creating the shared channel and inviting members require explicit flags:

```bash
SLACK_BOT_TOKEN=... \
PYTHONPATH=src python -m examples.investigation_agent.cli \
  --card-id sales-campaign-health \
  --evidence-file examples/investigation_agent/fixtures/sales-campaign-evidence.json \
  --slack-channel sales-campaign-health \
  --allow-channel-create \
  --allow-slack-invites \
  --slack-member-id ULEADERSHIP \
  --slack-member-id UMARKETING \
  --slack-member-id USALES
```

The Slack adapter uses one stable channel name, so a retry reuses the channel.
Production deployments should put channel/member policy in a durable, audited
configuration rather than allowing arbitrary model-provided invites.

## Optional final message

After the native report is complete, a caller may provide its own async writer
function to produce concise prose. `build_briefing_writer_input(report,
report_markdown, recipient_keys)` validates the native `InvestigationReport`
and passes only a compact projection of its claims, provenance, coverage,
limitations, outcome/status, configured recipient keys, and known
`source_key`/`comparison_key` refs. It does not send the full report and
Markdown twice. The writer returns only `narrative` plus `citations`; unknown
refs, empty prose, and uncited numeric claims are rejected. The returned
payload archives the exact native report and Markdown, so the writer cannot
choose or rewrite a destination or authoritative result.

This is a message-formatting aid, not an arbitrary prose truth verifier. A
numeric citation makes a claim inspectable but does not prove it, and the
writer must not make unsupported causal claims. Independent review remains
necessary. `ignore` is quiet and does not invoke the writer; partial or blocked
reports retain their warnings visibly in the payload. No external API gateway
is required—the caller owns the async writer and any model configuration.

## Replacing the fixture tools

Replace the JSON tools with bounded adapters for the systems the card names:
warehouse or Trino, BI dashboards, campaign analytics, deployment history,
incident records, and the ownership graph. Each adapter should return
`ContextFact` values with a stable id, a time-aware statement, source URL, and
provenance. The agent executes tools in parallel but still submits one
versioned `ContextSnapshot` to SignalWeave for the next Jev judgment.

When submitted through the public MCP tool, caller-supplied context is marked
`unverified` by SignalWeave. Automatic notification remains blocked until the
same evidence is available through deployment-owned source adapters or a
trusted server-side context provider. This is intentional: the example agent
can gather evidence, but it cannot self-attest that its own retrieval is safe
for an external side effect.

The sample intentionally includes a plausible causal chain, but SignalWeave
should still report it as the best supported explanation—not as proof of
causality—unless the organization's own evidence and policy establish that
stronger claim.

## Deployability boundary

This folder is an example agent, not a replacement for a durable workflow
runner. In production, run it from an existing scheduler, queue consumer, or
agent host and persist the SignalWeave receipt id, run id, context version, and
delivery receipt. The same interfaces can be wired to Codex, OpenAI, an internal
LLM gateway, Slack, Teams, email, or an existing incident system.
