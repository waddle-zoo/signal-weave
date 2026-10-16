# Published analysis as a company MCP source

This example lets a separately authorized frontier analyst publish a versioned
report that an approved card can read as ordinary source evidence. The gateway
only reads one operator-configured JSON file. The publisher and any write path
remain caller-owned and must be explicitly delegated; this example grants no
write access.

An owner-approved report source is not automatic approval of its underlying
data or verification of its claims. The manifest/card review owns source scope
and decision policy. A publication's `publication_authority`, `source_scope`,
lineage, and claims are publisher-provided statements; this reader does not
validate a signer or establish factual truth. Preserve the analyst's
interpretations as labeled hypotheses. `source_captured_at` is when the underlying
source result was produced, not the publication/retrieval time or the end of a
historical comparison period. Keep measurement windows and data-as-of cutoffs in
the evidence separately. Republishing old inputs must not refresh their capture
time. If the input capture time is unavailable, `source_captured_at` may be `null`
only when metadata explicitly says `"capture_status": "unknown"` and provides a
nonempty `capture_reason`. That status records uncertainty; it does not establish
truth, verify a provider or uncached-query capability, or attest to freshness.
Publication cannot precede a known capture time or be more than five minutes
ahead of the reader's clock; these checks detect invalid metadata, not a dishonest
publisher. An unknown capture time supplies no source-age bound. A deployment's
handling of missing source times is controlled by its existing card policy and
runtime; if it falls back to retrieval time, that is not evidence of when the
underlying inputs were captured. Treat this as a historical, owner-reviewed
publication example: it makes no source-freshness SLA or current-business
freshness claim. Do not use `null` to imply that a freshness policy is disabled
or satisfied.

## Operator quickstart

1. Put `reader.py` in a controlled deployment location with `mcp` available in
   that Python environment. Copy `manifest.example.json` and replace the Python,
   reader, and publication-file paths. Keep the publication path fixed in the
   manifest; the MCP tool has no path, SQL, or report-selector arguments.
2. Have the delegated publisher write a complete new file and atomically replace
   the configured path using its own authorized workflow. Do not truncate and
   rewrite a file while readers may use it. The reader rejects detected in-place
   changes; that is not a substitute for a correct publisher. Keep storage and
   writer permissions outside this read-only gateway. The file cap is 900,000 bytes.
   The serialized response has a separate 1,000,000-byte cap. The gateway sends
   structured content only, without a second text copy of the report. Source
   normalization has its own configured snapshot budget as well.
3. Register the manifest with the existing local Company MCP setup:

   ```sh
   chmod 600 /private/path/sources.json
   signalweave connections add --source mcp --manifest /private/path/sources.json
   ```

   If a company MCP manifest is already configured, merge this reviewed
   connection into it and use `signalweave connections update --source mcp
   --manifest /private/path/sources.json`; do not drop your existing connections.

   The existing connection wizard validates the manifest and stores its path.
   Review the discovered `analysis_publication / report:product-growth` source,
   then review the actual configured reader response and narrow card policy
   before approving the card. The source bridge checks tenant and source
   identity; the reviewed card policy controls freshness handling. An unknown
   capture time is not source-freshness evidence, and this historical example
   makes no freshness-SLA claim.

## Publication shape

The publisher supplies a `ResourceSnapshot`-shaped JSON object. `metadata` is
freeform publication lineage, not a fixed metric schema; `evidence[].values`
can contain the analyst's report-specific values. Keep facts, calculations,
and hypotheses distinguishable in the evidence and its values. The reader
validates the publication version/identity, explicit publication authority and
scope, and timezone-aware publication and known source-capture timestamps, then
returns the claims without rewriting timestamps or claim labels. For an unknown
source-capture time it requires the explicit metadata acknowledgement described
above. It adds one evidence record with publication ID, revision and the SHA-256
of the exact file bytes read. That record survives in decision receipts; a hash
establishes byte identity, not a signer, analytical correctness or permission to
deliver. Only for an explicitly unknown capture time, that existing record also
carries the publisher's `capture_reason`; known-capture record values retain
their existing shape. The acknowledgement and reason are publisher-provided
metadata, not independent verification of the source or its capture capabilities.
Keep the decision input to relevant findings and rollups, with pointers to raw
data: fitting the transport budget does not mean a publication fits the decision
provider's context budget. The dates and values below are illustrative; use the
actual input-result capture time and real measurement windows in your publication.

```json
{
  "source_key": "product-growth-publication",
  "adapter": "analysis_publication",
  "resource": "report:product-growth",
  "title": "Product growth analysis — week 42",
  "contract": {"tenant_id": "local", "authorized": true},
  "source_captured_at": "2026-10-15T23:00:00Z",
  "metadata": {
    "publication_schema_version": 1,
    "publication_id": "product-growth-weekly",
    "revision": 7,
    "publication_authority": "delegated frontier analyst",
    "source_scope": "Paid product accounts, all regions, warehouse run wh-8421",
    "published_at": "2026-10-16T00:05:00Z",
    "lineage": ["warehouse-run:wh-8421", "analysis-notebook:rev-18"]
  },
  "evidence": [
    {
      "source_key": "product-growth-publication",
      "subject_id": "finding:activation",
      "subject_label": "Activation finding",
      "statement": "Observed activation was lower in the captured period.",
      "values": {"periods": ["2026-10-08/2026-10-14", "2026-10-01/2026-10-07"], "change": -0.08, "unit": "fraction"},
      "origin": "source",
      "provenance": ["warehouse-run:wh-8421"]
    },
    {
      "source_key": "product-growth-publication",
      "subject_id": "hypothesis:onboarding",
      "subject_label": "Analyst hypothesis",
      "statement": "A recently changed onboarding step may explain part of the movement.",
      "values": {"claim_kind": "hypothesis", "confidence": "unassessed"},
      "origin": "source",
      "provenance": ["analysis-notebook:rev-18"]
    }
  ]
}
```

The manifest contract is the owner-reviewed definition and authorization for
the source. The report's measurements and interpretations are current
publication content, not new metric definitions or verified facts. A source
identity/tenant check is an authorization boundary, not a truth check; Jev
applies only the already-reviewed card policy to the labeled evidence.
