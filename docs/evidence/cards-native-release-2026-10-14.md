# Cards-based native release

Scope: the existing card-driven MCP, local native setup, source evidence,
configured decision provider, and receipt replay. This is integration/release
evidence, not a customer, universal enterprise-readiness, or superiority claim.
Domain-memory work is a separate milestone in the
[local plan](../cards-release-and-context-memory-plan.md).

## Main baseline

[PR #15](https://github.com/waddle-zoo/signal-weave/pull/15) merged as
`d84cc410ecc54a230f03ab39c50b7d7e7eac631f`. Candidate `521bc9d` had all 14 PR
CI checks and all three native-platform checks green. Independent code and
documentation reviewers gave scoped GO; the code reviewer also inspected the
native Superset proof artifact and executable hash.

The review found and fixed two defects: source inspection could replace
comparison meaning under the same key, and the default MCP factory selected a
source-only runtime that cannot make card decisions. New regressions check all
five comparison-meaning fields and reject source-only runtimes before serving.

| Gate | Observed result |
| --- | --- |
| Final source suite | 2,993 passed, 7 skipped; 461.29 seconds; Ruff passed |
| Scoped server authentication | 18 passed; 6.84 seconds; synthetic issuer/ASGI contracts, not a customer IdP |
| Final live Jev regression | 4 synthetic companies, 5 workflows, 14/14 workflow cases and 6/6 retrieval cases; 20 SDK requests, 70,048 input / 2,410 output tokens |
| Real candidate executable installation | 2 passed in 217.56 seconds, serial: actual executable, isolated install, PTY setup, MCP startup, reinstall, uninstall |
| Native company-MCP smoke with live Jev | Expected `notify` for a synthetic 20% decline; delivery disabled; same receipt replayed across process restart |
| Native local Superset plus live Jev | Default 10-tool profile, one fictional owner-approved chart, one completed judgment (`investigate`), 5 observations, 6 evidence records; 6,713 input / 50 output tokens; stored receipt verified; same-key replay returned the saved receipt (extra traffic not independently measured in this candidate harness) |

The final live regression repeats existing curated fixtures; it is not a new
holdout or proof of conversational onboarding. The native Superset case is a
report-only integration check, not an expected-outcome accuracy test: its periods
have unverified coverage, it validates no quantitative or causal claims, and its
default card windows do not establish that the source supports those windows.
No schedule or external notification was created.

## Failures retained

- The first live regression completed 13 workflow cases and failed one with a
  TypeSafe HTTP 499 response. The unchanged repeat and final post-fix run passed;
  these do not erase the observed provider failure.
- Concurrent real-binary installation checks timed out at their unchanged
  180-second checker and 30-second PTY limits. A later serial run passed with
  the same executable and limits. This is workload-sensitive local timing,
  not proof of instant CLI startup or a universal installation guarantee.
- The first joined Superset harness incorrectly required a full-profile
  preview tool in the default profile. It stopped before source/card tools or
  Jev; that invalid harness run is excluded. Only the corrected attempt counts.

Full payloads/logs remain in ignored local artifacts, not in tracked docs.
Reproduce source checks with `make verify`; native install tests use the
`SIGNALWEAVE_TEST_BINARY`, `_SHA256`, and `_VERSION` identity gates documented in
the [release workflow](../../.github/workflows/release.yml). The live regression
uses `evaluations.generalized_readiness_trial` and its independent gate.

Candidate production fingerprint:
`46ea0888f0e4a46c1a56f243b201e62db177c0ee7f1035fe2241e70282946562`.
Local candidate executable:
`9656c276ece4da31ae70abacd257b916d6e97bf03798412aa858fba655ee033e`.
Final live report SHA-256:
`fe6ca32f8e761ece6d4721bfc3c0fecb92c89df2b553fc7f1edcc67d58dfee53`.
Corrected native Superset report SHA-256:
`8b256750b8bb72f51e27e5f349c6c97afdb524f02a73f85691a6f685494e1418`.

## Public download gate

[`v0.2.0rc3`](https://github.com/waddle-zoo/signal-weave/releases/tag/v0.2.0rc3)
was published from main revision `d84cc41` after all three native runner gates
passed. The tagged [release run](https://github.com/waddle-zoo/signal-weave/actions/runs/38663764339)
published three archives, checksums, the installer, and build attestations.

The actual GitHub `curl | sh --setup` command was exercised on Apple Silicon
with a canonical temporary home, scripted human answers, and the real Codex CLI.
Download, checksum verification, setup, and registration completed in 31.419
seconds excluding human think time. The installed skill matched canonical
content; live catalog health and the 10-tool MCP guide passed. The documented
credential-update command then replaced a setup-only sentinel with the private
Jev credential. The same installed executable/home completed one source-backed
Superset card and recovered/replayed its persisted receipt. Source evidence
contained 5 observations and 6 records, with unverified-period caveats. Native
telemetry reported one Jev request, 6,705 input / 50 output tokens; the captured
HTTP log contained one Jev POST across the fresh evaluation and replay.
Uninstall with purge removed only the temporary executable and private home.

This is not a frontier-agent analysis, statistical alert-accuracy trial, or real
human usability panel. Catalog health does not prove freshness. The helper's
hardcoded replay request count is not used as measured traffic evidence; the
captured HTTP log is the observation above. Its declared retry setting is also
not used: this wrapper ran with the provider's default retry configuration,
and observed one successful request.

Three earlier public-test harness attempts are preserved and excluded: a
symlinked macOS temporary alias was correctly rejected before setup; a stale
skill-path assumption failed after setup; and a wrapper signature mistake
stopped before evaluation. Product security checks and timeouts were not relaxed.

Downloaded executable SHA-256:
`1815637c6217c27f45e775d80599c4cc0f479764982bfa701c35c6cd7913abdf`.
Public journey report SHA-256:
`33d061e1d136e3e2b886fd68959a1fc1698318d58fd5d20e7dd0fb9ea468dd58`.
Captured public journey log SHA-256:
`a9f99f7ba07da38bcabd74f3bd8cd46b4ed99f8f580c5782a0ad5ce958670768`.

## Server image packaging follow-up

A real Docker build exposed a missing package input: the Dockerfile did not
copy the bundled skill required by `pip install .`. The corrected image copies
the canonical skill and license, omits test files, and excludes local artifacts,
standard credential paths/patterns, and agent configuration directories from the
build context. Arbitrarily named secret files still require operator review.
CI now builds the image and checks its installed CLI and skill as non-root.

The locally built image passed an actual HTTP MCP check with synthetic
credentials and a configured local Superset adapter: UID 10001, health HTTP 200,
unauthenticated MCP HTTP 401, authenticated SDK initialization, the default 10
tools, and a successful guide call. No evaluation, provider request, or delivery
was invoked. Earlier harness attempts omitted the container bind setting or
required source configuration; those failures are retained, not counted as
successful deployment checks. The native rc3 archive is unchanged by this
Docker-only packaging fix.

Server HTTP proof report SHA-256:
`0e773e91d2a3e6b6b94e5b11c10beca02bf4545af6f4eaf43bcff54d51fd2582`.
