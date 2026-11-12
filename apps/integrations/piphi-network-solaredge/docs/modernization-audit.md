# SolarEdge modernization audit

Reference: the maintained Airthings runtime and `airthings-air-quality`
integration-owned experience package.

## Gaps found in the 0.1 implementation

- The runtime embedded and served two independently built sandboxed JavaScript
  bundles. Airthings registers one independently signed declarative experience.
- Widget manifests used the legacy embedded-package shape and had no binding
  slots, integration source constraints, freshness requirements, package themes,
  presentation boundary, interaction targets, or Core card replacement rules.
- Telemetry mixed live power, summary totals, and operational state into every
  delivery. It did not attach an explicit sample time, deduplicate slow summary
  readings, track Core delivery freshness, or retain the last good state after a
  read failure.
- Tests exercised local route shapes but did not send real Runtime SDK telemetry
  to a TestKit Core or validate a signed multi-widget package against Core.
- The container built Node assets, ran as root, and had no image health check.

## 0.2 target implemented

- One package, `io.piphi.solaredge-solar-energy`, owns both `energy-flow` and
  `production-summary` declarative widgets.
- Core owns the card shell, typography, keyboard/focus semantics, accessible
  native primitives, history/popout/details/refresh actions, and stale-state
  presentation. The integration supplies bounded theme tokens and meaningful
  labels for each reading and interaction target.
- Every binding is read-only and restricted to `piphi-network-solaredge`.
  Live-flow slots prefer streaming and become stale after 20 minutes; summary
  slots use snapshots and become stale after two hours.
- Live power and connectivity are delivered on each successful poll. Summary
  totals are sent only when the vendor marker or values change. Failed reads
  keep the last good measurements, emit an unavailable heartbeat, and appear in
  health and diagnostics freshness metadata.
- The capability catalog explicitly records implemented, planned, and excluded
  surface area. OAuth V2 remains planned; equipment-level modeling and mutating
  controls are intentionally excluded from this read-only release candidate.
