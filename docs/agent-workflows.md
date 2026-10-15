# Use SignalWeave with your agent

SignalWeave keeps a reviewed brief, reads its approved sources, and returns a
typed policy decision with evidence. Your agent does the deeper analysis and
writes the explanation. This guide uses the normal `agent` profile over local
stdio or a deployed HTTP service.

That profile limits SignalWeave's tools, not the whole agent. Keep your other
authorized BI, glossary, company-knowledge and owner-clarification tools connected
for onboarding as well as investigation.

For supported builds and upgrades, see
[release compatibility](local-install-reference.md#release-compatibility).

## 1. Set up the connection

Install and configure SignalWeave using the [laptop setup guide](local-install.md).
Run `signalweave setup`, choose the decision provider and source connections,
and connect Codex or Claude when setup offers. After registration, setup offers
to install the bundled workflow skill for that client in your user scope. If you skipped registration,
run `signalweave connect codex` or `signalweave connect claude`, then restart or
reconnect the agent. Keep credentials in the private setup prompts or files;
do not put them in an agent prompt. The skill install below does not register
the MCP server.

## 2. Use the bundled skill

If you accepted the setup offer, the skill is already installed for your client.
You can also install it explicitly, or keep a project-local copy instead:

```sh
signalweave skills install --agent codex --scope project
# or
signalweave skills install --agent claude --scope project
```

These commands install only the project-local skill. Add `--scope user` for a
client-wide install. `signalweave skills show` prints
the canonical content. If an existing project skill differs, installation
refuses to replace it; inspect and resolve that conflict deliberately.

## 3. Ask for a first readout

Start with one useful current readout, not a card approval. In Codex, invoke
`$signalweave`; in Claude, ask it to use the installed SignalWeave skill. For
example:

**Sales**

> Use `$signalweave` to explain what changed in online sales and how it affected
> total sales. Show the evidence and ask me about any business context you need.

**Customer health**

> Use `$signalweave` to review customer health. Which accounts need attention,
> and what supports that? Help me define a weekly digest for Customer Success.

**Operations**

> Use `$signalweave` to check for customer-impacting service regressions. Connect
> the related signals before suggesting a page; an isolated CPU spike is noise.

The skill supplies the analytical checks behind these short requests. The agent
should return a useful first readout, explain any uncertainty, and ask about the
business rules needed for repetition. You do not need to write JSON or guess
dashboard IDs. It still asks before approving a card or sending a message.

## 4. Clarify, review, then approve

Answer the agent's material questions in ordinary language. Then ask it to
prepare a draft card that preserves your definitions, comparison window,
required versus optional sources, quiet behavior, and outcome-to-recipient
rules. Have it show the exact source scope and run the available review. Fix
mistakes before approval. In the normal profile, a draft is not a trial: approve
only after you have reviewed it and explicitly authorize the saved card.

If you answer a question after a draft was saved, the agent can use
`revise_insight_card` to apply your clarification to the same card. It keeps the
source anchors, increments the version and returns it to draft; review and
approval must happen again. Old receipts remain history. Revision does not
approve the card or activate automation. Check your connected tool list on older
builds; without this operation a replacement draft must be reviewed explicitly.

Normal agent responses omit historical review/correction packets from the
revision receipt while preserving active policy, exact source scope, version and
context pins. For the audit, use
`get_insight_card(include_history=true, response_mode="full")`. The full profile
defaults to full revision responses; either profile accepts an explicit mode.

An approval-ready onboarding response uses `next_action="confirm_then_approve"`.
The default profile does not require a hidden simulation tool before approval;
its first delivery-disabled evaluation follows explicit owner approval. That
single check is not certification for unattended operation.

For example:

> Use my answers to prepare the recurring card. Show me its exact sources,
> required evidence, optional context, comparison period, decision rules and
> recipients, then review it. Do not approve or send anything until I confirm.

When a review returns `approval_handoff`, the agent can show the exact declared
scopes and populations, then reuse the supplied approval arguments after you
confirm them. It adds your reason; the handoff does not supply consent or waive
checks. A vague population label still needs clarification, even if the metric
definition looks right. The agent should give you supported findings while that
question remains open, keeping the recurring card in draft rather than treating
the initial readout as approved automation.

After reviewing the draft, give explicit approval only if it is correct:

> I approve card `<card-id>` with the displayed source scope and policy. Run one
> delivery-disabled evaluation and show me the result and receipt; do not
> schedule a recurrence or send a message.

Review the proposed message as well as the decision. Does it answer your question,
fit its intended reader, and make the important scope and data gaps clear? You or
your designated data expert can give that feedback. A team that knows the metric
may prefer a short update; a new audience may need its definition spelled out.
Keep business purpose in the card's `why_watch` and presentation preferences in
the agent's notes; reviewed domain context is another option when those tools are enabled.
These expectations are not fresh measurements or permission to change policy, send a
message, or start a schedule. Card changes still need the normal review and approval.
This example helps qualify onboarding; it does not prove every future run.

## 5. Repeat and investigate

For a later run, ask the agent to evaluate the approved card for the current
period. Each distinct run needs a new stable idempotency key; reusing a key
replays its saved receipt rather than refreshing evidence. Read the typed
decision together with the evidence, including source coverage, dates and
comparability. Missing or omitted evidence is not an all-clear.

If the result calls for investigation, the agent should use its own authorized
BI or company tools to check the relevant segments, calculations and competing
explanations, then write a concise, source-linked account of what is known and
what remains uncertain. Jev supplies a narrow typed judgment, not a calculator,
causal analyst, or user-facing explanation. Do not silently add investigation
sources to the recurring card; ask for an owner-reviewed card update if those
sources should be read on future runs. Scheduling and external delivery belong
to separately authorized caller tools, not SignalWeave.

When the optional domain-context tools appear in the connected guide, agents can
reuse reviewed definitions and dated findings across cards and poll for review
reminders. See [shared domain context](domain-context.md). This does not replace
current source evidence, card approval, or workflow certification.
