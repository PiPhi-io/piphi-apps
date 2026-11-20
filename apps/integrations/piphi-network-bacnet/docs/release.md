# Release

This package is released independently by the trusted monorepo
`.github/workflows/release-app.yml` workflow.

Before cutting a release:

- Set `manifest.json.version` to the release version.
- Set `runtime.linux.container.image` to the final registry image.
- Set `maintainer.name` and `maintainer.website` to the publishing owner.
- Run the local validation and conformance tests.
- Qualify the exact image against the committed BACpypes UDP simulator with `scripts/qualify_release_image.py`.
- Treat physical SenseEdge testing as optional follow-up evidence, not a publication gate.
- Keep marketplace governance at `draft`, `unverified`, rollout `0`; simulator evidence must not be presented as live-device qualification.
- Run the package commands declared in `piphi-app.json`.
- Verify the release version is synchronized across `piphi-app.json`,
  `manifest.json`, `pyproject.toml`, the runtime constant, and image references.

After the source PR is merged and required checks pass, dispatch the central
release for package `piphi-network-bacnet` and version `0.1.1`. It must build
the immutable namespaced tag from reviewed `main`, publish both `linux/amd64`
and `linux/arm64`, and produce release evidence, SBOM, provenance, and
attestations. Independently inspect the exact digest, OCI labels, platforms,
attestations, and non-root/read-only execution before proposing a registry PR.
The registry proposal must preserve draft/unverified/0% governance.

Current image target (not yet published):

```text
ghcr.io/piphi-io/piphi-network-bacnet:0.1.1
```
