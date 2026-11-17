# Changelog

## 0.1.4 — 2026-11-17

- Restrict physical operation to the exact `/dev/i2c-1` node and Bosch BME680/BME280/BMP280 contracts; reject unselectable bridges, AHT20, PMSA003I, and unsafe generic reads.
- Derive lock and duplicate-claim identity from backend, exact node, bus, and address rather than caller-provided opaque display identity.
- Fail discovery closed on permission and kernel-driver ownership preflight before I/O.
- Run non-root with a required host-device supplementary GID, read-only root filesystem, dropped capabilities, and no-new-privileges.
- Classify background refresh failures as stale/unavailable and record subsequent recovery without blind hardware retries.
- Add package validation, dependency audit, lint, build, negative permission, concurrency, offline/recovery, and outbound runtime-auth-context evidence.

Physical and electrical compatibility remains unqualified.
