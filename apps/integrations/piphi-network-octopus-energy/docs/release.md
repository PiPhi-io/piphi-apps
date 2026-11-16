# Release

This package is released by the monorepo's protected `Release one app package`
workflow after full CI and container qualification pass on the default branch.

Before cutting a release:

- Set `manifest.json.version` to the release version.
- Set `runtime.linux.container.image` to the managed GHCR image.
- Set `maintainer.name` and `maintainer.website` to the publishing owner.
- Run the local validation and conformance tests.
- Run `piphi-network-create publish-check -C .` from this project.

The centralized workflow is triggered manually from GitHub Actions after the
version and image metadata are merged. It qualifies the package, builds the
amd64/arm64 image with SBOM and provenance, pushes it to GHCR, attests the
digest, and creates namespaced release evidence and a registry proposal.

Current image target:

```text
ghcr.io/piphi-io/piphi-network-octopus-energy:0.1.1
```
