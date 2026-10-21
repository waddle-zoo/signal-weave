# Current whole-agent and release evidence

This is a short current index, not a leaderboard. Failures, timeouts, unknown
usage, overhead, and mixed outcomes stay visible; these bounded journeys do
not establish general superiority. The full historical index is preserved
[here](archive/research/evaluations-2026-10-20.md), with its original
navigation in the immutable [`437ab297` snapshot](https://github.com/waddle-zoo/signal-weave/blob/437ab297bb621c724edc71b138b5ff774759c51f/docs/evaluations.md).

## Latest journeys and release checks

| Study | Result and limit |
| --- | --- |
| [Published rc4 / OpenAI Decisions replay — Oct 19](evidence/openai-decisions-live-2026-10-19.md) | Download/setup, live decision and restart replay; one Codex brief from two existing company cards and authenticated HTTP replay. Known-card outcomes matched 46/48, including all 8 qualifying notify routes. Approval-blocked attempt and TLS failure retained. Not new-company onboarding, external delivery, or an agent advantage. |
| [Meridian onboarding diagnostics — Oct 19](evidence/meridian-onboarding-diagnostics-2026-10-19.md) | 5,000 accounts and 118 assets. Original failures retained. Later treatment authored archival cards and completed two Jev calls, then timed out during recipient follow-through; file presence does not prove attachment use and usage is unknown. One cutoff per study—not eight successful reviews or an accuracy/cost win. |
| [OrbitWorks whole journey — Oct 19](evidence/orbitworks-whole-journey-2026-10-19.md) | Agent-authored SQL/card, owner clarification, six source cutoffs, supported referrals, and final handoff. Treatment sent 0 no-trigger FYIs versus 5 baseline; 15 vs 26 local messages is descriptive, not a human-time or causal win. Two treatment timeouts needed separate recovery; original usage remains unknown. |
| [Northstar current-native journey — Oct 19](evidence/northstar-whole-journey-2026-10-19.md#current-native-fresh-agent-onboarding-through-delivery) | Scripted setup, agent-authored SQL/card, owner read, approval, and three fresh-agent/live-Jev reviews produced five local inbox messages and a feedback investigation. Earlier helper-blocked attempt remains. This forward run is not a new pair and was slower/more token-intensive than its retained baseline. |
| [Harbor whole-company journey — Oct 19](evidence/harbor-whole-journey-2026-10-19.md) | Fifteen source-supported daily packages; stopped at the simulated owner quota with 13 dates unrun. Baseline completed source checks but missed two handoffs. No full-month or superiority claim. |
| [Northstar Superset journey — Oct 19](evidence/northstar-whole-journey-2026-10-19.md) | Seven live-Jev reviews, investigation, nine delivered messages, and twelve readable attachments. Core weekly figures/routes were supported, but messages need less plumbing and one follow-up is redundant. Baseline was faster and used fewer frontier tokens; the original owner-fixture failure remains. |
| [Pine Courier whole journey — Oct 19](evidence/pine-whole-journey-2026-10-19.md) | Three live-Jev observations, five local inbox messages, and feedback. Figures/routes were supported; next-action clarity, recipient-open evidence, and a final-summary attribution remain gaps. Baseline also succeeded faster and with fewer tokens. Original wrapper failure retained; no general advantage. |
| [Published rc5 release gates — Oct 20](local-install-reference.md#startup-measurements) / [release workflow](https://github.com/waddle-zoo/signal-weave/actions/runs/39366963314) | Published rc5 scripted terminal setup, real Codex registration, source-health checks, upgrade, and uninstall passed all three platform gates. Published rc5 provider/MCP smoke was offline. The separate live OpenAI integration reused the same fingerprint as the preceding local build. The new full business journey is still in progress; this is release/integration proof, not business efficacy. |

These reports include simulated owners/recipients and local inboxes where stated;
they are not a real-human usability panel or proof of external Slack/email
delivery. Each report identifies the source, model, and sink that actually ran.

## Earlier mixed paired-period result

The October 13 decision-first study covered 108 paired periods across six
synthetic families: native 108/108, baseline 108/108, treatment 107/108. The
treatment took 3,091.2 seconds versus 2,063.6 seconds (**+49.8%**) despite 36
quiet frontier skips; onboarding/review was excluded and cached-token billing
was unknown. This does not show overall superiority. Separately, a 150,456-byte
(about 50,152-token) Superset payload exceeded a 12,000-token limit, a failure
the then-2,923-test suite missed. See the [retained study record](evidence/agent-workflow-study-2026-10-13.md)
and [full historical index](archive/research/evaluations-2026-10-20.md).

## In progress—not results

The [October 20 workflow-product protocol](../evaluations/protocols/workflow-product-2026-10-20.json)
is staged for execution, not a result. It records planned stages and claim
limits only; this index will be updated after the actual runs.
