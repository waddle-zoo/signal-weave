# Security policy

SignalWeave is an alpha, self-hosted project. Do not expose the local demo stack
to an untrusted network or use it as a production identity, authorization,
workflow, or notification control plane without adding the deployment controls
described in [`docs/security.md`](docs/security.md).

## Reporting a vulnerability

Please do not disclose credentials, private source data, or an exploitable
vulnerability in a public issue. If GitHub private vulnerability reporting is
enabled for this repository, use the **Report a vulnerability** button on the
repository Security tab. Otherwise, contact the repository maintainers privately
through the organization’s existing security channel and include:

- the affected commit, component, and configuration;
- reproduction steps or a minimal proof of concept;
- the impact and any required access; and
- a suggested mitigation, if known.

Please allow maintainers reasonable time to investigate before public disclosure.

## Supported versions

Only the latest commit on `main` is actively maintained while the project is in
alpha. Pin deployments to a reviewed commit and do not assume that a release is
secure merely because CI is green.

