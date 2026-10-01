# Northstar Outfitters: the week the dashboard changed

A compact, blog-focused SignalWeave replay over four situations a business actually cares about.

The card watches revenue, sales channels, web conversion, support pressure, and finance. Jev decides whether the evidence should notify leadership, queue an investigation, suppress the noise, or route a source failure to data trust.

**4/4 scenarios matched the authored operating policy.**

## Revenue is down everywhere, not just in one chart.

This is the kind of movement that deserves a leadership push with the evidence attached.

| Signal | Movement |
|---|---:|
| Net sales revenue | -22% |
| Net sales — Marketplace | -16% |
| Net sales — Mobile | -20% |
| Net sales — Online | -24% |
| Net sales — Store | -18% |
| Web conversion rate | -15% |
| Support backlog | +28% |
| Finance booked revenue | -21% |

**Movement-only route:** `notify`
**SignalWeave + Jev:** `notify` → `leadership`
**Confidence:** `0.96` · **Evidence:** `13 items` · **Latency:** `278.73 ms`

> Evaluated 9 observations across 4 sources; 5 watch items and 4 questions were checked.

> Jev evaluated the card's typed watch, question, and outcome judgments; selected=notify, support=0.96.

## Mobile conversion collapsed while the rest of the business held steady.

A severe mobile funnel failure deserves a leadership push with the affected surface attached, even though the other channels are holding steady.

| Signal | Movement |
|---|---:|
| Net sales revenue | -17% |
| Net sales — Marketplace | -3% |
| Net sales — Mobile | -42% |
| Net sales — Online | -4% |
| Net sales — Store | -2% |
| Web conversion rate | -31% |
| Support backlog | +22% |
| Finance booked revenue | -16% |

**Movement-only route:** `notify`
**SignalWeave + Jev:** `notify` → `leadership`
**Confidence:** `0.91` · **Evidence:** `13 items` · **Latency:** `306.43 ms`

> Evaluated 9 observations across 4 sources; 5 watch items and 4 questions were checked.

> Jev evaluated the card's typed watch, question, and outcome judgments; selected=notify, support=0.91.

## Every channel softened, but nothing crossed the team’s action boundary.

A dashboard movement is not automatically a leadership problem. This should be suppressed without waking an agent for a deep analysis.

| Signal | Movement |
|---|---:|
| Net sales revenue | -8% |
| Net sales — Marketplace | -8% |
| Net sales — Mobile | -8% |
| Net sales — Online | -8% |
| Net sales — Store | -8% |
| Web conversion rate | -4% |
| Support backlog | +2% |
| Finance booked revenue | -7% |

**Movement-only route:** `ignore`
**SignalWeave + Jev:** `ignore` → `no delivery`
**Confidence:** `0.99` · **Evidence:** `13 items` · **Latency:** `382.1 ms`

> Evaluated 9 observations across 4 sources; 5 watch items and 4 questions were checked.

> Jev evaluated the card's typed watch, question, and outcome judgments; selected=ignore, support=0.99.

## The dashboard stopped reporting. Do not invent a business story.

A missing source is a data-trust incident, not evidence that revenue moved.

| Signal | Status |
|---|---|
| Executive dashboard | unavailable |

**Movement-only route:** `ignore`
**SignalWeave + Jev:** `insufficient_data` → `data-trust`
**Confidence:** `0.95` · **Evidence:** `15 items` · **Latency:** `297.6 ms`

> Evaluated 9 observations across 4 sources; 5 watch items and 4 questions were checked.

> One or more required card sources were unavailable, so no automatic interpretation is safe.

## What this shows

A movement-only alert can tell Northstar that revenue moved. SignalWeave gives an agent the business context to decide what the movement means and what should happen next.

The same card handles a company-wide revenue problem, an isolated mobile funnel failure, ordinary movement, and a broken source without turning every case into a leadership notification.

This is a local Northstar fixture and a reviewable simulation. The value being demonstrated is the decision boundary: humans define what matters, Jev interprets the bounded evidence, and the caller-owned agent receives a route it can act on.
