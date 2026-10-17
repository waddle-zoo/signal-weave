# Juniper Trail Retail: fictional source-steward declaration v1

This is additional simulation input supplied by the fictional data steward,
not an inference, a real customer's attestation, a card, or permission to act.

For Commerce weekly (`company_mcp|resource-949a4c0c44fb188d1658`), the glossary's
`net_sales` definition is the controlling scope: completed-order gross revenue
less refunds posted in the same reporting week, excluding tax and shipping.
There are no additional customer, region, eligibility or pilot filters on this
export beyond that definition. Web and shop are its disjoint sales channels;
booked or cancelled order value is not recognized sales. The generic population
label “Eligible entities in the source glossary” refers to this scope, not to an
additional unspecified cohort.

For that source, `previous_period` maps to `company-metric-glossary#/definitions/comparison`:
the previous complete reporting week, with source intervals in UTC. Each run
must use its actual reported measurement intervals, coverage and comparability.
Historical onboarding examples do not attest to later source freshness,
completeness, refund timing or values.

Returns operations (`company_mcp|resource-00dc1bfdfad5f5f05554`) is point-in-time
refund-posting metadata, not a second monetary ledger. It does not share a
transaction population merely because the sources are related. Use it within
its own stated scope as corroboration; do not add or subtract its records from
Commerce weekly's amounts or treat its presence as proof of current quality.

This declaration supplies no alert threshold, destination, outcome, current
measurement or causal explanation. Ask the business owner for action policy.
Save and show the proposed artifacts; consent, context review and card approval
are separate steps. No sending or scheduling is authorized here.
