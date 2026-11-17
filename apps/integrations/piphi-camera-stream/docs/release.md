# Release

This package uses the repository's central application CI and release workflows declared through
`piphi-app.json`.

Before cutting a release:

- Set `manifest.json.version` to the release version.
- Set `runtime.linux.container.image` to the final registry image.
- Set `maintainer.name` and `maintainer.website` to the publishing owner.
- Run the local validation and conformance tests.
- Run `piphi-network-create publish-check -C .` from this project.

The central release workflow uses the package declaration to tag the release, build a
multi-architecture Docker image, push it, and create provenance and release evidence.

Images starting with `ghcr.io/` publish to GitHub Container Registry. Images
using `docker.io/org/image:tag` or `org/image:tag` publish to Docker Hub with
the `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets.

Current image target:

```text
ghcr.io/piphi-io/piphi-camera-stream:0.1.7
```
