# Evidence

Start with the [evaluation index](../evaluations.md) for the current product-path
results and the useful historical Northstar studies. Reports separate setup,
native decisions, final agent outcomes, and communication quality.

Latest whole-company exercise: [Pine Courier, from installation through three
weekly reviews](pine-whole-journey-2026-10-19.md). It includes the actual delivered
messages, capable baseline, complete effort accounting and remaining human-handoff
gaps, rather than substituting a policy score for the journey.

New experiment transcripts and generated exports belong under ignored
`artifacts/`, not in this documentation directory. Keep a concise protocol,
results summary, reproduction command, source/skill identities, and an honest
account of failures in public docs. Retain only the machine-readable evidence
needed to inspect current claims or exercise offline regression tests here.

## Historical raw-data archive

These five older dossiers were removed from the current checkout after checking
that no production code, evaluation runner, script, or test directly loaded them.
Their reports and failures remain linked from the historical study documents.
The complete raw files are preserved in immutable Git history:

| Dossier | Files | Bytes | Preserved source |
| --- | ---: | ---: | --- |
| Recurring runtime, initial | 8 | 1,177,316 | [Archive](https://github.com/waddle-zoo/signal-weave/tree/ca8a10b69c08a81e793a4860538fa7a9e0b80bd0/docs/evidence/recurring-runtime-live-01) |
| Recurring runtime, transfer | 8 | 1,583,808 | [Archive](https://github.com/waddle-zoo/signal-weave/tree/ca8a10b69c08a81e793a4860538fa7a9e0b80bd0/docs/evidence/recurring-runtime-transfer-live-01) |
| Recurring runtime, completion | 6 | 2,406,866 | [Archive](https://github.com/waddle-zoo/signal-weave/tree/ca8a10b69c08a81e793a4860538fa7a9e0b80bd0/docs/evidence/recurring-runtime-transfer-completion-live-01) |
| Enterprise onboarding journeys | 13 | 1,311,794 | [Archive](https://github.com/waddle-zoo/signal-weave/tree/ca8a10b69c08a81e793a4860538fa7a9e0b80bd0/docs/evidence/enterprise-onboarding-journeys-2026-10-02) |
| Enterprise onboarding repair, remaining cases | 56 | 1,635,331 | [Archive](https://github.com/waddle-zoo/signal-weave/tree/ca8a10b69c08a81e793a4860538fa7a9e0b80bd0/docs/evidence/enterprise-onboarding-repair-v6-remaining-01) |

Total: **91 files / 8,115,115 bytes**, retained irrespective of whether their
results passed or failed. A private local archive was extracted and compared
byte-for-byte with all 91 tracked originals before removal. Its SHA-256 is
`ff78585a430dd38d25ce2b15c16e2b22f165b6172c73f6763e2985c330080bda`.
Removing them from this tree does not rewrite or shrink Git history. Existing
untracked private research artifacts were left untouched.
