# Internal adversarial code review

Two Luna worker agents reviewed separate changes, then cross-reviewed the other
paths. These are internal reviews, not external peer review. No reviewer's opinion
changes a failed live result.

The initial review found and required fixes for:

1. Current evidence capture could be used to request acceptance certification.
   Capture plus `acceptance_outcomes` now fails before fetching; current capture
   remains a tagged shadow check.
2. Workflow evaluation lost the authenticated principal before dynamic follow-up.
   The evaluator now propagates it through the real engine and source registry.
   A regression includes a foreign descriptor and checks tenant filtering before
   Jev selection and authorization of the resolved follow-up.
3. Selected-source authorization occurred after paid ranking. Explicit refs now
   undergo authorization preflight, and unauthorized selections use no Jev call.
4. Extra source-input fields were silently discarded. The public schema now
   rejects them; source contracts remain adapter-owned.

The reviewers supported the limited frozen probe after these repairs, not
enterprise readiness. The probe subsequently failed: one of two treatment setups
and two of six intended native outcomes/recipient pairs passed.

A follow-up review confirmed the generic numeric-binding defect: the card's
`contribution` selector means an individual segment (or any matching segment),
not aggregate within-group deterioration. The author-supplied label cannot alter
that executable meaning. This finding motivated the separate v3 repair and trial;
the v2 cards/results were not edited.

The frozen source hash check matched all 16 recorded source files to revision
`4440c19fd02dd772dec58cd28206e5d3dcba5d9c`. Seven tests still expected the older
ignored-field or late stale-review error behavior. They were retained in the
recorded full-suite result and updated only after the probe finished. Their new
expectations require strict rejection, not weaker permission checks.
