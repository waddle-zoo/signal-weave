# Meridian Cloud: what the larger onboarding trial exposed

This first pair did **not** prove a working recurring workflow. The capable
baseline returned useful provisional analysis; SignalWeave reached two draft
cards but timed out before approval or Jev evaluation. The failed attempt stays
in the [compact record](../../evaluations/data/meridian-onboarding-diagnostics-2026-10-19.json).

## The actual experiment

Meridian is a fictional subscription company with 5,000 accounts, overlapping
revenue/cash definitions, multiple currencies and 118 discoverable assets. Eight
as-known weekly snapshots contain 136,330 source events at the first cutoff and
155,892 at the last. **Only the first cutoff was executed by analysts.**

Both arms used fresh Luna sessions, the same four real read-only company-MCP
tools, source definitions, simulated colleagues and retained workspaces.
Treatment additionally received the checksum-verified native executable, its
bundled skill and documented shared-context extension. No analytical SQL or
card was supplied. The MCP is a custom typed-export source, not a hosted BI
vendor or proof that an arbitrary existing MCP needs no integration work.

| First onboarding attempt | Company tools + Luna | SignalWeave + same tools |
| --- | --- | --- |
| Elapsed seconds | 370.06 | 1,208.10 |
| Completed work | Provisional cash/renewal report and runbook | Two draft cards; no completed workflow |
| Analyst uncached input / output tokens | 115,663 / 42,633 | **Unknown after timeout**, not zero |
| Colleague replies | 3 | 6 |
| Live Jev requests | 0 | 0 |

Baseline colleague calls additionally used 13,535 uncached input / 475 output
tokens. Its checked currency-separated figures matched the raw source, but
owner preferences remained open. Its runbook also claimed an owner question
that the recorded exchanges do not contain. Useful analysis is not completed
onboarding or delivered recurring reports.

## What needs fixing

**A lab capacity error.** The small example MCP's one-million-instruction guard
rejected a normal current-subscription aggregation that direct read-only SQLite
completed in about 26 milliseconds. Independent review reproduced it; valid
optimized raw queries also worked. Thirteen treatment query calls hit this
guard. This is a source-fixture confounder, not a SignalWeave defect, and makes
product cost/UX comparisons from those repairs invalid.

**A real integration diagnostic gap.** The agent registered a new query locator
but supplied an underlying table locator as the reader's returned resource.
Native inspection correctly rejected the mismatch, but named no offending
field. Diagnostics now identify constant field names without returning remote
values. The guide explains identity arguments, the existing MCP-manifest CLI
path, compact reviews, and advisory versus policy-critical context. No identity,
tenant, source-scope or approval check was removed.

**An incomplete human conversation.** The baseline's first answer left choices
for the requesting owner. A real person could answer; the original next scripted
request instead assumed agreement. The separately frozen forward method adds an
actual owner reply and analyst continuation at the same cutoff, with shared
budgets. The owner may explicitly delegate exact technical/card review to the
data expert after intent and scope are clear—not invent policy or authorize
scheduling/external sends. First useful findings should not wait for completed
card setup.

## Review and claim boundary

Independent internal data, product and process reviews checked source integrity,
actual communication and trial validity. The source reviewer recomputed all
eight snapshots and renewal populations from raw tables; that validates the
reference, not eight successful agent reviews. Admission for unstarted waves
was withdrawn; the original admission, timeout and unknown usage remain intact.

The next run is forward testing, not a rescore or external peer review. This
pair establishes neither Jev decision accuracy nor an enterprise, speed or cost
advantage. Evaluating delivered work and separately checking simulated-human
fidelity follows [agent-evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
and the concern studied by [UserProxyBench](https://arxiv.org/abs/2609.38043).
