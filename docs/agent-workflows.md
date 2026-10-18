# Use SignalWeave with your agent

SignalWeave keeps a reviewed brief, reads its approved sources, and returns a
typed policy decision with evidence. Your agent does the deeper analysis and
writes the explanation. This guide uses the normal `agent` profile over local
stdio or a deployed HTTP service.

That profile limits SignalWeave's tools, not the whole agent. Keep your other
authorized BI, glossary, company-knowledge and owner-clarification tools connected
for onboarding as well as investigation.

The confidence floor gates business conclusions (`ignore`, `notify`, `escalate`).
A selected `insufficient_data` or `investigate` result remains a review handoff
with its original support and configured owner; low support must not silently
swap a data-quality owner for a business-investigation team. Neither handoff
proves the underlying analysis is correct or grants permission to send a message.

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

Keep the clarification focused on the workflow you want. For example:

> Watch the overall service SLA. Tier breakdowns help explain it; they are not
> separate alerts. If either week isn't comparable, tell Data Operations rather
> than claiming the business got worse.

The agent should preserve that scope, not expand it into unrequested alert
rules. It can show supported current findings while noting what still needs
clarification before unattended delivery. That does not approve a card, make
an invalid comparison usable, or authorize a message.

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

Ordinary BI sources need not publish SignalWeave-specific metric contracts to
support this owner-reviewed path. Missing adapter definitions or comparison
windows remain explicitly **unverified**; your reviewed card preserves business
meaning, not a fabricated source guarantee. Adding intended recipients does not
turn approval into delivery permission. Known incompatible windows, source
permissions, health checks and explicit required-comparison bindings still apply.
Before unattended delivery, separately test the actual workflow against the
owner's examples, including partial periods and missing context, and authorize
the caller's delivery tools. Do not treat an approved card or a high-confidence
judgment as that proof.
`onboarding_warnings` on an approved card retain the setup review's caveats
without its large catalog audit. They are historical review findings, not fresh
measurements; check each run's `source_contracts` and evidence as well.

Describe business states in the policy: “notify Operations when an approval has
been pending for more than 36 hours” is a valid condition, not automatically a
source failure. If a fact is instead a prerequisite for the decision—such as
whether an exception was approved for this period—make that a required question
or comparison. Raw field names like `status` do not establish that distinction.

For example:

> Use my answers to prepare the recurring card. Show me its exact sources,
> required evidence, optional context, comparison period, decision rules and
> recipients, then review it. Do not approve or send anything until I confirm.

When a review returns `approval_handoff`, the agent can show the exact declared
scopes and populations, then reuse the supplied approval arguments after you
confirm them. You can answer in ordinary language; the agent records the
confirmed choice and reason rather than asking you to write API fields.
The supplied fingerprint binds your reply to the reviewed snapshot. If the card
changes while you are reviewing it, the agent must show the change and ask again;
it must not substitute the latest stored review for the one you saw.
The handoff does not supply consent or waive
checks. A vague population label still needs clarification, even if the metric
definition looks right. The agent should give you supported findings while that
question remains open, keeping the recurring card in draft rather than treating
the initial readout as approved automation.

After reviewing the draft, give explicit approval only if it is correct:

> Yes, I approve this card with the displayed source scope and policy. Run one
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

Before enabling unattended delivery, ask your agent to check meaningful contrasts
against the saved policy: something that should get attention, something that
should stay quiet, and a material data gap. Add an exception or boundary when it
matters to your rule. The agent should prepare the technical work and show the
evidence and proposed messages; you supply business intent, not fixtures or API
fields. A written example is not an executed evaluation. The normal profile can
evaluate the connected evidence, but cannot replay hypothetical snapshots. If
replay tools are unavailable, keep untested behavior in shadow review rather than
claiming automation is ready. Useful current answers need not wait for that.

## 5. Repeat and investigate

Compact results keep one copy of identical evidence and plans. A report's
`evidence_ref` or workflow's `evidence_plan_ref` identifies that canonical
`result_path`. Use the inline section when available; page that path through
`get_decision_receipt` only for omitted detail. Full responses and saved receipts
retain the original report and workflow structure.

Compact `report` checks describe the generated engine-comparison report, not the
quality of your agent's separate analysis. They retain material blockers,
warnings and source checks without generic report boilerplate. Use measurements
from evidence, observations and analyses; an empty generated numeric-claim list
does not erase them. `report.full_report_ref` identifies the unchanged full
report in the receipt for audit or explicit report requests.

For a later run, ask the agent to evaluate the approved card for the current
period. Each distinct run needs a new stable idempotency key; reusing a key
replays its saved receipt rather than refreshing evidence. Read the typed
decision together with the evidence, including source coverage, dates and
comparability. Missing or omitted evidence is not an all-clear.

For a known approved card backed by saved BI or configured query sources, that
evaluation is the starting call—not another
onboarding. It includes the active policy, follow-up guidance and current source
evidence. Use the guide or full card history only when orientation, a change or
an audit actually needs it. Keep your ordinary workspace notes, files and other
authorized company tools available for follow-up.

