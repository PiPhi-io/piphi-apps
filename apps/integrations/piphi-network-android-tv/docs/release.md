# Release

Releases use the monorepo's protected **Release one app package** workflow in
`.github/workflows/release-app.yml`. The workflow does not bump or commit a
version: all release metadata must already be committed to the default branch.

Before dispatching a release:

1. Synchronize `manifest.json`, `pyproject.toml`, `piphi-app.json`,
   `settings.py`, image tags, and release docs with `scripts/release.py`.
2. Run `python scripts/release_plan.py --package piphi-network-android-tv
   --version VERSION` from the monorepo root.
3. Run the full command set declared in `piphi-app.json` and build the
   container locally.
4. Merge the reviewed change to the protected default branch.
5. Dispatch the workflow with the exact package ID/version and deliberately set
   `publish=true`.

The workflow qualifies the package, builds and pushes `linux/amd64` and
`linux/arm64` to GHCR, emits SBOM/provenance and an OCI attestation, uploads
immutable release evidence plus a registry proposal, and creates a namespaced
GitHub prerelease/tag.

For `0.3.0-rc.1`, publishing is explicitly permitted without physical hardware
qualification. Governance must remain `draft`, `unverified`, and rollout zero;
the release must not be described as production-ready or hardware-verified.

Current image target:

```text
ghcr.io/piphi-io/piphi-network-android-tv:0.3.0-rc.1
```
