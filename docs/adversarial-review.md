# SignalWeave adversarial review

This review treats SignalWeave as a small enterprise boundary around existing data systems, not as a complete enterprise control plane.

## Verdict

**Ready for the minimal self-hosted proof/product boundary.** The source is scoped, tested, containerized, authenticated when deployed with `SIGNALWEAVE_API_TOKEN`, and fails closed on the high-risk data and routing cases below.

The verdict does not mean a company should deploy the local JSON catalog or static token as its final governance system. Those are explicit integration seams documented in [security.md](security.md).

## Review lenses

### Security reviewer — pass with deployment conditions

- MCP and webhook requests reject missing bearer credentials when the deployment token is configured.
- Health remains available without credentials for orchestration.
- The service does not execute caller-supplied SQL.
- The monitor container runs as UID 10001.
- Credentials are loaded at runtime and are not written to the repository.
- Remaining condition: production deployments must provide TLS, token rotation or an identity gateway, and a secret manager.

### Reliability reviewer — pass

- Superset requests have timeouts and refresh a cached API token after a 401.
- Dashboard discovery is paginated and bounded; chart loading is concurrency-limited.
- Row and series limits are bounded.
- Missing charts, source timeouts, empty results, and ambiguous metrics become evidence-backed `insufficient_data`/`investigate`, never `ignore`.
- Stale data, missing baselines, low confidence, and unapproved recipients are safety-gated.
- Monitor-card writes are atomic.
- Remaining condition: use a durable store and idempotent delivery worker when running more than one service replica.

### Product reviewer — pass

- The product boundary is one decision layer above existing data assets.
- Superset is an adapter and demo source, not the product name or workflow engine.
- TypeSafe is used for narrow typed plan/judgment questions; code owns calculations, allowlists, and safety policy.
- Airflow, Temporal, schedulers, chat delivery, and agent orchestration remain outside scope.
- The Jev proof demonstrates four distinct labeled evaluation cases; the separate live acceptance check exercises a real Superset dashboard without an expected label.

## Evidence collected

```text
make verify                         local lint + unit suite
25 passed, 1 skipped                adversarial/unit suite
1 passed                            live Superset integration
3 dependency containers healthy      Superset/Postgres/Redis runtime
Host Jev + Superset evaluation       Sales Dashboard round-trip
UID 10001                           non-root monitor
401 / 200                           unauthenticated/authenticated MCP and push checks
TypeSafe Jev                         20-case repeated proof: 100% exact, 0 errors
GitHub Actions CI                   green on the release commit
```

The exact thresholds and Jev confidence values remain calibration inputs, not universal truth. Teams should label outcomes and tune them against operational consequences before enabling automatic delivery.
