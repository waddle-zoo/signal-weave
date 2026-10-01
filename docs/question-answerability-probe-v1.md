# Question answerability probe v1 — preregistration

Research-only paired diagnostic following the failed owner-reviewed v4 trial.
No new production gate, source permission, threshold or owner policy is added.

Hypothesis: the current Noul mixes an answer-existence instruction with the
original question as its true criterion. This can conflate a known negative
answer with no available answer. Its `questions[index]` reference is also not
a root field of runtime state. These are question-contract defects; the retained
v4 probabilities do not prove how much they caused its failures.

Compare the exact current template with one candidate that embeds the question
directly in instructions and aligns both criteria with answer existence. A
concrete no, zero or absence counts as an answer; missing, conflicting or
inapplicable evidence does not. Do not infer completeness from a resource title,
healthy status or list alone. Do not infer causation from timing.

Twenty synthetic development cases: four domains (support denominator, release
rollback, finance approval, cluster coverage) with affirmative, negative,
missing and conflicting answers, plus partial compound-question evidence,
wrong population, precomputed numeric answer and unestablished causal explanation.
These are hand-designed diagnostic controls, not random enterprise holdouts.

Each case makes one request batching both templates on exactly the same state.
Labels and fixture IDs remain outside that state. Retain inputs, both questions,
raw probabilities, valid/invalid status, resolved model, usage and request time.
Fixed existing thresholds: at least .70 is supported, at most .30 is not_supported,
otherwise unknown. Invalid/missing responses cannot pass. There are no retries
or deliveries; maximum 20 requests; incomplete runs remain failures. Preserve
reservations before dispatch and keep error messages secret-safe.

Freeze code, fixture, tests and this declaration after preflight review. Run once
into exclusive `artifacts/question-answerability-v1-01`. Do not edit or repeat
for favorable outputs. Primary diagnostics: supported/not-supported correctness
for both templates, false support on unanswerable cases, and false refusal on
known-negative answers. Candidate must pass all twenty cases with no false
support to justify a production integration experiment; this is a development
gate, not a reliability estimate. Report unknown answers separately, not as
semantic detection. Keep failures and unchanged thresholds.

Even passing would not prove the full-card judgment improves: smaller states and
only two questions differ from runtime state and fan-out. A subsequent frozen-card
regression must test actual runtime behavior before any comparative benefit claim.
The Cinder list-only coverage ambiguity and endpoint mismatch require separate
source-contract and exact-directory handling, not answerability prompt tuning.

Design references: [TypeSafe Noul](https://docs.typesafe.ai/primitives/noul),
[answer-existence cookbook](https://docs.typesafe.ai/cookbooks/semantic_find),
and [Jev 1.13 limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).
