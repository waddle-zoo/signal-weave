# Helio connected-Preset-MCP paired trial

Date: 2026-10-04
Model: \`gpt-5.6-luna\`
Run report: \`/private/tmp/helio-preset-mcp-paired-20261004.json\`
Trace: \`/private/tmp/helio-preset-mcp-paired-20261004.jsonl\`

## Question

Does a Luna agent using the same human-authored Helio card and connected
Preset-MCP source catalog perform better with a SignalWeave Jev preflight than
with direct source discovery and analysis?

The treatment difference was limited to one typed Jev retrieval preflight. Both
arms received the same tenant, permission scope, cached Preset chart
observations, source contracts, final submission schema, and model. Jev did
not receive a hidden label or an outcome instruction.

The fixture contains three periods:

1. complete and below threshold: \`ignore\`;
2. complete and above the weighted-rate threshold: \`notify\` Support Quality; and
3. a partial channel partition: \`insufficient_data\` to Support Data.

The reproducible case file is
\`evaluations/data/helio-preset-mcp-cases.json\`.

## Result

| Metric | Luna + connected Preset-MCP tools | Luna + SignalWeave/TypeSafe preflight |
| --- | ---: | ---: |
| Exact decisions | 3/3 (100%) | 3/3 (100%) |
| Unsafe automatic actions | 0/3 | 0/3 |
| Required-evidence recall | 100% | 100% |
| Complete provenance | 3/3 | 3/3 |
| Median end-to-end time | 5.153 s | 4.175 s |
| Diagnostic-query calls | 1 | 0 |
| Jev requests | 0 | 3 |
| Jev input/output tokens | 0 / 0 | 7,871 / 285 |
| Oracle-field exposure | 0 | 0 |

Per-case outcomes matched exactly:

| Case | Expected | Agent-only | Jev-assisted |
| --- | --- | --- | --- |
| Complete, below threshold | \`ignore\` | exact | exact |
| Complete, above threshold | \`notify\` → Support Quality | exact | exact |
| Partial channel partition | \`insufficient_data\` → Support Data | exact | exact |

The direct agent performed one bounded diagnostic on the partial result. It was
not needed to reach the safe outcome and returned no additional bytes or CPU
work in this fixture. The Jev preflight classified the same evidence as
reusable, so the treatment did not issue that query. This is a useful
orchestration result, not proof that Jev is more correct than Luna.

## Interpretation

This trial does not support a claim that SignalWeave improves decision quality
on already well-curated, compact Helio inputs. Luna alone matched the policy
perfectly. The defensible value shown here is:

- a typed preflight can suppress a redundant diagnostic step;
- the downstream agent still applies the human-authored policy;
- incomplete Preset evidence remains an explicit safe abstention rather than a
  notification; and
- Jev's weighted source probabilities are useful as retrieval context, not as
  causal reasoning or a replacement for the frontier model.

The treatment adds Jev work. It should only be adopted where that work prevents
more expensive exploration, repeated queries, unsafe delivery, or missed
context at larger source breadth. This three-case sample is too small to
estimate enterprise reliability or cost savings.

## Boundary and limitation

This run replays the connected Preset-MCP handoff contract locally using the
same source shapes and evidence that a customer-owned agent would receive. It
does not call Preset's hosted remote \`/mcp\` endpoint. The current SignalWeave
runtime still does not consume Preset's remote MCP transport for unattended
evaluation; it supports the direct Preset API adapter and a caller-supplied
MCP context only as supplementary evidence. A real hosted-Preset proof still
requires an OAuth-capable external-evidence ingestion path or a direct
customer-authorized Preset API connection.

To rerun:

\`\`\`bash
PYTHONPATH=src:. .venv/bin/python evaluations/paired_agent_trial.py \
  --cases evaluations/data/helio-preset-mcp-cases.json \
  --dotenv /Users/brandonsovran/IdeaProjects/hyperset/.env \
  --typesafe-key-file /Users/brandonsovran/Downloads/apikey_typesafe \
  --model gpt-5.6-luna \
  --concurrency 1 \
  --report /private/tmp/helio-preset-mcp-paired-20261004.json \
  --trace /private/tmp/helio-preset-mcp-paired-20261004.jsonl
\`\`\`
