# Northstar relationship-expansion trial

This focused trial closes the most important gap exposed by the retrieval
ablation. A Payments card has one human-approved dashboard anchor. A versioned
company context snapshot says that Fulfillment context is required to interpret
customer-impacting movement. The adapter-owned relationship index expands that
cross-domain neighborhood before Jev ranks candidates.

The product path is:

1. lexical adapter search supplies a bounded starting set;
2. `SourceRegistry.expand_related_resources` asks adapters for a bounded graph
   neighborhood around the card anchor and context endpoints;
3. SignalWeave merges and authorizes both sets without scanning the catalog;
4. Jev ranks the combined candidate set;
5. SignalWeave returns the selected evidence bundle and receipt metadata.

The new adapter method is optional. Existing connectors continue to work, while
graph- or lineage-aware connectors can expose relationship traversal without
SignalWeave owning a knowledge graph.

Run the live proof with:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
PYTHONPATH=src:. \
.venv/bin/python -m evaluations.northstar_relationship_expansion_trial \
  --output artifacts/northstar-relationship-expansion/report.json
```

The trial is intentionally narrow. It proves that explicit company relationships
can recover a neighborhood that lexical search misses and deliver it to Jev. It
does not claim that a single global relevance threshold assembles every
downstream role correctly. The context obligation in this fixture is satisfied
when at least one authorized Fulfillment projection is selected; if a card needs
an owner, quality, and diagnostic projection separately, that requirement must
be explicit in the graph/card contract and evaluated as separate obligations.

## Live result

The live run on 2026-09-22 used one Jev request over a 100,000-resource-per-
adapter virtual catalog:

| Check | Result |
| --- | ---: |
| Lexical search recall for six Fulfillment projections | 0/6 |
| Relationship expansion recall | 6/6 |
| Jev-selected context obligation | 1.0: at least one Fulfillment projection selected |
| Jev-selected projection recall | 1/6 |
| Jev requests / bundle resolution | 1 / 0.775s |
| Native full catalog scans | 0 |

This closes the candidate-coverage gap and proves the graph context reaches Jev.
It also identifies the remaining readiness boundary: the system cannot infer
from “related context” whether a workflow needs one projection or distinct
diagnostic, quality, ownership, and delivery projections. Those obligations
must be human- or graph-authored and then checked as coverage constraints.
