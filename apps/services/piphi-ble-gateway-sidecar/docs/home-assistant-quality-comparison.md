# Home Assistant-quality rebaseline for the PiPhi BLE stack

**Review date:** 2026-11-15

**PiPhi baseline:** [`PiPhi-io/piphi-apps@7d3c6c3250757f4df927f1f98ce643f2d2917274`](https://github.com/PiPhi-io/piphi-apps/tree/7d3c6c3250757f4df927f1f98ce643f2d2917274) plus the Bronze-candidate changes documented here

**Upstream standard:** [Home Assistant Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/) and its [rule list](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/)

## Conclusion

The BLE gateway, Passive BLE Monitor, and Bermuda Presence now qualify for a
**PiPhi Bronze** claim over their explicitly documented product slices. Bronze is
Home Assistant's baseline quality tier: UI-driven typed setup, tested setup and
uniqueness behavior, stable identity, transparent dependencies, lifecycle-safe
runtime state, and complete introductory user documentation.

This is not a claim of feature parity with Home Assistant's complete Bluetooth
manager, the full Passive BLE Monitor parser catalogue, or every Bermuda feature.
Protocol breadth and quality are separate. Deferred capabilities remain planned
or excluded in each machine-readable capability catalog and are not advertised.

The packages are not yet Silver, Gold, or Platinum. Silver requires measured
coverage above 95% across every module plus the remaining reliability and
ownership rules. Gold adds discovery, reconfiguration, repairs, translations,
and comprehensive user experience. Platinum adds fully strict typing and the
remaining technical-excellence rules.

## Architecture and production evidence

| Area | Current PiPhi evidence | Assessment |
|---|---|---|
| Adapter ownership | Only the managed gateway owns Bleak scanning. Passive parsing and presence consume the authenticated gateway contract. | Meets the shared-manager architectural requirement. |
| Linux lifecycle | A narrow BlueZ Adapter1 adapter reports bounded health, reads rfkill state, may power only the selected adapter, and supervises scanner restart. | Deterministic fake-BlueZ tests cover power loss, disappearance, reappearance, and retry. No broad host reset exists. |
| Windows lifecycle | Bleak selects WinRT without importing D-Bus. Native `windows-latest` CI installs, tests, and builds the universal wheel. | Qualified native process artifact. |
| Observation contract | `piphi.ble.observation.v1` includes opaque handle, receiver provenance, monotonic observation time, ingest time, replay marker, bounded advertisement fields, RSSI, optional Tx power, connectability, and address classification. | Stable privacy-preserving consumer boundary. |
| Privacy and authorization | Raw addresses, names, keys, unrestricted D-Bus, raw payloads, pairing, arbitrary GATT, and host resets do not cross the contract. Empty catch-all matchers are rejected and consumer credentials are scoped. | Stronger boundary than the in-process comparators require. |
| Delivery and restart | Per-consumer bounded queues, drop/coalesce counters, deduplication, out-of-order rejection, bounded redacted checkpoints, marked replay, and cursor-gap snapshots. | Slow consumers and restart cannot create unbounded memory or live-presence replay. |
| Passive sensor slice | Explicit opaque handle; unencrypted BTHome v2 battery, temperature, humidity, and RSSI; packet-ID deduplication; malformed-frame isolation; independent receiver/freshness/availability state. | Honest narrow product slice. Parser breadth remains demand-driven. |
| Presence slice | Explicit selected handles; home/away/unknown; receiver outage degrades to unknown; topology health; estimated distance; stale exclusion; smoothing, velocity guard, radius, and deterministic area hysteresis. | Core Bermuda-style inference is implemented without claiming coordinates. |
| Setup quality | Passive and Bermuda setup validate gateway registration before committing configuration. Bermuda replacement is transactional, preserving the old entry if validation fails. | Meets Bronze test-before-configure intent. |
| CI and supply chain | Full app CI, dependency audit, behavior tests, contract validation, Linux OCI builds, native Windows gateway qualification, immutable digests, checksums, and OIDC/Sigstore provenance. | Release evidence is reproducible and externally verifiable. |

## Bronze rule adaptation

Home Assistant's rules refer to in-process `ConfigEntry`, entity platform, and
Brands mechanics. PiPhi applies the protected behavior rather than pretending
those classes exist:

- config-flow rules map to `/ui-config`, typed `/config`, transactional external
  validation, stable config IDs, and Runtime TestKit coverage;
- entity rules map to stable Runtime SDK device/entity IDs, contextual names,
  lifecycle-owned tasks, and deterministic deconfiguration;
- service-action setup maps to process-level Runtime SDK automation registration;
- Home Assistant Brands is exempt because these are external PiPhi packages;
  publisher, support, compatibility, access, and documentation metadata is
  mandatory instead;
- the gateway is a singleton platform service, so user device config-flow rules
  are exempt while its authenticated consumer-registration API is fully tested.

Each package's `quality-scale.yaml` lists all 20 Bronze rules, concrete evidence,
and a reason for every exemption. Package CI rejects a Bronze manifest whose
checklist is missing, incomplete, or points to absent evidence.

## Package ratings and boundaries

### BLE gateway sidecar — Bronze

The rated scope is one local Bleak scanner on Linux/BlueZ or Windows/WinRT,
authorized matcher registration, normalized observation delivery, bounded replay,
health diagnostics, and selected-adapter Linux recovery.

Remote receiver ingestion, rotating/private identity resolution, connection-slot
management, pairing, and allow-listed GATT are not in this rating. Pairing,
arbitrary GATT, raw identity export, unrestricted D-Bus, spoofing, and destructive
host control remain explicitly excluded.

### Passive BLE Monitor — Bronze

The rated scope is unencrypted BTHome v2 battery, temperature, humidity, and RSSI
for one explicitly approved opaque handle. Gateway failure and measurement
staleness are distinct. Replay cannot create freshness, and malformed packets are
isolated.

Encrypted BTHome, vendor-specific formats, binary sensors, scales, air-quality
objects, and broad parser coverage remain planned or excluded. They are not
required to make the supported slice reliable.

### Bermuda Presence — Bronze

The rated scope is explicitly selected opaque handles, bounded home/away/unknown
semantics, configured receiver-area topology, degraded coverage, RSSI distance
estimates, and deterministic area switching. Initial gateway validation is
transactional; a later outage yields unknown rather than false away.

Private identity keys, precise coordinates, ambient auto-tracking, observation
injection, and adapter control remain excluded. Guided calibration UX and gateway
remote-receiver provisioning remain future Gold-level product work.

## Remaining tier work

### Silver blockers

1. Enforce and demonstrate more than 95% coverage for every runtime module.
2. Standardize one-time unavailable/recovered logging and user-visible
   authentication recovery across Runtime SDK packages.
3. Record explicit code ownership in repository governance metadata.
4. Add unload/reload and reauthentication acceptance tests where applicable.

### Gold blockers

1. Add discovery and reconfiguration flows where safe; explicit selection must
   remain mandatory before entities are created.
2. Add translated entity names, icons, and user-facing errors.
3. Add repair guidance for permissions, unhealthy adapters, invalid topology,
   expired credentials, and unsupported payloads.
4. Complete guided calibration and richer diagnostics without weakening privacy.
5. Document supported devices and automation examples as parser demand expands.

### Platinum blockers

1. Apply strict typing to every runtime module, not selected core modules only.
2. Keep all transport dependencies asynchronous and verify resource efficiency
   under sustained observation load.

## Safety invariants

Quality work must not weaken these boundaries:

1. no unrestricted host D-Bus API;
2. no raw persistent identity, names, keys, or advertisement dumps in public data;
3. no ambient device inventory as entities;
4. no catch-all export to child integrations;
5. no arbitrary pairing, GATT, observation injection, or broad host reset;
6. no false precision for RSSI distance or area inference;
7. no replay treated as live presence;
8. no secrets in ordinary public configuration, diagnostics, events, or logs.

## Release evidence

Gateway `0.3.0` was published from source revision
`7d3c6c3250757f4df927f1f98ce643f2d2917274` with Linux amd64/arm64 OCI digest
`sha256:40ac79bb4bb39b728eca8e16e58ef2c41f190c8cb324debbe18115ffb886be89`
and wheel SHA-256
`fecd63fb75506de2de42207d8f4b7c45160ebba43f4eededb17aad449e0d4691`.
Both artifacts have GitHub OIDC/Sigstore build-provenance attestations. The Bronze
metadata and transactional setup change are patch releases and require their own
normal release qualification before marketplace promotion.
