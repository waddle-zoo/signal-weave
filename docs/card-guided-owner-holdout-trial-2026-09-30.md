# Card-guided owner holdout — 2026-09-30

This is the stronger follow-up to the 1,000-chart retrieval trial. It uses a
separate six-case catalog and a separate owner-label file. The owner labels are
loaded by the evaluator only; they are not included in the cards, chart
metadata, snapshots, retrieval query, or Jev state.

Run it with:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  .venv/bin/python evaluations/card_guided_owner_holdout.py \
  --typesafe-key-file /absolute/path/to/apikey_typesafe \
  --output artifacts/card-guided-owner-holdout.json

.venv/bin/python evaluations/card_guided_owner_holdout_adversarial_review.py \
  artifacts/card-guided-owner-holdout.json
```

## Live result

The run used live Jev over six new operating situations and 1,000 catalog
entries per situation. Each card explicitly defined its evidence semantics in
human language: focal signal, corroboration, diagnostic context, quality
checks, and contradiction/benign context.

| Measure | Jev card-guided | Lexical selection + Jev | Gold selection + Jev |
| --- | ---: | ---: | ---: |
| Retrieval precision | 94.4% | 50.0% | 100.0% |
| Retrieval recall | 100.0% | 100.0% | 100.0% |
| Outcome accuracy | 100.0% | 83.3% | 100.0% |
| Promoted evidence-role accuracy | 100.0% | 100.0% | 100.0% |
| Driver recall | 100.0% | 100.0% | 100.0% |
| Median end-to-end latency | 1,904 ms | 1,146 ms | 979 ms |
| Jev requests | 30 | 18 | 18 |
| Estimated TypeSafe cost | $0.0249 | $0.0163 | $0.0121 |

The lexical arm had access to the same catalog and cards but selected sources by
word overlap. The gold arm isolates the final Jev decision from retrieval. The
guided arm therefore demonstrates the product path: card meaning plus bounded
Jev retrieval plus typed decisioning.

## Adversarial process result

`card_guided_owner_holdout_adversarial_review.py` passed every gate:

- live Jev model identity;
- six cases at 1,000 catalog entries each;
- guided retrieval precision and recall;
- guided and gold outcome accuracy;
- evidence-role accuracy and driver recall;
- non-empty evidence for the no-alert case;
- independent owner-label source;
- scenario-label verification against the separate label file; and
- aggregate recomputation from per-case rows.

The first run of this holdout intentionally exposed an onboarding gap: the
support card said “within the operating range” without defining the range. Both
the guided and gold arms correctly recognized the ambiguity but returned
`investigate` instead of the owner's intended `ignore`. After the card added an
explicit 10% tolerance, the rerun reached 100% outcome accuracy. That is a
card-authoring requirement, not a hidden SignalWeave heuristic.

## What this proves—and what it does not

This is strong synthetic, live-provider evidence that explicit human context
lets SignalWeave retrieve and package the right evidence at catalog scale, then
execute the defined workflow without a free-form reasoning model.

It does not prove production causal inference or replace owner review. The next
real-world gate remains a time-split replay using labels from an actual team,
with usefulness, noise, timeliness, and wrong-recipient labels collected
outside Jev.
