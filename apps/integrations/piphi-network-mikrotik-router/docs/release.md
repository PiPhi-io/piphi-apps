# Release

Releases use the monorepo **Release one app package** workflow.

Before cutting a release:

- Set `manifest.json.version` to the release version.
- Run the local validation and conformance tests.
- Confirm `piphi-app.json`, `manifest.json`, `pyproject.toml`, and runtime
  settings use the same immutable version and managed GHCR repository.

Dispatch with package ID `piphi-network-mikrotik-router`, the already committed
version, and `publish=false` for qualification. Publishing uses tag
`apps/piphi-network-mikrotik-router/v0.1.2`; do not create a standalone `v*`
tag or a Docker Hub image.

Current image target:

```text
ghcr.io/piphi-io/piphi-network-mikrotik-router:0.1.2
```
