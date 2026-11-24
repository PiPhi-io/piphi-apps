# Release metadata

This package is released by the trusted root workflows in `PiPhi-io/piphi-apps`; it does not carry package-local publishing automation or credentials.

Before a source release, run the package commands from `piphi-app.json`, the repository app validators, and an AMD64/ARM64 BuildKit build. `scripts/validate.py` rejects drift among the manifest, Python package, runtime constant, app metadata, experience package, Docker release argument, and image reference.

Current source target: `ghcr.io/piphi-io/piphi-network-openepaperlink:0.1.2`.

Publishing, tags, release dispatch, registry synchronization, and governance promotion require separate authorization and review.
