# Release

Releases are immutable and tag-driven. Before pushing `vMAJOR.MINOR.PATCH`, synchronize the version
in `manifest.json`, `pyproject.toml`, and the Docker build argument, then run:

```bash
pdm install --frozen-lockfile -G dev
pdm run ruff check src tests scripts
pdm run ruff format --check src tests scripts
pdm run pytest
pdm run python scripts/validate.py
pdm run python scripts/check_release.py v0.1.2
piphi-network-create publish-check -C .
```

Pushing the tag builds and attests Linux amd64/arm64 images, publishes
`ghcr.io/piphi-io/piphi-webrtc-sidecar:<version>`, and creates the matching GitHub release.
