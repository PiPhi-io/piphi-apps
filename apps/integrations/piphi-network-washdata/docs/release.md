# Release

WashData releases through the central `piphi-apps` integration workflow.

Before cutting a release:

- Set `manifest.json.version` to the release version.
- Set `runtime.linux.container.image` to the final registry image.
- Set `maintainer.name` and `maintainer.website` to the publishing owner.
- Run the local validation and conformance tests.
- Verify migration, restart replay, failure injection, stale recovery, and
  source-event deduplication tests.
- Verify the image contains Runtime Kit `0.11.1` or newer.
- Run `piphi-network-create publish-check -C .` from this project.

The generated workflow is triggered manually from GitHub Actions. It bumps the
semantic version, updates release metadata, commits and tags the release, builds
a multi-architecture Docker image, pushes it, and creates a GitHub release.

Images starting with `ghcr.io/` publish to GitHub Container Registry. Images
using `docker.io/org/image:tag` or `org/image:tag` publish to Docker Hub with
the `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets.

Current image target:

```text
ghcr.io/piphi-io/piphi-network-washdata:0.2.0
```
