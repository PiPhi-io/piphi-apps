# Release

Version `0.3.0` targets:

```text
ghcr.io/piphi-io/piphi-network-zwave:0.3.0
```

Before tagging `apps/piphi-network-zwave/v0.3.0`:

1. Install the frozen lockfile and run tests, scaffold validation, and publish checks.
2. Build and smoke-test the parent with sidecar `0.3.0` using authentication.
3. Build the parent image for `linux/amd64` and `linux/arm64`.
4. Publish through the protected GHCR release workflow.
5. Verify the immutable digest, architecture imports, SBOM, and provenance.
6. Cut over the registry in a separate PR pinned to the verified digest.

Software tests do not qualify controller hardware, RF behavior, secure inclusion,
or real-device interoperability. Keep marketplace qualification `unverified` and
rollout at zero until physical-controller evidence is recorded.