Some checks need calculations outside the saved dashboard. With an already
connected [analyst publication](../examples/analysis_publication/README.md), the
calling agent must refresh that evidence **before** evaluating the card: rerun
its retained queries/calculations for the requested period, retain the inputs,
and atomically replace the configured file with compact findings and lineage.
SignalWeave reads that file; it does not perform the refresh. The agent should
explain this once: “I'll reuse the saved analysis, refresh its evidence, then
apply your approved policy.” The owner reviews business choices, not file formats.
The one-time connection still requires operator setup. Without that connection
and an actual working refresh procedure, the analysis may be useful but the
recurring check is not ready. Suitable saved BI sources do not need this extra path.

Make the question's clock clear. A current monitor needs current source evidence;
a historical investigation needs the requested **as-of date** and measurement
window. For example: “Repeat our delivery review using the data visible as of
June 22, and follow up the prior cases as of that date.” Do not turn that into a
search for today's production data, or present a historical receipt as a fresh
monitoring result. Keep material source limitations visible in either case.

Use the evidence already returned by evaluation. Fetch `get_decision_receipt`
only to recover a saved run, page omitted evidence or inspect the full audit.
Its `receipt` contains metadata; `result` contains the stored evidence once.

If the result calls for investigation, the agent should use its own authorized
BI or company tools to check the relevant segments, calculations and competing
explanations, then write a concise, source-linked account of what is known and
what remains uncertain. Jev supplies a narrow typed judgment, not a calculator,
causal analyst, or user-facing explanation. Do not silently add investigation
sources to the recurring card; ask for an owner-reviewed card update if those
sources should be read on future runs. Scheduling and external delivery belong
to separately authorized caller tools, not SignalWeave.

That card update is for **SignalWeave's own** automatic reads and policy inputs,
not every query the calling agent performs. For example, an aggregate may answer
whether any priority work crossed its clock; the agent can use its already-
authorized company SQL tool to retrieve the affected records for the handoff.
It need not add each detail query to the card first. Keep those findings source-
linked and distinct from what the policy provider actually judged. New tool
access, query cost and actual delivery still need their normal authorization.

For the human readout, lead with the supported finding and the caveat that changes
its interpretation. Cite the actual source URL or exact `adapter|resource`
reference—not just the decision receipt—and finish with the smallest justified
next check, or say that no action is needed. The rendered report includes a
bounded source-reference overview and the full reference list in its appendix.
These locators help inspect current assets; the receipt preserves the run's
evidence. They do not prove that an interpretation or causal explanation is true.

Keep the message distinct from the supporting detail. Your agent can use its
ordinary file or delivery tools to provide a record list or chart the recipient
can actually open; a private receipt or transient export label is not that link.
Summarize the finding, scale and next action in the message. If no accessible
detail path exists and the handoff requires record identifiers, include what is
needed inline rather than claim an attachment was delivered. When a follow-up
concerns a previously affected group, inspect its current state when possible: a lower
aggregate does not explain what happened to those records or why.

Use source-provided exports or downloads for supporting rows when available.
Calculate derived tables from those originals rather than manually rebuilding
them in the response. Keep the exact query, source and measurement window with
the evidence. Check the final message against it too: a checksum cannot validate
an invented explanation, an unknown expectation or a copied denominator.
The [example company MCP](../examples/harbor_help/README.md#source-backed-files)
offers an opt-in local export tool; your BI tool may provide its own downloads.
These are caller/source capabilities, not another SignalWeave approval step.

`insufficient_data` limits the affected policy conclusion, not every useful
answer. The agent can still report supported facts and investigate through its
authorized BI tools. If the card maps that outcome to a data-owner route, the
handoff permits only that configured data-gap notice; it does not become a
business-regression alert. Caller-submitted findings remain unverified for
automatic policy routing. For a new policy decision, fetch updated approved
source evidence or use a trusted runtime context provider—do not repeatedly
resubmit the same caller context expecting it to become trusted.

When the optional domain-context tools appear in the connected guide, agents can
reuse reviewed definitions and dated findings across cards and poll for review
reminders. See [shared domain context](domain-context.md). This does not replace
current source evidence, card approval, or workflow certification.

## Choose alerting or routine reporting

These are different jobs. For alert-only monitoring, your existing runner can
call SignalWeave directly through the CLI or MCP; it need not start a frontier
agent just to obtain the card's typed judgment. Hand actionable evidence to the
agent for investigation and a focused message. With Jev configured, that policy
step uses Jev; it does not invoke Codex or Claude itself.

| Requested job | Valid result | Caller behavior |
| --- | --- | --- |
| Alert only | `ignore` | Keep the receipt; do not start an investigation or send an alert |
| Alert only | Needs attention or more evidence | Give the agent the evidence and relevant stored context to investigate |
| Routine report | Including a quiet business period | Prepare the requested report; `ignore` does not cancel the separate reporting request |

A deferred judgment, changed required context or unavailable evidence is not
quiet success. Inspect current action availability and source limitations before
routing work. Scheduling and sending still require separate authorization in
your caller-owned runner. This pattern does not establish measured savings:
source-query cost and frontier work depend on the workflow. Evaluations that
always generate a report cannot measure the benefit of suppressing quiet alerts.
