# Release

This package is released independently by the protected monorepo release workflow.

Before cutting a release:

- Keep `pyproject.toml`, `piphi-app.json`, `manifest.json`, Docker labels, and
  documentation on the same immutable version.
- Run locked tests, Ruff, package validation, monorepo validation, and container
  qualification.
- Merge the source PR before dispatching publication from the protected default
  branch.
- Independently verify the exact multi-architecture digest, provenance, labels,
  runtime hardening, authentication boundary, and mutation policy.
- Synchronize the registry in a separate PR without changing draft/rollout/
  quality/qualification governance.

Image target:

```text
ghcr.io/piphi-io/piphi-network-daikin-onecta:0.2.0
```
