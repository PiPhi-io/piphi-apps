# Home Assistant-quality comparison for the PiPhi BLE stack

**Research cutoff:** 2026-11-15

**PiPhi source reviewed:** [`PiPhi-io/piphi-apps@7097de736a30deaa13c8303390fdde7023f3729b`](https://github.com/PiPhi-io/piphi-apps/tree/7097de736a30deaa13c8303390fdde7023f3729b)

**Method:** primary/first-party documentation, source, tests, and CI only. This is a behavioral comparison, not a recommendation to copy upstream code.

## Executive conclusion

PiPhi does **not yet have a Home Assistant-quality BLE stack**.

The intended PiPhi architecture is sounder for its trust boundary than either legacy comparator: a privileged, managed gateway should own BlueZ and deliver privacy-preserving observations, while unprivileged integrations own parsing and presence. The reachable production code does not implement that architecture yet:

* `piphi-ble-gateway-sidecar` is a generic FastAPI runtime scaffold. Applying configuration immediately reports `connected: true`; there is no Bleak, BlueZ, D-Bus, adapter, scanner, observation stream, queue, or recovery code in its dependencies or lifecycle.[^p-gateway-state][^p-gateway-project]
* `piphi-network-passive-ble-monitor` is the only package with real BLE behavior. It directly performs serialized five-second `BleakScanner.discover()` polls, accepts only explicitly configured static MAC addresses, decodes six unencrypted BTHome v2 object IDs into battery/temperature/humidity, and sends current state telemetry.[^p-passive-scan][^p-passive-parser][^p-passive-state] This bypasses the intended gateway boundary and cannot safely be promoted inside the current Core container because the repository deliberately withholds the host D-Bus socket.[^p-passive-readme]
* `piphi-network-bermuda-presence` is also a generic runtime scaffold. It marks a configured record connected without ingesting observations and implements no home/away, receiver topology, distance, freshness, smoothing, or hysteresis behavior.[^p-bermuda-state]

Home Assistant's current Bluetooth integration is the appropriate **quality baseline**, not a feature checklist to reproduce. It centralizes adapter ownership, exposes one normalized observation model to local and remote scanners, arbitrates active/passive/auto scanning, persists bounded scanner history for restart replay, tracks provenance and monotonic time, manages connection slots, performs adapter recovery, and supplies diagnostics and repair guidance.[^ha-init][^ha-manager][^ha-storage][^ha-docs] Its `bluetooth_le_tracker` is explicitly marked `legacy`; it is useful only as a behavioral reference for basic home/away, not as an architecture target.[^ha-legacy-manifest][^ha-legacy-tracker]

The shortest credible route is therefore:

1. make the gateway real and prove its BlueZ lifecycle, observation contract, bounded delivery, and recovery;
2. move the existing BTHome consumer onto that contract and harden freshness/deduplication;
3. add basic presence;
4. only then implement multi-receiver Bermuda-style area inference;
5. expand parser/device breadth in response to measured demand.

## Scope, status vocabulary, and pinned upstreams

### Classification

| Code | Meaning |
|---|---|
| **I — implemented** | Reachable production code executes the behavior; a manifest/catalog claim alone does not count. |
| **M — missing/required** | Required before the applicable PiPhi package can credibly claim Home Assistant-quality behavior. |
| **E — intentionally excluded** | Must stay outside PiPhi's public/state/action boundary for safety or privacy. An internal, least-privilege implementation may still be required. |
| **D — demand-driven** | Useful parity, but not required for the first safe, reliable product slice. |

### Immutable upstream snapshot and licenses

| Upstream | Commit used | License | Role in this review |
|---|---|---|---|
| Home Assistant Core | [`fddf359f543346a9b7cc0068e8e4dc19944dea13`](https://github.com/home-assistant/core/tree/fddf359f543346a9b7cc0068e8e4dc19944dea13) | [Apache-2.0](https://github.com/home-assistant/core/blob/fddf359f543346a9b7cc0068e8e4dc19944dea13/LICENSE.md) | Bluetooth integration, legacy tracker, and their tests. |
| Home Assistant documentation | [`8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f`](https://github.com/home-assistant/home-assistant.io/tree/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f) | [CC BY-NC-SA 4.0](https://github.com/home-assistant/home-assistant.io/blob/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f/LICENSE.md) | First-party deployment and user-facing behavior. |
| Passive BLE Monitor | [`51bf13b994a1f9c8b72c345401f48d81dd96f984`](https://github.com/custom-components/ble_monitor/tree/51bf13b994a1f9c8b72c345401f48d81dd96f984) | [MIT](https://github.com/custom-components/ble_monitor/blob/51bf13b994a1f9c8b72c345401f48d81dd96f984/LICENSE) | Broad parser and legacy direct-adapter comparator. |
| Bermuda | [`b2d0d4059f47cc7a309c629cfd8a1e987346b7ec`](https://github.com/agittins/bermuda/tree/b2d0d4059f47cc7a309c629cfd8a1e987346b7ec) | [MIT](https://github.com/agittins/bermuda/blob/b2d0d4059f47cc7a309c629cfd8a1e987346b7ec/LICENSE) | Multi-receiver area-presence comparator. |

Home Assistant Core pins its transport/model library versions in the Bluetooth manifest and Core project dependencies.[^ha-manifest][^ha-project] The exact release commits used by that snapshot are:

| Library | Version / commit | License | Responsibility relevant here |
|---|---|---|---|
| `habluetooth` | [`7.1.2` / `efc10fb2f55df617780db255667e1af96f6b8277`](https://github.com/Bluetooth-Devices/habluetooth/tree/efc10fb2f55df617780db255667e1af96f6b8277) | [Apache-2.0](https://github.com/Bluetooth-Devices/habluetooth/blob/efc10fb2f55df617780db255667e1af96f6b8277/LICENSE) | scanner/manager behavior, histories, availability, active-scan scheduling |
| `bluetooth-adapters` | [`2.4.0` / `cd018fa4aa94bed091610725b98cb66477d762b8`](https://github.com/Bluetooth-Devices/bluetooth-adapters/tree/cd018fa4aa94bed091610725b98cb66477d762b8) | [Apache-2.0](https://github.com/Bluetooth-Devices/bluetooth-adapters/blob/cd018fa4aa94bed091610725b98cb66477d762b8/LICENSE) | adapter enumeration/details and D-Bus history |
| `bluetooth-auto-recovery` | [`1.6.4` / `1cc791eddb460469f237ce3e9119da2b0ef199dc`](https://github.com/Bluetooth-Devices/bluetooth-auto-recovery/tree/1cc791eddb460469f237ce3e9119da2b0ef199dc) | [MIT](https://github.com/Bluetooth-Devices/bluetooth-auto-recovery/blob/1cc791eddb460469f237ce3e9119da2b0ef199dc/LICENSE) | Linux adapter reset/recovery |
| `bleak-retry-connector` | [`4.7.1` / `0bdeaf11d91aa954ee0973ba06c9aba52ddb9971`](https://github.com/Bluetooth-Devices/bleak-retry-connector/tree/0bdeaf11d91aa954ee0973ba06c9aba52ddb9971) | [MIT](https://github.com/Bluetooth-Devices/bleak-retry-connector/blob/0bdeaf11d91aa954ee0973ba06c9aba52ddb9971/LICENSE) | connection routing, retries, and slot management |
| `bluetooth-data-tools` | [`1.29.24` / `3a1ed8de1d056c99163dcac7589d5b66bb572177`](https://github.com/Bluetooth-Devices/bluetooth-data-tools/tree/3a1ed8de1d056c99163dcac7589d5b66bb572177) | [Apache-2.0](https://github.com/Bluetooth-Devices/bluetooth-data-tools/blob/3a1ed8de1d056c99163dcac7589d5b66bb572177/LICENSE) | coarse monotonic time and Bluetooth data helpers |
| `bleak` | [`3.0.2` / `bb49377d38afb3a9fac9022aaf2c8f59d4ef7cfe`](https://github.com/hbldh/bleak/tree/bb49377d38afb3a9fac9022aaf2c8f59d4ef7cfe) | [MIT](https://github.com/hbldh/bleak/blob/bb49377d38afb3a9fac9022aaf2c8f59d4ef7cfe/LICENSE) | cross-platform scanner/client API |
| `dbus-fast` | [`5.0.22` / `350eed7095f58bdae4d0482ebfd4d9f55a919f75`](https://github.com/Bluetooth-Devices/dbus-fast/tree/350eed7095f58bdae4d0482ebfd4d9f55a919f75) | [MIT](https://github.com/Bluetooth-Devices/dbus-fast/blob/350eed7095f58bdae4d0482ebfd4d9f55a919f75/LICENSE) | async D-Bus transport |
| `home-assistant-bluetooth` | [`2.0.0` / `de507e1357efd048473cf20181687cbe63ac0af1`](https://github.com/home-assistant-libs/home-assistant-bluetooth/tree/de507e1357efd048473cf20181687cbe63ac0af1) | [Apache-2.0](https://github.com/home-assistant-libs/home-assistant-bluetooth/blob/de507e1357efd048473cf20181687cbe63ac0af1/LICENSE) | shared `BluetoothServiceInfo` observation model |

These licenses are recorded for provenance only. PiPhi should specify its own interfaces from behavioral requirements and tests, not transplant upstream implementation.

## What the comparators actually implement

### 1. Home Assistant Bluetooth: current quality baseline

**Boundary.** Core creates one `HomeAssistantBluetoothManager`, adapter registry, connection-slot manager, persistence store, and passive-update processor. Device integrations register filtered callbacks; local `HaScanner` instances and externally supplied `BaseHaRemoteScanner` instances enter the same manager.[^ha-init][^ha-manager] That is the central architectural lesson for PiPhi: adapter ownership and normalized observation distribution belong below parsers and presence logic.

**Linux/BlueZ lifecycle.** HA discovers adapters, ignores crashed/default-address Linux adapters, follows USB changes with debounced rediscovery, starts scanners only after registering them, stops them on unload, and reports start failures as retryable config-entry failures.[^ha-init] First-party docs require BlueZ and D-Bus and explain the exact degraded behavior when container capabilities are absent: no automatic reset, failed management operations, and unreliable/missing raw advertisements.[^ha-docs]

**Scanning and consumers.** Configuration offers Auto, Active, and Passive modes. Auto falls back to Active where hardware cannot support passive scanning. Callback registration carries matcher, connectability, mode, optional active-scan interval/duration, and replay ordering; address-specific consumers can request temporary active scans rather than globally fighting over the adapter.[^ha-config][^ha-manager]

**Observation semantics.** The shared model includes address/name, RSSI, manufacturer/service data, service UUIDs, source receiver, connectability, and monotonic time. The manager maintains all-source and connectable histories, chooses routes across scanners with stale/RSSI safeguards, and can replay history oldest-first, newest-first, or not at all.[^ha-manager][^ha-manager-tests] Per-scanner histories are persisted, stale data is expired at load, and history is restored when a scanner registers.[^ha-storage]

**Operations and recovery.** Connection slots are centralized. Scanner watchdog tests exercise stop errors, inactivity restart, adapter reset, failed restart, and a restart that exceeds the watchdog interval.[^ha-scanner-tests] Diagnostics include manager state, adapter details, and the Linux D-Bus managed-object view; repair issues distinguish degraded permissions and passive fallback.[^ha-diagnostics][^ha-manager]

**Quality evidence.** At the pinned snapshot, the selected Core suites contain 16 Bluetooth test modules plus the legacy tracker module and approximately 243 test functions. They exercise scanner wrappers, callback matching/replay, local and remote scanners, stale availability, roaming, persistence, config flows, diagnostics, watchdog/recovery, and active/passive processors. This is more important than raw test count: hardware-independent failure-path fixtures define expected behavior.

### 2. `bluetooth_le_tracker`: explicitly legacy

Core labels this integration `quality_scale: legacy` and makes it consume the shared Bluetooth integration; it does not own an adapter.[^ha-legacy-manifest] It loads tracked addresses from legacy `known_devices.yaml`, accepts observations from any source, updates home presence on advertisements, refreshes periodically, optionally reads the battery characteristic, and requires five sightings before auto-enrolling a new address.[^ha-legacy-tracker][^ha-legacy-docs]

Useful behavioral parity for PiPhi is limited to **explicit selection, repeated-observation enrollment, and timeout-based home/not-home**. Do not reproduce YAML device storage, MAC-prefixed identity, indiscriminate `track_new_devices`, or direct battery GATT as a presence concern. The first-party page itself warns that rotating addresses undermine MAC-based discovery.[^ha-legacy-docs]

### 3. Passive BLE Monitor: breadth benchmark, migration source—not destination

BLE Monitor is a direct-adapter monolith: it selects HCI interfaces, starts an `HCIdump` thread, parses raw reports, fans parsed results into three Janus queues, and creates sensor, binary-sensor, and tracker entities.[^bm-runtime] It supports a UI/options flow and YAML import, adapter restart/inactivity settings, active scanning, allow-listed MAC/UUID devices, keys, reset periods, filtering/aggregation options, and static-MAC/UUID tracking.[^bm-config]

Its main value as a comparator is parser evidence: 54 parser modules and 56 test modules (about 408 test functions at this snapshot), including encrypted BTHome/Xiaomi/ATC paths, duplicate counters, malformed packets, multiple HCI reports, parser isolation, and many vendor fixtures.[^bm-bthome][^bm-tests] Its CI runs pytest, pre-commit, HACS validation, and Hassfest on pull requests.[^bm-ci]

Its limitations are equally explicit. It cannot consume ESPHome Bluetooth proxies, may conflict with the shared HA Bluetooth integration, and its maintainers advise moving to Core integrations as device support becomes available; the stated goal is eventual deprecation after migration.[^bm-readme] Therefore PiPhi should treat it as a **coverage and fixture catalogue**, not as an adapter architecture target.

### 4. Bermuda: presence behavior benchmark

Bermuda is a consumer of Home Assistant's shared Bluetooth manager. It registers one non-connectable callback, inspects the manager's local/remote scanners, and uses remote scanner timestamps when available.[^bermuda-coordinator][^bermuda-advert] The receiver's HA area supplies room topology. It creates entities only for selected tracked devices even though it maintains transient internal records for observed devices.[^bermuda-device][^bermuda-config]

For every device/receiver pair it retains RSSI, Tx power, source, timestamp, raw and smoothed distance, sample histories, and stale counts. Equal/older remote timestamps are rejected; local USB observations without packet timestamps are deliberately aged and only treated as new when RSSI changes.[^bermuda-advert] It computes RSSI distance with configurable reference power, attenuation, per-receiver offset/radius, velocity rejection, smoothing, stale timeout, and area-switch hysteresis; fresh eligible receivers compete for the area assignment.[^bermuda-distance][^bermuda-area]

Identity support includes stable iBeacon identity and resolvable private address handling through HA's `private_ble_device`/IRK coordinator. Diagnostic output redacts addresses and includes active device/scanner counts, IRK diagnostics, a device dump, and Bluetooth-manager diagnostics.[^bermuda-device][^bermuda-diagnostics]

The options flow exposes scanner health, tracked-device selection, global filters, and guided calibration.[^bermuda-config] The pinned repository has eight test modules and about 32 test functions, with lint, HACS, Hassfest, pytest timeout/parallelization, nightly CI, and signed release archives.[^bermuda-ci][^bermuda-release] This is useful production evidence, but its smaller fixture suite means PiPhi should independently specify and test inference invariants rather than assuming every Bermuda edge case is settled.

## PiPhi implemented behavior and detailed classification

| Capability | HA / comparator behavior | PiPhi production evidence | Class | Assessment |
|---|---|---|---|---|
| Architecture boundary | HA and Bermuda centralize scanner ownership below consumers; BLE Monitor directly owns HCI and is migrating away. | Gateway owns no transport. Passive monitor imports Bleak directly. Bermuda scaffold consumes nothing. | **M** | Establish the gateway as the sole normal adapter owner; integrations consume a versioned observation API. Direct Bleak may remain only in an isolated developer harness. |
| BlueZ/D-Bus adapter lifecycle | Discovery/hotplug, scanner start/stop, degraded mode, watchdog, reset/recovery, repair diagnostics. | No gateway BlueZ dependency or lifecycle. Passive monitor relies on Bleak defaults and logs scan exceptions; its deployment intentionally lacks approved D-Bus access. | **M** | Release blocker for any Core-deployable receiver. |
| Scan modes/filter arbitration | Per-adapter Auto/Active/Passive plus consumer matchers and temporary active-scan demand. | Five-second `discover()` bursts under one process lock; no explicit mode, BlueZ discovery filter, consumer registration, or cross-process arbitration. | **M** | Required to prevent integrations from fighting over BlueZ and to control RF/power cost. |
| Local observations | HA local scanners normalize observations into manager history. | Passive monitor can scan a trusted Linux host directly. Gateway cannot. | **I** (dev only), **M** (platform) | The current implementation is real but in the wrong trust/deployment boundary. |
| Proxy/remote observations | HA accepts remote scanners with receiver identity and packet timestamps; Bermuda prefers these for area accuracy. | No gateway receiver protocol or proxy registration. | **D** initially / **M** before area presence | A single local receiver can ship first; multi-area presence cannot. |
| Observation schema | HA model carries source, time, address, RSSI, Tx power/advert data, connectability, manufacturer/service fields. | `SensorAdvertisement(address, metrics, rssi)` only; parser output is fused to transport. No receiver, observed time, ingest time, address type, connectability, Tx power, advertisement identity, or schema version. | **M** | Define transport-neutral envelope before adding more parsers. |
| Provenance and timestamps | HA/Bermuda distinguish source and monotonic observation time; remote timestamps support stale rejection. | Passive monitor stamps only local processing freshness with `monotonic()` after the whole scan. No per-packet/source timestamps reach telemetry. | **M** | Required for freshness, dedup, replay, and multi-receiver inference. |
| Identity/privacy | HA transports addresses internally; Bermuda supports iBeacon and IRK-derived stable identities and redacts diagnostics. | Passive config is a raw static MAC; telemetry uses runtime device identity but scanning/state retain address. No pseudonymous handle or redaction-specific diagnostic tests. | **M** | Gateway should map authorized observations to opaque handles; raw addresses stay internal and short-lived. |
| Rotating addresses | Bermuda groups iBeacon identities and uses private-BLE/IRK resolution. Legacy tracker documents the static-MAC limitation. | Static MAC exact-match only. | **D** for sensors / **M** for phone-quality presence | Implement only within a tightly scoped private-identity service; never expose IRKs or rotation history. |
| Deduplication | HA histories suppress stale route churn; Bermuda rejects equal/older receiver timestamps; BLE Monitor has parser-specific packet/counter dedup. | A scan collapses results by address, but there is no packet identity/window. BTHome packet ID is parsed only to skip publishing it; repeated packets still publish telemetry. | **M** | Required before streaming/fanout to bound duplicate load without hiding changed values. |
| Freshness/availability | HA learns/falls back advertising intervals; Bermuda has separate advert, distance, scanner, and home-away timeouts. | Non-trigger BTHome becomes disconnected after `3 × poll_interval`; scan errors immediately mark connected false. Trigger-based devices never age out after first sighting. State merges old metrics indefinitely. | **M** | Model observation freshness separately from receiver health and sensor availability; trigger devices need an explicit unknown/stale state. |
| Backpressure/fanout | HA is in-process callback/history based; active processors prevent obsolete queued polls. A PiPhi process boundary requires stronger bounded delivery guarantees. | No gateway stream, queue, capacity, slow-consumer isolation, drop policy, counters, or tests. Runtime telemetry scheduling is called but its internals are outside these packages and does not establish gateway fanout semantics. | **M** | Bounded per-consumer queues and observable overload are release blockers for the gateway. |
| Replay/restart | HA persists per-scanner histories, expires stale records, restores on registration, and gives subscribers explicit replay ordering. | No observation persistence/replay/checkpoint. In-memory `_last_seen` and trigger flags vanish on restart; config startup sync is a no-op in all three packages. | **M** | Persist only a bounded, redacted latest-observation checkpoint; reject stale replay after restart. |
| Passive parser breadth | BLE Monitor has broad vendor/BTHome fixtures; HA distributes parsers into device integrations. | Unencrypted BTHome v2 only: packet ID plus battery, two temperature encodings, and two humidity encodings. | **I** for declared slice; **D** beyond it | Honest narrow support is acceptable. Add formats only with user demand, protocol ownership, normalization, and fixtures. |
| Encrypted passive sensors | BLE Monitor accepts configured keys for several protocols, including BTHome. | Explicitly rejects encrypted BTHome. | **D** | Not required for first release. If added, keys must use a secret store, never config responses/logs/state/diagnostics. |
| Malformed/untrusted payload safety | Both parser comparators have malformed-packet fixtures and isolate unsupported reports. | Length/version/order/range checks exist; unknown BTHome IDs stop parsing rather than guessing. | **I** for narrow decoder | Preserve fail-closed parsing and add fuzz/property bounds before broadening. |
| Basic home/away | Legacy tracker and BLE Monitor can track selected static identities with a consider-home timeout. | Passive `connected` approximates recent receipt only for non-trigger sensors; no presence entity/event or robust timeout. Bermuda scaffold fabricates connected on config. | **M** | Build selected-device presence on observation freshness, not integration connectivity. |
| Multi-receiver topology | HA represents local/remote sources; Bermuda maps receivers to areas and reports coverage. | No receiver IDs, area mapping, topology revision, scanner health, or proxy timestamps. | **M** for Bermuda package | Cannot be implemented correctly until gateway schema exists. |
| Distance | Bermuda stores raw and smoothed per-pair distance with calibration and radius controls. | None. | **D** after basic presence / **M** for Bermuda parity | Label as estimate, retain age/source, and never imply geometric precision. |
| Hysteresis | Bermuda uses freshness, radius, history, relative-distance tests, velocity rejection, and area-switch hysteresis. | None. | **M** for area presence | Must prevent room flapping and must have deterministic trace fixtures. |
| Configuration UX | HA auto-discovers adapters and offers mode options/repairs; BLE Monitor and Bermuda provide rich flows and calibration. | Generic API config. Passive monitor validates a static MAC and 30–3600 s poll interval; gateway/Bermuda accept generic host/API fields unrelated to BLE semantics. | **M** | At minimum: adapter selection/status, consented tracked-device selection, receiver-area mapping, and validation with actionable errors. |
| Diagnostics | HA reports manager/adapters/D-Bus; Bermuda redacts detailed scanner/device/identity diagnostics. | Generic active config IDs, event count, project kind, and endpoint list only. No adapter, scan, queue, parser, freshness, or topology health. | **M** | Add structured, redacted counters and ages; never dump raw D-Bus or advertisements. |
| Tests/fixtures | HA deeply tests transport failures; BLE Monitor deeply tests packets; Bermuda tests inference and runs nightly CI. | Gateway: 4 modules/10 tests, passive: 6/17, Bermuda: 3/7. Most are scaffold contract/catalog checks. Passive has good initial BTHome and scan-boundary tests; no BlueZ fixture exists because gateway behavior does not exist. | **M** | Add deterministic D-Bus/scanner, queue/restart, packet corpus, and presence traces before claims or release. |
| Release gates | Upstreams gate tests and validation; Bermuda signs archives. | The monorepo has reusable full-CI and immutable OCI release workflows, but these three packages remain `legacy-static`: current app CI performs metadata validation only, and `release_plan.py` rejects all three until full CI is enabled.[^p-ci][^p-release][^p-release-plan] Local test runs pass 12 gateway, 24 passive-monitor, and 9 Bermuda cases, but those tests are not release gates. | **M** | Enable full CI, dependency audit, behavioral tests, portable image build, and release evidence before publishing any BLE tranche. Strong packaging cannot substitute for BLE-specific qualification. |

## Prioritized gap matrix with acceptance criteria

Priority is ordered by dependency and risk, not by visible feature appeal.

| Priority | Gap / owner | Concrete acceptance criteria |
|---|---|---|
| **P0** | **Privileged gateway deployment and BlueZ lifecycle** — gateway | On an approved least-privilege host path, enumerate allow-listed adapters over D-Bus; represent BlueZ unavailable, adapter absent/unpowered/rfkill-blocked, permission-degraded, scanning, and recovered states; handle hotplug and BlueZ owner changes without process restart; stop discovery cleanly; never report radio `connected` from configuration alone. Deterministic fake-D-Bus tests cover every transition and permission failure. |
| **P0** | **Versioned observation contract** — gateway + consumers | Envelope has schema version, opaque device handle, receiver ID, receiver kind, observation monotonic time, ingest wall time, age, RSSI, optional Tx power, connectable flag, address type/classification, service UUIDs, manufacturer/service data in explicitly authorized bounded fields, and replay marker. Unknown fields are forward-compatible; malformed/oversized frames are rejected. Raw MAC/name/payload are absent from ordinary telemetry and diagnostics. Contract fixtures are shared by all three packages. |
| **P0** | **Scan arbitration** — gateway | Multiple consumers can atomically register/update/remove matchers and passive/active requirements; one adapter scan plan is derived deterministically; Auto/passive fallback is visible; temporary active requests expire; no consumer can request an unbounded catch-all active scan without explicit policy. Concurrency and cancellation tests prove no duplicate scanner or stuck discovery session. |
| **P0** | **Bounded fanout/backpressure** — gateway | Per-consumer queue capacity, max age, and drop/coalesce rule are explicit; a stalled consumer cannot delay another; queue depth/high-watermark/dropped/coalesced counters are diagnosed; memory remains bounded under a synthetic advertisement flood; disconnect/reconnect and cancellation do not leak tasks. |
| **P0** | **Freshness, dedup, replay, restart** — gateway | Dedup key/window is protocol-neutral and preserves changed RSSI/source where needed; out-of-order observations never replace newer state; only a bounded redacted latest checkpoint is persisted; restart replay is marked and age-checked; stale records cannot resurrect presence; BlueZ/process restart tests prove recovery and monotonic ordering. |
| **P0** | **Safety and redaction tests** — gateway | Logs, `/diagnostics`, events, state, telemetry, persisted checkpoints, and error responses are automatically scanned in tests for raw MACs, IRKs/keys, passkeys, raw payloads, D-Bus trees, and unredacted names. Authorization tests prove one consumer cannot widen another's observation scope or issue D-Bus/GATT calls. |
| **P1** | **Migrate passive monitor to gateway** — passive monitor | Production package has no direct Bleak/BlueZ dependency; consumes the shared envelope; preserves current validated BTHome fixtures and normalized units; parser failure is per-observation and counted; receiver failure is not reported as sensor absence; explicit static-device consent remains required. |
| **P1** | **Availability model** — passive monitor | Separate `receiver_healthy`, `observation_fresh`, and `sensor_available`; derive freshness from observed time and a documented fallback interval; trigger-based devices eventually become unknown/stale rather than permanently connected; old measurements retain timestamp/age and cannot masquerade as current. Tests cover irregular trigger packets, clock/restart boundaries, and scanner outage. |
| **P1** | **BLE diagnostics/config UX** — gateway + passive monitor | User can select approved adapters and tracked devices without typing implementation-centric `host`; status explains permissions, mode fallback, last observation age, parser support, and drops; diagnostics expose only redacted receiver/device handles and aggregate counters; configuration changes are transactional and rollback on failed scan-plan application. |
| **P1** | **BLE qualification gate** — all | CI runs fake-D-Bus/virtual-adapter lifecycle tests, flood/backpressure tests, observation contract compatibility, parser corpus, restart/replay, and privacy redaction. Release evidence records test revision and contract version. A documented multi-hour BlueZ/virtual-adapter soak covers adapter loss/reappearance and daemon restart. Physical-adapter evidence is useful compatibility input, not a release or certification gate. |
| **P2** | **Basic selected-device home/away** — Bermuda presence | Consume opaque identity observations; require explicit selection; use configurable consider-home with minimum/maximum bounds; emit idempotent arrived/left transitions; receiver outage yields unknown/degraded rather than false away; five-sighting enrollment may be offered but must not auto-track by default. Tests include dropped, duplicate, delayed, and replayed observations. |
| **P2** | **Receiver topology** — gateway + Bermuda presence | Stable receiver IDs map to Core devices/areas; topology has a revision and online/last-seen status; local and proxy timestamps normalize to one age contract; area inference excludes missing-area, stale, or unhealthy receivers and reports degraded coverage. |
| **P3** | **Distance and area inference** — Bermuda presence | Maintain raw and filtered RSSI distance per device/receiver with observed time and calibration; cap implausible velocity; support per-receiver offsets/radius; use deterministic hysteresis with documented switch reasons; no area is emitted when all candidates are stale; trace tests cover approach, departure, equal-strength rooms, occlusion, receiver outage, and restart. Distance is clearly labeled estimated. |
| **P3** | **Private/rotating identity** — gateway identity boundary | Add only after threat review. Resolve authorized iBeacon identity and, if demanded, IRK-based private addresses inside a narrow service; expose only opaque stable handles; keys are encrypted at rest and never leave the resolver; deletion removes key and linkage; tests cover rotation, collision/non-match, expiry, redaction, and revocation. |
| **P4** | **Parser/encryption breadth** — passive monitor | Prioritize formats from observed user demand. Every added protocol has an owned specification, real redacted packet fixtures, malformed/truncated/duplicate/encrypted cases, range/unit normalization, entity semantics, and migration notes. Keys use secret references. No target count of BLE Monitor parsers is a release criterion. |
| **P4** | **GATT operations** — gateway | Add only for a named integration need. Per-device/service/characteristic allow-list, centralized connection slots, deadlines/cancellation, retries, audit record, and write risk classification are required. Presence and passive parsing remain unable to request GATT. |

## Safety and privacy exclusions

The following are deliberate non-goals even where upstream software can technically do them:

1. **No unrestricted host D-Bus socket API.** The gateway may hold narrowly approved host access; child integrations receive typed BLE observations and approved operations, never a generic D-Bus tunnel.
2. **No raw persistent identity in public state.** Raw MAC addresses, changing-address histories, IRKs, LTKs/link keys, passkeys, and unredacted names must not appear in entities, telemetry, events, automation conditions/actions, diagnostics, or support bundles.
3. **No arbitrary observation injection.** Test fixtures use a test-only boundary. Production consumers cannot spoof receivers, RSSI, timestamps, or identity links.
4. **No ambient device inventory as entities.** Discovery may maintain short-lived internal candidates, but only explicitly selected devices become PiPhi devices/entities. This follows the useful part of Bermuda's separation between transient observations and configured entities.[^bermuda-device]
5. **No global catch-all export.** A parser/consumer receives only fields and device/protocol scopes authorized by its registration; passive presence does not justify retaining every nearby identifier.
6. **No arbitrary pairing, trust, connection, or GATT writes.** Such operations remain excluded until a specific integration defines least-privilege policy, user confirmation, timeouts, and audit behavior.
7. **No destructive host control.** Child integrations cannot reset all adapters, remove bonds globally, disable host Bluetooth, advertise/spoof, provision mesh, or claim audio/profile ownership.
8. **No false precision.** RSSI-derived distance is an estimate and area is an inference. Do not expose precise coordinates or confidence unsupported by calibrated observations.
9. **No silent replay as live presence.** Restart checkpoints are bounded, marked, and freshness-checked. A replay may warm parser state but cannot independently produce an arrival.
10. **No keys in ordinary configuration documents.** If encrypted advertisements become demand-driven work, configuration stores secret references; diagnostic and logging paths prove redaction.

These exclusions are stricter than BLE Monitor's direct HCI/key model and Bermuda's in-process access to HA identity internals. They are appropriate because PiPhi crosses container/process and telemetry boundaries.

## Recommended staged tranche order

### Tranche 0 — make claims honest

* Keep gateway and Bermuda presence marked pre-production.
* Stop equating configured state with radio connectivity in both scaffolds.
* Declare the existing passive monitor a trusted-host developer slice until the approved gateway exists.
* Freeze a v1 observation threat model and schema before implementation.

**Exit:** documentation, manifest claims, diagnostics, and reachable behavior agree.

### Tranche 1 — gateway transport foundation

Implement P0 adapter lifecycle, scan arbitration, normalized observations, bounded fanout, privacy, restart, and deterministic failure fixtures. Validate local BlueZ first; do not add proxies, parsers, or GATT to hide transport risk.

**Exit:** one local or virtual adapter can run for the soak period, survive BlueZ restart and adapter loss/reappearance, bound memory under flood/slow consumer, and emit only redacted contract-conformant observations. Physical hardware certification is not required.

### Tranche 2 — narrow passive sensor product

Move BTHome parsing behind the gateway, retain the existing fail-closed decoder, repair availability semantics, and add useful diagnostics/config UX. Support only current unencrypted temperature/humidity/battery/RSSI initially.

**Exit:** current parser tests plus end-to-end gateway fixtures pass; trigger/non-trigger freshness is correct through outage and restart; no direct production Bleak dependency remains in the integration.

### Tranche 3 — basic presence and remote receivers

Add explicitly selected home/away behavior and then the remote/proxy receiver protocol with source timestamps and topology health. Do not start with distance.

**Exit:** presence remains stable under duplicates, delayed packets, receiver outage, and replay; remote receiver provenance is observable and redacted.

### Tranche 4 — Bermuda-style area presence

Add receiver-area mapping, per-pair histories, calibration, estimated distance, stale exclusion, smoothing, velocity guards, and hysteresis. Use recorded traces as executable acceptance tests.

**Exit:** deterministic room transitions, switch reasons, degraded coverage, and no stale-area resurrection across restart.

### Tranche 5 — demand-driven breadth

Add rotating/private identity, encrypted advertisements, additional BTHome objects/vendor formats, and narrowly allow-listed GATT only when product demand pays for their threat model, fixtures, diagnostics, and maintenance.

**Exit:** each feature independently satisfies its security and protocol acceptance criteria; breadth never weakens the gateway boundary.

## Test and release evidence summary

| Project | Snapshot evidence | What it proves / does not prove |
|---|---|---|
| HA Core Bluetooth + legacy tracker | 17 selected test modules, ~243 test functions; extensive fake scanner/D-Bus adapter fixtures and failure paths | Strong behavioral baseline for manager/scanner lifecycle, history, callbacks, mode/config, diagnostics, recovery. Counts are snapshot observations, not quality scores. |
| BLE Monitor | 56 parser/integration test modules, ~408 test functions; pytest + pre-commit + HACS + Hassfest CI | Strong parser/device corpus and regression culture; does not validate shared-adapter architecture. |
| Bermuda | 8 test modules, ~32 test functions; lint/HACS/Hassfest/pytest nightly; signed release ZIP | Evidence of maintained integration/release process and some inference regressions; not a complete oracle for area math. |
| PiPhi gateway | 4 test modules, 10 test functions / 12 collected cases pass locally | Runtime port, contract, conformance, catalog shape—not BlueZ behavior. Tests are not currently wired into app CI. |
| PiPhi passive monitor | 6 test modules, 17 test functions / 24 collected cases pass locally | Useful BTHome happy/malformed fixtures, configured-address filtering, RSSI, and basic stale behavior; no gateway/BlueZ/restart/flood fixtures. Tests are not currently wired into app CI. |
| PiPhi Bermuda presence | 3 test modules, 7 test functions / 9 collected cases pass locally | Scaffold contract/catalog only; no presence behavior. Tests are not currently wired into app CI. |

The PiPhi monorepo already has a solid supply-chain release frame available: per-app qualification, protected-branch check, immutable image digest evidence, SBOM/provenance, and attestation.[^p-release] None of these three packages has opted into that path yet; all remain `legacy-static`, and release planning fails closed.[^p-release-plan] The first tranche must enable full CI as well as domain qualification. No BLE package should be promoted merely because local scaffold tests pass.

## Primary-source references

[^ha-manifest]: Home Assistant, [`bluetooth/manifest.json`](https://github.com/home-assistant/core/blob/fddf359f543346a9b7cc0068e8e4dc19944dea13/homeassistant/components/bluetooth/manifest.json#L1-L27), pinned requirements and integration metadata.
[^ha-project]: Home Assistant, [`pyproject.toml`](https://github.com/home-assistant/core/blob/fddf359f543346a9b7cc0068e8e4dc19944dea13/pyproject.toml#L45-L58), Core-level `home-assistant-bluetooth` dependency.
[^ha-init]: Home Assistant, [`bluetooth/__init__.py`](https://github.com/home-assistant/core/blob/fddf359f543346a9b7cc0068e8e4dc19944dea13/homeassistant/components/bluetooth/__init__.py#L153-L264) and [adapter setup](https://github.com/home-assistant/core/blob/fddf359f543346a9b7cc0068e8e4dc19944dea13/homeassistant/components/bluetooth/__init__.py#L287-L447).
[^ha-manager]: Home Assistant, [`bluetooth/manager.py`](https://github.com/home-assistant/core/blob/fddf359f543346a9b7cc0068e8e4dc19944dea13/homeassistant/components/bluetooth/manager.py#L66-L363), callback registration/replay and local/remote scanner registration.
[^ha-storage]: Home Assistant, [`bluetooth/storage.py`](https://github.com/home-assistant/core/blob/fddf359f543346a9b7cc0068e8e4dc19944dea13/homeassistant/components/bluetooth/storage.py#L1-L72), stale expiry and persisted scanner history.
[^ha-config]: Home Assistant, [`bluetooth/config_flow.py`](https://github.com/home-assistant/core/blob/fddf359f543346a9b7cc0068e8e4dc19944dea13/homeassistant/components/bluetooth/config_flow.py#L51-L84), scanning mode options.
[^ha-diagnostics]: Home Assistant, [`bluetooth/diagnostics.py`](https://github.com/home-assistant/core/blob/fddf359f543346a9b7cc0068e8e4dc19944dea13/homeassistant/components/bluetooth/diagnostics.py#L14-L27).
[^ha-manager-tests]: Home Assistant, [`test_manager.py`](https://github.com/home-assistant/core/blob/fddf359f543346a9b7cc0068e8e4dc19944dea13/tests/components/bluetooth/test_manager.py#L72-L193) and [stale roaming tests](https://github.com/home-assistant/core/blob/fddf359f543346a9b7cc0068e8e4dc19944dea13/tests/components/bluetooth/test_manager.py#L263-L427).
[^ha-scanner-tests]: Home Assistant, [`test_scanner.py`](https://github.com/home-assistant/core/blob/fddf359f543346a9b7cc0068e8e4dc19944dea13/tests/components/bluetooth/test_scanner.py#L44-L476), scanner watchdog/recovery fixtures.
[^ha-docs]: Home Assistant documentation, [`bluetooth.markdown`](https://github.com/home-assistant/home-assistant.io/blob/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f/source/_integrations/bluetooth.markdown#L30-L136), Linux requirements, degraded permissions, modes, and legacy exclusivity warning.
[^ha-legacy-manifest]: Home Assistant, [`bluetooth_le_tracker/manifest.json`](https://github.com/home-assistant/core/blob/fddf359f543346a9b7cc0068e8e4dc19944dea13/homeassistant/components/bluetooth_le_tracker/manifest.json#L1-L11), explicit `quality_scale: legacy`.
[^ha-legacy-tracker]: Home Assistant, [`bluetooth_le_tracker/device_tracker.py`](https://github.com/home-assistant/core/blob/fddf359f543346a9b7cc0068e8e4dc19944dea13/homeassistant/components/bluetooth_le_tracker/device_tracker.py#L53-L236).
[^ha-legacy-docs]: Home Assistant documentation, [`bluetooth_le_tracker.markdown`](https://github.com/home-assistant/home-assistant.io/blob/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f/source/_integrations/bluetooth_le_tracker.markdown#L10-L55).
[^bm-readme]: Passive BLE Monitor, [`README.md`](https://github.com/custom-components/ble_monitor/blob/51bf13b994a1f9c8b72c345401f48d81dd96f984/README.md#L1-L108), proxy limitation and Core migration/deprecation stance.
[^bm-runtime]: Passive BLE Monitor, [`__init__.py`](https://github.com/custom-components/ble_monitor/blob/51bf13b994a1f9c8b72c345401f48d81dd96f984/custom_components/ble_monitor/__init__.py#L465-L500) and [configuration/startup](https://github.com/custom-components/ble_monitor/blob/51bf13b994a1f9c8b72c345401f48d81dd96f984/custom_components/ble_monitor/__init__.py#L207-L397).
[^bm-config]: Passive BLE Monitor, [`config_flow.py`](https://github.com/custom-components/ble_monitor/blob/51bf13b994a1f9c8b72c345401f48d81dd96f984/custom_components/ble_monitor/config_flow.py#L67-L131) and [device options](https://github.com/custom-components/ble_monitor/blob/51bf13b994a1f9c8b72c345401f48d81dd96f984/custom_components/ble_monitor/config_flow.py#L190-L384).
[^bm-bthome]: Passive BLE Monitor, [`ble_parser/bthome.py`](https://github.com/custom-components/ble_monitor/blob/51bf13b994a1f9c8b72c345401f48d81dd96f984/custom_components/ble_monitor/ble_parser/bthome.py#L130-L180) and [duplicate/key handling](https://github.com/custom-components/ble_monitor/blob/51bf13b994a1f9c8b72c345401f48d81dd96f984/custom_components/ble_monitor/ble_parser/bthome.py#L330-L380).
[^bm-tests]: Passive BLE Monitor, [`custom_components/ble_monitor/test`](https://github.com/custom-components/ble_monitor/tree/51bf13b994a1f9c8b72c345401f48d81dd96f984/custom_components/ble_monitor/test).
[^bm-ci]: Passive BLE Monitor, [`test_commit.yml`](https://github.com/custom-components/ble_monitor/blob/51bf13b994a1f9c8b72c345401f48d81dd96f984/.github/workflows/test_commit.yml#L1-L38).
[^bermuda-coordinator]: Bermuda, [`coordinator.py`](https://github.com/agittins/bermuda/blob/b2d0d4059f47cc7a309c629cfd8a1e987346b7ec/custom_components/bermuda/coordinator.py#L118-L297), manager/scanner boundary and callback registration.
[^bermuda-device]: Bermuda, [`bermuda_device.py`](https://github.com/agittins/bermuda/blob/b2d0d4059f47cc7a309c629cfd8a1e987346b7ec/custom_components/bermuda/bermuda_device.py#L63-L149) and [private/iBeacon identity](https://github.com/agittins/bermuda/blob/b2d0d4059f47cc7a309c629cfd8a1e987346b7ec/custom_components/bermuda/bermuda_device.py#L151-L230).
[^bermuda-advert]: Bermuda, [`bermuda_advert.py`](https://github.com/agittins/bermuda/blob/b2d0d4059f47cc7a309c629cfd8a1e987346b7ec/custom_components/bermuda/bermuda_advert.py#L48-L204), per-receiver provenance, timestamp rejection, and histories.
[^bermuda-distance]: Bermuda, [`bermuda_advert.py`](https://github.com/agittins/bermuda/blob/b2d0d4059f47cc7a309c629cfd8a1e987346b7ec/custom_components/bermuda/bermuda_advert.py#L265-L389) and [filtering](https://github.com/agittins/bermuda/blob/b2d0d4059f47cc7a309c629cfd8a1e987346b7ec/custom_components/bermuda/bermuda_advert.py#L392-L493).
[^bermuda-area]: Bermuda, [`coordinator.py`](https://github.com/agittins/bermuda/blob/b2d0d4059f47cc7a309c629cfd8a1e987346b7ec/custom_components/bermuda/coordinator.py#L1318-L1490), freshness/radius selection and hysteresis.
[^bermuda-config]: Bermuda, [`config_flow.py`](https://github.com/agittins/bermuda/blob/b2d0d4059f47cc7a309c629cfd8a1e987346b7ec/custom_components/bermuda/config_flow.py#L125-L325) and [calibration flow](https://github.com/agittins/bermuda/blob/b2d0d4059f47cc7a309c629cfd8a1e987346b7ec/custom_components/bermuda/config_flow.py#L327-L496).
[^bermuda-diagnostics]: Bermuda, [`diagnostics.py`](https://github.com/agittins/bermuda/blob/b2d0d4059f47cc7a309c629cfd8a1e987346b7ec/custom_components/bermuda/diagnostics.py#L16-L35).
[^bermuda-ci]: Bermuda, [`tests.yaml`](https://github.com/agittins/bermuda/blob/b2d0d4059f47cc7a309c629cfd8a1e987346b7ec/.github/workflows/tests.yaml#L1-L109).
[^bermuda-release]: Bermuda, [`release.yaml`](https://github.com/agittins/bermuda/blob/b2d0d4059f47cc7a309c629cfd8a1e987346b7ec/.github/workflows/release.yaml#L1-L52).
[^p-gateway-state]: PiPhi, [`piphi-ble-gateway-sidecar/state.py`](https://github.com/PiPhi-io/piphi-apps/blob/7097de736a30deaa13c8303390fdde7023f3729b/apps/services/piphi-ble-gateway-sidecar/src/piphi_ble_gateway_sidecar/state.py#L39-L101).
[^p-gateway-project]: PiPhi, [`piphi-ble-gateway-sidecar/pyproject.toml`](https://github.com/PiPhi-io/piphi-apps/blob/7097de736a30deaa13c8303390fdde7023f3729b/apps/services/piphi-ble-gateway-sidecar/pyproject.toml#L1-L17) and [lifecycle](https://github.com/PiPhi-io/piphi-apps/blob/7097de736a30deaa13c8303390fdde7023f3729b/apps/services/piphi-ble-gateway-sidecar/src/piphi_ble_gateway_sidecar/lifecycle.py#L1-L20).
[^p-passive-scan]: PiPhi, [`scanner.py`](https://github.com/PiPhi-io/piphi-apps/blob/7097de736a30deaa13c8303390fdde7023f3729b/apps/integrations/piphi-network-passive-ble-monitor/src/piphi_network_passive_ble_monitor/scanner.py#L1-L37).
[^p-passive-parser]: PiPhi, [`bthome.py`](https://github.com/PiPhi-io/piphi-apps/blob/7097de736a30deaa13c8303390fdde7023f3729b/apps/integrations/piphi-network-passive-ble-monitor/src/piphi_network_passive_ble_monitor/bthome.py#L1-L66).
[^p-passive-state]: PiPhi, [`state.py`](https://github.com/PiPhi-io/piphi-apps/blob/7097de736a30deaa13c8303390fdde7023f3729b/apps/integrations/piphi-network-passive-ble-monitor/src/piphi_network_passive_ble_monitor/state.py#L81-L196).
[^p-passive-readme]: PiPhi, [`piphi-network-passive-ble-monitor/README.md`](https://github.com/PiPhi-io/piphi-apps/blob/7097de736a30deaa13c8303390fdde7023f3729b/apps/integrations/piphi-network-passive-ble-monitor/README.md#L1-L19).
[^p-bermuda-state]: PiPhi, [`piphi-network-bermuda-presence/state.py`](https://github.com/PiPhi-io/piphi-apps/blob/7097de736a30deaa13c8303390fdde7023f3729b/apps/integrations/piphi-network-bermuda-presence/src/piphi_network_bermuda_presence/state.py#L39-L101) and [lifecycle](https://github.com/PiPhi-io/piphi-apps/blob/7097de736a30deaa13c8303390fdde7023f3729b/apps/integrations/piphi-network-bermuda-presence/src/piphi_network_bermuda_presence/lifecycle.py#L1-L20).
[^p-ci]: PiPhi, [`reusable-app-ci.yml`](https://github.com/PiPhi-io/piphi-apps/blob/7097de736a30deaa13c8303390fdde7023f3729b/.github/workflows/reusable-app-ci.yml#L29-L83).
[^p-release]: PiPhi, [`release-app.yml`](https://github.com/PiPhi-io/piphi-apps/blob/7097de736a30deaa13c8303390fdde7023f3729b/.github/workflows/release-app.yml#L71-L183).
[^p-release-plan]: PiPhi, [`app_tooling.py`](https://github.com/PiPhi-io/piphi-apps/blob/7097de736a30deaa13c8303390fdde7023f3729b/scripts/app_tooling.py#L268-L279), release planning rejects `legacy-static` packages.
