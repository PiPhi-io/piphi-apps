# Release

Version and image references must agree across `pyproject.toml`, `settings.py`, `manifest.json`, and `piphi-app.json`.

Current target:

```text
ghcr.io/piphi-io/piphi-network-knx:0.2.0
apps/piphi-network-knx/v0.2.0
```

Before publication:

1. Run every command in the README's release gate.
2. Build and smoke-test the exact container as the non-root `piphi` user.
3. Run `python3 scripts/release_plan.py --package piphi-network-knx --version 0.2.0` at repository root.
4. Merge the qualified source to `main`; release tags are never created from a feature branch.
5. Dispatch `release-app.yml` from `main` with `package_id=piphi-network-knx`, `version=0.2.0`, and `publish=true`.
6. Verify the amd64 and arm64 image manifests, SBOM/provenance attestations, release evidence, and immutable digest.
7. Apply the generated proposal to `PiPhi-io/piphi-nework-registry` and run that repository's validator/governance suite.

Do not mark hardware qualification verified without a recorded physical test matrix. Do not move an existing release tag.
