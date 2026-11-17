# Changelog

## 0.1.4 — 2026-11-17

- Disable physical SPI backends until exact node/bus/chip-select selection is implemented and physically qualified; advertise only opt-in mock operation.
- Reserve duplicate target claims before I/O using backend/node/bus/chip-select identity, with adapter-scoped operation serialization ready for future physical backends.
- Classify background refresh failures as stale/unavailable and record subsequent recovery without blind hardware retries.
- Run non-root with no host devices, a read-only root filesystem, dropped capabilities, and no-new-privileges.
- Require Core-allocated private ingress; examples publish only on loopback.
- Add package validation, dependency audit, lint, build, concurrency, offline/recovery, and outbound runtime-auth-context evidence.

No physical or electrical SPI path is qualified.
