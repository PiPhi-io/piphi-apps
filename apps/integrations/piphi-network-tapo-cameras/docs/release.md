# Release

Source, immutable artifact, independent artifact verification, and exact-digest
registry synchronization are separate gates.

Before tagging `apps/piphi-network-tapo-cameras/v0.2.0`:

1. Run `pdm lock --check` and `pdm install --check -G dev`.
2. Run `pdm run pytest`, `pdm run python scripts/validate.py`, and
   `pdm run python scripts/check_release.py apps/piphi-network-tapo-cameras/v0.2.0`.
3. Build the locked image for `linux/amd64` and `linux/arm64`.
4. Confirm the image runs as non-root and `/health` is public while other routes
   fail closed without the runtime token.
5. Run the deterministic transport, restart, outage/recovery, prohibited-command,
   and secret-canary tests against the exact image.
6. Publish `ghcr.io/piphi-io/piphi-network-tapo-cameras:0.2.0` without changing
   draft publication, 0% rollout, unrated quality, or unverified qualification.
7. Independently verify the immutable digest, then synchronize that exact digest
   to the registry in a separate PR.

Physical qualification remains separate. It should cover at least one powered
camera and one powered doorbell across restart, invalid credentials, outage,
privacy on/off, and recovery before governance promotion.
