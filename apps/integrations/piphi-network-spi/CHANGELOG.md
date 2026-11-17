# Changelog

## 0.1.4 — 2026-11-17

- Disable physical SPI backends until exact node/bus/chip-select selection is implemented and physically qualified; advertise only opt-in mock operation.
- Derive lock and duplicate-claim identity from backend, exact node, bus, and chip select rather than caller-provided opaque display identity.
- Classify background refresh failures as stale/unavailable and record subsequent recovery without blind hardware retries.
- Run non-root with no host devices, a read-only root filesystem, dropped capabilities, and no-new-privileges.
- Add package validation, dependency audit, lint, build, concurrency, offline/recovery, and outbound runtime-auth-context evidence.

No physical or electrical SPI path is qualified.
