# Release

Releases use the monorepo's protected **Release one app package** workflow in
`.github/workflows/release-app.yml`. The workflow does not bump or commit a
version: all release metadata must already be committed to the default branch.

Before dispatching a release:

1. Synchronize `manifest.json`, `pyproject.toml`, `piphi-app.json`,
   `settings.py`, image tags, and release docs with `scripts/release.py`.
2. Run `python scripts/release_plan.py --package piphi-android-adb-sidecar
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

For `0.3.0-rc.2`, the artifact includes bounded network ADB transport, Android
11+ wireless pairing and mDNS through pinned Platform Tools, and a private API
wired to the Android TV parent integration. Physical hardware, firmware, and
USB qualification remain outstanding. Governance must remain `draft`,
`unverified`, and rollout zero.

Current image target:

```text
ghcr.io/piphi-io/piphi-android-adb-sidecar:0.3.0-rc.2
```
