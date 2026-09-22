# Card-guided retrieval at dashboard scale

This is the product-shaped retrieval trial for the Jev path. It does not send
1,000 raw chart observations to Jev. Each case contains 1,000 chart
descriptors, an adapter-owned catalog search, a bounded Jev candidate pool, and
chart snapshots materialized only after selection.

The card supplies the English business rule. Jev ranks catalog candidates
against that rule, then SignalWeave evaluates the selected evidence with the
same card. The lexical arm uses the same final Jev decision stage but selects
charts lexically. The gold arm uses evaluator-only selections to isolate the
final decision stage from retrieval.

## Live run

Six synthetic dashboards were run with live Jev calls. Each had 1,000 chart
descriptors, four or fewer meaningful charts, and unrelated noise. The
catalog metadata contained titles, metric definitions, operating areas, and
relationships; evaluator labels were not sent to Jev.

| Measure | Jev card-guided | Lexical selection + Jev | Gold selection + Jev |
| --- | ---: | ---: | ---: |
| Retrieval precision | 87.5% | 29.2% | 100.0% |
| Retrieval recall | 87.5% | 70.8% | 100.0% |
| Retrieval F1 | 80.0% | 39.8% | 100.0% |
| Final decision F1 | 68.6% | 72.1% | 73.0% |
| Driver recall | 33.3% | 66.7% | 33.3% |
| Outcome accuracy | 33.3% | 33.3% | 50.0% |
| Median latency | 3,068 ms | 1,869 ms | 1,637 ms |
| Estimated cost | $0.0223 | $0.0145 | $0.0101 |

The retrieval result is useful: Jev-selected candidates were much more precise
than lexical selection and materialized fewer irrelevant charts. It is not a
finished enterprise result. The growth case retrieved only one of four
meaningful charts, and even gold selection produced only 50% outcome accuracy.
The final decision stage still needs stronger graph context and owner-labeled
card rules.

## What this proves

- SignalWeave can keep Jev away from an unbounded raw-chart payload.
- A human-authored card can guide semantic candidate selection over a noisy
  catalog.
- Jev ranking improves precision over lexical selection in this fixture.
- The final evidence decision remains inspectable and separately measurable.

## What it does not prove

This is a synthetic adapter and a single live run. It does not establish
catalog recall for Superset, Looker, Hex, Trino, or a real knowledge graph. It
does not prove query-cost savings, production correctness, or autonomous
delivery. The current outcome result is explicitly not good enough to claim
that the full mass-insight workflow is solved.

The next meaningful trial should use real or owner-labeled graph edges,
time-split dashboard snapshots, adapter query telemetry, and a larger set of
cards with known useful-chart sets. It should measure candidate recall,
materialized-query count, query seconds/bytes, evidence recall, useful-alert
rate, and unsafe delivery rate separately.

## Reproduce

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
PYTHONPATH=src:. \
.venv/bin/python -m evaluations.card_guided_retrieval_benchmark \
  --typesafe-key-file /absolute/path/to/apikey_typesafe \
  --repeats 1 \
  --max-candidates 40 \
  --retrieval-limit 12 \
  --selection-cap 8 \
  --output artifacts/card-guided-retrieval-1000.json
```
