# Changelog

## 0.1.5 — 2026-11-17

- Add immutable OCI source/revision/version labels for exact-image provenance checks.

## 0.1.4 — 2026-11-17

- Narrow version 0.1.4 to opt-in mock operation; reject every physical I2C backend before preflight or I/O.
- Reserve duplicate target claims before I/O using backend/node/bus/address identity, while serializing every address and scan on the exact adapter/bus lock.
- Fail discovery closed on permission and kernel-driver ownership preflight before I/O.
- Run non-root with a required host-device supplementary GID, read-only root filesystem, dropped capabilities, and no-new-privileges.
- Request no host devices or supplementary groups because Core does not yet provide governed dynamic device-GID resolution; retain Core-allocated private ingress and loopback-only examples.
- Classify background refresh failures as stale/unavailable and record subsequent recovery without blind hardware retries.
- Add package validation, dependency audit, lint, build, negative permission, concurrency, offline/recovery, and outbound runtime-auth-context evidence.

Physical and electrical compatibility remains unqualified.
