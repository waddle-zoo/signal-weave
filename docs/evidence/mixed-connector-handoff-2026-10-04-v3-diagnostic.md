# Mixed-connector handoff v3 diagnostic

This run is retained as a failed integrity artifact, not as a product win.
It used live Jev and the saved-login Luna agent across three synthetic
companies, three monitoring periods per company, noisy connector catalogs, and
push-gated treatment. Both arms used the same owner brief and the same
connector-shaped sources.

The SignalWeave arm completed onboarding for all three companies and scored
9/9 exact monitoring runs. The agent-only arm completed onboarding for 2/3
companies; its third onboarding episode exhausted the synthetic owner-review
correction path after preserving unsupported source notes, so the paired
monitoring denominator was incomplete. The mechanical reviewer therefore
correctly rejected the report for a value claim.

The useful finding is the gap: the baseline agent can loop on an owner-review
rejection and end without a structured completion, while the Jev-assisted arm
found a usable source path in the same noisy catalog. That is evidence for an
onboarding reliability problem and a possible retrieval advantage, not proof of
overall superiority. A valid claim requires a later complete paired run with
both arms finishing onboarding under the same retry and correction budget.

Raw report: `/private/tmp/signalweave-mixed-connector-handoff-v3-20261004/report.json`.

Mechanical review: `/private/tmp/signalweave-mixed-connector-handoff-v3-20261004/review.json`.
