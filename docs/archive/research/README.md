# Archived evaluation research

This directory preserves six superseded research reports and the exact former
`docs/evaluation.md` guide. These reports remain useful as historical protocol
and result records; they are not current product claims. Their limitations,
including absent artifacts, simulated roles, prepared cases, and evidence
re-audit findings, are retained in the reports and in the active
[`evaluation index`](../../evaluations.md).

`evaluation-legacy.md` is an exact byte-for-byte copy of the former guide.
Its relative links reflect the original `docs/` layout. For complete original
navigation, consult the immutable [437ab297 repository snapshot](https://github.com/waddle-zoo/signal-weave/tree/437ab297bb621c724edc71b138b5ff774759c51f).

The full former evaluation index from `origin/main` at commit `437ab297` is
preserved byte-for-byte as
[`evaluations-2026-10-20.md`](evaluations-2026-10-20.md). Its source and archive
hashes are recorded in the move manifest. Use the immutable snapshot above for
its original relative-link navigation.

The five fixture/scoring test modules moved to
[`evaluations/tests/historical`](../../../evaluations/tests/historical/).
They are intentionally outside default pytest discovery and can be run with
`make historical-eval-tests`. The active product and current journey regression
suite was not reduced beyond those five modules. At this archive boundary,
default pytest discovery collected 5,206 active items; the relocated cohort is
24 items (5,230 total when the opt-in cohort is included). No source runner,
evaluation input, raw `docs/evidence` file, or paired-agent test was moved.

See [`MOVE-MANIFEST.md`](MOVE-MANIFEST.md) for the exact source-to-destination
map and SHA-256 hashes recorded before relocation. A few report links were
updated only to follow files to their new locations; the manifest preserves
the original-byte digests for verification.
