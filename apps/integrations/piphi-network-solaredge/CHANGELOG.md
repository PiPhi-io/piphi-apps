# Changelog

## 0.2.2 — 2026-10-05

- Replace two embedded sandboxed widgets with one signed, integration-owned
  declarative experience containing Energy Flow and Production Summary.
- Add SolarEdge and Quiet themes, source-scoped bindings, freshness contracts,
  history/popout/details/refresh interactions, and Core card replacements.
- Record timestamped live power history and poll heartbeats while deduplicating
  slower production-summary samples.
- Preserve the last good measurements on SolarEdge read failures and expose
  poll, Core-delivery, and sample freshness through health and diagnostics.
- Add Runtime TestKit delivery coverage, current Core package-contract tests,
  deterministic signing tests, release invariants, and accessibility checks.
- Run the runtime image as a non-root user with a persistent SDK automation
  ledger and container health check.
- Prepare immutable runtime and experience release workflows. Runtime `v0.2.2`
  targets the existing Docker Hub repository authorized by the OIDC connection.
