# Northstar lab reproduction record

Recorded 2026-10-19. This separates the complete cached-runtime smoke from the still-unverified fresh image build.

## Result

The full Superset seed completed in the isolated test project `sw-northstar-repro-cached-20261019`, bound to `127.0.0.1:18091`. The final seed process exited **0** after 48m13s, with no OOM. Authenticated Superset login returned HTTP 200; `/health` returned HTTP 200; the authenticated catalog contained **24 datasets, 1,200 charts, and 48 dashboards**.

The warehouse contained **16 base tables, 11 views, and 27 non-system relations**. The base tables held 828,883 rows total, and each table count matched the generated manifest. All 16 generated CSV SHA-256 values matched the packaged input-hash manifest.

## Cached image versus fresh build

The complete run used the already-cached derived Superset 4.1.3 image ID `sha256:c4507b97ca9c711db163afc4adffb035d86863c785b72e1e1a7ed33a0e6e628c`, through the unique local tag `signalweave-northstar-cached-repro:20261019`. It reused the existing isolated project, seed container, secrets, and volumes; the final continuation started the existing stopped seed container, without building or pulling an image. The original `northstar-superset:local` tag was not changed.

The fresh pinned-image route is **not verified**. The Dockerfile pins Docker Hub's verified `apache/superset:4.1.3` multi-platform index digest `sha256:31d965435b462361d2b8207595eff28f54492778d0afd53768da5e763cc16ce7`, but Docker Desktop stalled while resolving that base-image metadata and a separate pull of the same digest timed out. The failed build produced no image or project resources. The cached derived image exposed a Superset 4.1.3 version label, but no upstream repository digest was available, so the cached smoke does not prove equivalence to a fresh build of the pinned Dockerfile.

## Attempt history

| Attempt | Result | Catalog at end |
| --- | --- | --- |
| Fresh pinned-image build | Base metadata resolution stalled; separate digest pull timed out. No image or project resources created. | — |
| First cached seed, started 06:50:06 UTC | At 8m42s the bounded smoke stopped the still-progressing seed. Container exit 137, `OOM=false`; this was a time-bound stop, not a completed seed. | 24 datasets, 445 charts, 23 dashboards |
| First continuation, 07:50:23–08:05:23 UTC | Exited 1 after 15 minutes when the one-time Superset access token expired: `GET /api/v1/chart/ -> 401: Token has expired`. No OOM. | 24 datasets, 666 charts, 31 dashboards |
| Final continuation, 08:07:36–08:55:49 UTC | The seeder reauthenticated once on 401 and retried. Same project, container, credentials, volumes, and cached image; exit 0, no OOM. | 24 datasets, 1,200 charts, 48 dashboards |

The 401 led to a narrow bootstrap fix: on one expired-token response, obtain a fresh login/CSRF token and retry the request once. The focused regression test covers this path. The seed operations reuse existing datasets, charts, and dashboards, so rerunning the bootstrap is idempotent.

## Healthcheck interpretation

The cached image's inherited webserver healthcheck reports the one-off `superset-init` and `superset-seed` containers as unhealthy because those jobs do not run the Superset webserver. The final seed container retained that healthcheck status even though its process exited 0; this is not evidence of a failed seed. During the final run, the Superset service and warehouse were healthy, and the app/API checks above passed.

Compose now disables inherited healthchecks for those one-off jobs on future starts. The Compose edit did not recreate or modify the completed containers. Use the init/seed exit status and authenticated application checks as the result; do not infer job success from the inherited container healthcheck.

## Provenance and input digests

- The deterministic generator uses seed `90219` and produced 16 input CSVs totaling 828,883 rows. The generated per-table row counts are in [`generated_manifest.json`](generated_manifest.json).
- All 16 generated CSV hashes matched [`seeded-input-sha256.json`](seeded-input-sha256.json). The manifest file SHA-256 was `aa3b2236abbc4de8d613a75cfb6bbb86fa6d5fe0985b69d955853bdda3ba51f0`; the generated manifest SHA-256 was `c05823220055716b267ad140ad6e65bd539764aa84af11918d8b58366d7bf1c4`.
- [`source-provenance.json`](source-provenance.json) records the supplied local snapshot, applicable source/packaged file hashes, and verified base-image metadata. The snapshot did not include Git commit metadata.
- The generator's import/spacing normalization and unused-loop-variable rename did not change the 16 input hashes. The seeder additionally received the expired-token retry described above; runtime credentials remain required environment variables.
- The workspace-local machine record at `artifacts/northstar-repro-cached-20261019/reproduction-final.json` contains per-table row counts, every generated CSV digest, image/container IDs, exact timestamps, and check results. It is an ignored local artifact, not part of the published example.
- The original fresh-build failure and first partial run remain in the workspace under `artifacts/northstar-repro-20261019/reproduction-smoke.log` and `artifacts/northstar-repro-cached-20261019/reproduction-smoke.log`. The token-expiry and successful continuation summaries are preserved as `seed-resume-1-sanitized.log` and `seed-resume-2-sanitized.log` in the cached reproduction artifact directory. Credentials are not included.

No original `northstar-bi` containers, images, volumes, or warehouse tables were changed, and no paid-model/provider calls were made.
