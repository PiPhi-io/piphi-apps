# Release

Version `0.2.0` targets:

```text
ghcr.io/piphi-io/piphi-zwave-js-sidecar:0.2.0
```

Before tagging `apps/piphi-zwave-js-sidecar/v0.2.0`:

1. Run `npm ci`, high-severity audit, check, tests, validation, and build.
2. Build the container for `linux/amd64` and `linux/arm64`.
3. Run the no-hardware health/config-validation smoke test.
4. Publish the immutable tag through the protected GHCR release environment.
5. Verify the multi-architecture manifest, digest, SBOM, and provenance.
6. Open a separate registry cutover PR pinned to the verified digest.

Software tests do not qualify controller hardware, RF behavior, secure inclusion,
or real-device interoperability. Keep marketplace qualification `unverified`
until physical-controller evidence is recorded.
