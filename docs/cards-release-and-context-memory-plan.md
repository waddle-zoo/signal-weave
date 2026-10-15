# Cards release, then domain memory

Owner: SignalWeave maintainers. Started: October 14, 2026.

## Order and scope

First ship the existing card-driven MCP and native executable from `main`.
Domain memory is a subsequent, independently evaluated change. A working
installer or a correct provider decision is not proof of final-agent benefit.
Do not describe simulated results as customer adoption or universal accuracy.

Keep the production boundary: the agent discovers and reasons, cards preserve
the recurring brief and policy, SignalWeave gathers bounded evidence and calls
the configured provider for typed judgments. The agent owns schedules and
delivery. No scheduler, agent framework, or mandatory graph database is added.

## Milestone A: merge and publish the cards baseline

1. **Integrate the candidate.** Reconcile `feat/local-investigation-runtime`
   with `fix/bounded-dashboard-judgments`. Preserve unrelated untracked work.
   Review the production diff against remote `main`; retain the deferred
   evidence handoff, valid receipt pointers, absolute BI citations, and bounded
   pagination. Do not enable experimental graph-bundle policies.
2. **Verify source and server contracts.** Run `make verify` in the clean
   candidate. Report actual skips. Run loopback/PTY checks with the permissions
   they require rather than treating sandbox failures as product failures.
   Verify authenticated HTTP MCP, card approval boundaries, source isolation,
   replay, and explicit failed/deferred provider results.
3. **Build the exact native candidate.** Record commit, source fingerprint,
   executable hash, and version. Test the actual executable through fresh
   isolated install, wizard, configuration/credential management, MCP setup,
   bundled skill, upgrade, and uninstall. Never change the user's personal
   installation or agent configuration during these tests.
4. **Prove the useful cards path.** Use the current native MCP against local
   Superset with synthetic company data and live Jev. Onboard and review a
   narrowly scoped recurring card; inspect its actual source facts, typed
   judgment, probabilities, receipt, and repeated evaluation. Exercise quiet,
   actionable, ambiguous/missing-data, and investigation handoffs in the
   existing generalized regression suite. A fixture regression is not new
   held-out or customer evidence. Inspect the final output, not just outcome
   labels. Keep oversized broad-dashboard analysis explicitly deferred.
5. **Independent release review.** Obtain engineering and human/product
   reviews. Fix concrete blockers and rerun the affected checks. Do not turn
   negative comparative benchmarks into claimed wins.
6. **Merge through a PR.** Push the candidate, run protected-branch CI, attach
   the PR to this task, and merge only after required checks pass. Do not
   weaken branch protections. Verify the resulting `main` revision.
7. **Publish the matching native prerelease.** Bump package/lock metadata to
   `0.2.0rc3`, build all three platforms in GitHub Actions, and publish an
   immutable tag from `main`. Verify checksums, asset presence, and a real
   isolated installation downloaded from GitHub. Only then update README
   download instructions to the verified release. Rerun installed MCP smoke.
8. **Record concise evidence.** Keep full logs, artifacts, and trial payloads
   outside tracked documentation. Publish one short release evidence note
   with identities, commands, results, review disposition, and limitations.

Acceptance: required CI passes; independent reviewers have no unresolved
release-blocking findings; the matching downloaded executable installs,
onboards, serves MCP, runs a card through live Jev, and uninstalls in isolation;
server authentication contracts pass. This certifies the stated cards path,
not every chart/question or an enterprise-wide cost/accuracy advantage.

## Milestone B: task-oriented domain memory

Start only after Milestone A is recorded as complete on `main`.

1. Inspect Hyperset's current bundle/identity/provenance model and document the
   smallest reusable boundary. Prefer consuming an existing context provider
   over duplicating a catalog. Keep this in a separate feature branch.
2. Select one cross-dashboard business domain and preregister held-out tasks:
   competing metric definitions, ambiguous asset names, changed definitions,
   stale findings, cross-domain evidence, missing context, and permission
   boundaries. Owners may clarify business meaning; hidden expected answers
   never enter onboarding or retrieval state.
3. Define a small persistent model: stable source references, versioned
   business context, typed relationships, and dated investigation memories.
   Store source observations, confirmed meaning, and hypotheses separately.
   Context captures valid/observed time, provenance, and source scope. Do not
   copy warehouse rows into a knowledge graph or infer causation from links.
4. Implement a task-context packet using bounded lexical/semantic candidate
   retrieval and targeted relationship expansion. Preserve relevant caveats,
   conflicts, and coverage gaps. Fetch detailed facts lazily through existing
   source tools. Decision providers see the relevant packet, not the estate.
5. Give the agent a conversational onboarding/update skill and a narrow MCP
   retrieval operation. Users describe their domain in ordinary language;
   agents reconcile identities and ask material clarifying questions.
6. Keep local/server behavior on the same application contracts. Start with
   existing storage capabilities where suitable; require no separate graph
   service for the local binary. Filter authorization before retrieval and
   inference, including connected relationship targets and memory contents.
7. Run equal-information ablations: agent plus ordinary context; agent plus
   SignalWeave memory; agent plus memory and Decisions/Jev. Same source tools,
   owner knowledge, model, budget, and task distributions. Measure final
   answer/alert quality, misleading or missed notifications, useful retrieval,
   clarification effort, tool calls, provider tokens, and total elapsed time.
8. Have independent reviewers inspect code, traces, and final human messages.
   Fix failures without encoding fixture-specific names or answer keys. Merge
   only a slice that measurably improves a preregistered user outcome without
   material correctness or permission regressions. Report a negative result
   and revise the approach if it does not.

## Progress log

- Candidate branches inspected; released `v0.2.0rc2` predates recent evidence
  handoff fixes. Independent engineering and product reviewers dispatched.
- Integrated the primary branch's current documentation into the clean
  payload-fix worktree. No domain-memory changes have been made.
