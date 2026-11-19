# Release

Releases are immutable and tag-driven. Before pushing `vMAJOR.MINOR.PATCH`, synchronize the version
in `manifest.json`, `pyproject.toml`, and the Docker build argument, then run:

```bash
pdm install --frozen-lockfile -G dev
pdm run ruff check src tests scripts
pdm run ruff format --check src tests scripts
pdm run pytest
pdm run python scripts/validate.py
pdm run python scripts/check_release.py v0.3.8
piphi-network-create publish-check -C .
# After building the candidate image:
pdm run python scripts/smoke_container.py --build --image piphi-webrtc-sidecar:ci-smoke
```

The required package CI container smoke verifies the real pinned go2rtc process, production
authentication, an FFmpeg-generated H.264 fixture frame, pairwise stream cleanup, and secret-safe
failure output.

Pushing the tag builds and attests Linux amd64/arm64 images, publishes
`ghcr.io/piphi-io/piphi-webrtc-sidecar:<version>`, and creates the matching GitHub release.
