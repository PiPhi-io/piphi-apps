# Release

Releases are built from signed-off semantic-version tags by the pinned GitHub Actions workflow.

Before cutting a release:

- Set `manifest.json.version` to the release version.
- Keep `pyproject.toml`, `manifest.json`, `settings.py`, and the Docker build argument on the
  same version.
- Run lint, tests, `scripts/validate.py`, and `scripts/check_release.py vX.Y.Z`.
- Confirm the upstream image digest and source link in `THIRD_PARTY_NOTICES.md`.
- Push the commit, wait for CI, then push the matching `vX.Y.Z` tag.

The tag workflow validates the exact release metadata, builds a Python distribution, publishes
an amd64/arm64 image to GHCR with SBOM and provenance, adds a GitHub artifact attestation, and
creates the GitHub release. The registry entry remains draft with a 0% rollout until hardware
qualification and governance review are complete.

Current image target:

```text
ghcr.io/piphi-io/piphi-wyze-camera-service:0.1.3
```
