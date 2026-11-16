# Release image qualification

Run the release-image gate against the exact image digest or local tag that will be published:

```bash
docker build -t piphi-network-matter:candidate .
npm run qualify:release-image -- piphi-network-matter:candidate
```

Remote images are pulled automatically when they are not already present in the local Docker
cache. Digest-pinned references are preferred for post-publication verification.

Slow builders or hosts can extend the startup deadline:

```bash
npm run qualify:release-image -- piphi-network-matter:candidate --timeout-seconds 120
```

## Gate coverage

The executable harness validates that the image:

- declares `/app/data` as a volume and starts under a non-root UID;
- actually runs with Docker host networking and can reach a sidecar fixture on the host loopback;
- authenticates every sidecar snapshot and event request with the production Bearer token;
- rejects missing and incorrect Core credentials while accepting the production runtime token;
- becomes truthfully healthy and projects the fixture's Matter entity; and
- retains the stable entity ID, configured alias, and `/config` record after the parent container
  is removed and recreated with the same named volume.

The fixture is deliberately outside the parent container, so a pass exercises the built parent
artifact and its real network boundary rather than importing parent source into the harness.

The harness installs interrupt handlers and also cleans up in a `finally` path. Containers and the
named volume use the `piphi-matter-parent-qualification-<pid>-<timestamp>` prefix. If the host or
Docker daemon is killed too abruptly for cleanup to run, remove only resources with that prefix
after confirming no qualification is active.

Do not substitute `npm test` for this gate: unit and two-process tests do not prove the OCI user,
volume declaration, host network mode, or persistence behavior of the release artifact.

Standard CI separately enforces at least 95% line coverage over the parent production modules;
the current report is 100%. The image gate remains manual because it requires a Linux Docker host.
