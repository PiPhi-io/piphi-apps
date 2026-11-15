# PiPhi Modbus and Home Assistant Modbus: capability and quality audit

**Research cutoff:** 2026-11-15

**PiPhi source audited:** parent `0.9.0`, RTU sidecar `0.7.0`, their tests, manifests, CI and release metadata in this repository

**Home Assistant source baseline:** `home-assistant/core` commit [`a0f0cf28fea4e1dfea7937305808a3b5414111fd`](https://github.com/home-assistant/core/tree/a0f0cf28fea4e1dfea7937305808a3b5414111fd/homeassistant/components/modbus) (2026-11-13) and official documentation available by the cutoff

**Method:** source and reachable production paths outrank README, manifest and capability-catalog claims. Tests count as evidence for the behavior they execute, not as proof of deployment, field compatibility or a quality tier.

## Executive conclusion

PiPhi has a credible **bounded semantic-profile Modbus implementation**, not Home Assistant parity and not a Home Assistant quality tier. Its honest supported slice is:

- FC01/02/03/04 reads and profile-bound FC05/06/15/16 writes;
- TCP, UDP and RTU-framed TCP; serial RTU and ASCII through the sidecar;
- a CA-validated, server-authenticated TLS wrapper around Modbus/TCP;
- units 1–247, the four standard data areas, common fixed-width numbers, fixed strings, enum/bitfield interpretation, scaling and four byte/word layouts;
- in-memory polling/state, contiguous **network** read batching, bounded serial request serialization, protocol confirmation and read-back; and
- PiPhi sensor/binary-sensor/switch/number/select models plus profile-composed light/fan/cover/climate-shaped models.

That is useful protocol breadth. It should not be described as “Home Assistant-quality protocol evidence achieved,” “transport parity matched,” or “complete.” The current releases are explicitly `draft`, `unverified` and `unrated` in both manifests.[P-MANIFEST][S-MANIFEST] Startup config recovery is a placeholder; network reconfiguration is not transactional; serial transport errors do not invoke the implemented reconnect method; serial reads are one point per transaction and do not enforce RTU inter-frame timing; diagnostics/state/entity reads are unauthenticated; the sidecar receives the entire `/dev/serial` tree; TLS lacks client-certificate authentication required by the Modbus Security description; and release containers resolve dependencies from ranges instead of the tested lock.[P-LIFECYCLE][P-STATE][S-STATE][S-TRANSPORT][P-APP][S-APP][P-DOCKER][S-DOCKER]

Home Assistant remains the broader user-facing baseline: its generic YAML integration supports TCP, UDP, RTU-over-TCP, serial RTU and serial ASCII, four data areas, seven entity platforms, broad decode/transform options, polling, writes, reload, and connection inventory.[HA-DOC][HA-SCHEMA][HA-HUB][HA-WS] Its generic raw write actions are deliberately broader and less profile-constrained than PiPhi's model.[HA-SERVICE] That breadth is not itself a quality rating: the examined Home Assistant Modbus manifest has no `quality_scale`, and the integration has no `quality_scale.yaml` at the pinned commit.[HA-MANIFEST][HA-CORE]

**Release judgment:** retain the profile-bound write design, but treat the current pair as a strong pre-release implementation. P0 recovery, privacy/authentication, serial timing/device isolation, atomic setup/reconfigure, and reproducible-release work remains before a defensible general release claim.

## What is being compared

The Modbus Application Protocol defines function-code behavior and the four logical data areas; device meaning, scaling, units and safe writable ranges come from device documentation rather than the base protocol.[MB-SPEC] The official serial guide is the current implementation reference for new serial implementations, while the older serial document is explicitly legacy-only.[MB-SOURCES]

Home Assistant's generic Modbus integration is a broad operator-configured adapter. PiPhi is instead a profile-driven bridge with a privileged serial helper. A fair comparison therefore separates:

1. **Protocol breadth** — transports, functions, data areas and codecs.
2. **Product quality** — setup, reconfigure, recovery, diagnostics, privacy, documentation, tests and release evidence.
3. **Safety policy** — what callers are intentionally unable to do.

## Evidence table

| Area | Home Assistant first-party baseline | PiPhi source evidence | Audit result |
|---|---|---|---|
| **Transports** | Generic YAML supports TCP, UDP, RTU-over-TCP, serial RTU and serial ASCII.[HA-DOC][HA-SCHEMA] A separate shared-connection API supports TCP, UDP, TLS and serial parameters for device integrations.[HA-CONNECTION] | Network client implements TCP, UDP, CRC-framed RTU-over-TCP and TLS; the sidecar implements serial RTU and ASCII.[P-TCP][S-TRANSPORT] | **Broad on paper, qualified claim needed.** PiPhi has six selectable paths, but TLS is not full Modbus Security (see below), and serial timing/recovery gaps remain. |
| **Functions and data areas** | Generic entities use FC01/02/03/04 reads and FC05/06/15/16 writes through pymodbus; all four areas are configurable.[HA-HUB][HA-CONST][HA-DOC] | `FUNCTION_BY_AREA` implements FC01–04; point writes choose FC05, FC06 or FC16 and coil groups use FC15.[P-TCP][S-TRANSPORT] | **Useful core slice matched.** No mask write, read/write multiple registers, file records, device identification, diagnostics or vendor functions. This exclusion is acceptable if stated, not hidden under “generic parity.” |
| **Protocol limits** | The upstream client API documents up to 2,000 contiguous bits and approximately 125 registers for standard reads, and requires applications to serialize client calls.[PYMODBUS] | Network planner caps bits at 2,000 and registers at 125 and serial/network paths serialize requests.[P-TCP][S-TRANSPORT] | **Mostly sound.** FC16 schema uses 123 registers and FC15 uses 1,968 coils, consistent with bounded request design. Serial reads do not batch adjacent points. |
| **TLS / security protocol** | The shared HA connection library models TLS for device-specific integrations; generic YAML does not expose TLS.[HA-CONNECTION][HA-DOC] | PiPhi uses Python TLS, a configured CA, hostname verification and port 802, but supplies no client certificate and sends its normal MBAP framing.[P-TCP] | **Call this “server-authenticated TLS-wrapped Modbus/TCP,” not certified Modbus Security.** The Modbus Organization describes Modbus Security as TLS with X.509 authentication of both server and client on port 802.[MB-SOURCES] |
| **Addresses and profiles** | YAML lets the operator declare hub, unit, address, type and transforms per entity.[HA-DOC][HA-SCHEMA] | Pydantic models bind profile ID/version/provenance, unit, area, address, width, codec and writability; duplicate IDs, overlap and writes to read-only areas are rejected.[P-SCHEMA][S-SCHEMA] | **Good structural boundary, not a trust system.** Provenance is free text, profiles are inline user input, and hashes detect identity/change but there is no signature, trusted issuer or catalog verification. |
| **Decoding** | Supports signed/unsigned 16/32/64-bit values, float16/32/64, strings, custom `struct`, swaps, scaling, offset, precision and value policies.[HA-DOC][HA-SCHEMA][HA-ENTITY] | Supports corresponding fixed numeric types, strings, four ordering policies, enums, read-only bitfields, scale/offset, invalid vectors, bounds and precision.[P-SCHEMA][P-CODEC][S-SCHEMA] | **Strong safe subset.** Excluding executable/custom structures is reasonable. “Parity” is still too broad because HA exposes more per-platform transforms, device/state classes and semantic mappings. |
| **Entities** | Seven actual Home Assistant platforms: binary sensor, climate, cover, fan, light, sensor and switch.[HA-CONST][HA-DOC] | PiPhi emits its own point models and generic profile-composed models, including switch/number/select-like points and light/fan/cover/climate composites.[P-MODEL][P-COMPOSITE] | **Not one-for-one platform parity.** The models do not establish HA entity lifecycle behavior, device classes, state classes, translations or complete platform semantics. |
| **Polling and batching** | Default entity interval is 15 s, zero disables polling, requests serialize behind a hub lock, and `virtual_count` combines contiguous values.[HA-DOC][HA-HUB][HA-ENTITY] | Parent schedules groups with priority, jitter and backoff. Network reads coalesce only exactly contiguous points. Sidecar refresh loops over each point.[P-STATE][P-TCP][S-STATE] | **Good network primitive; incomplete system behavior.** No global/profile rate budget, no scheduler fairness proof, no serial block planner, and due groups run sequentially across every config, so one slow bus can delay unrelated buses. |
| **Writes** | Generic services accept caller-selected hub, unit, address and value; entity platforms also write configured targets and some verify state.[HA-SERVICE][HA-ENTITY] | PiPhi accepts point/command IDs, re-resolves immutable profile bindings, disallows unit 0 by schema, checks responses and reads back.[P-STATE][P-TCP][S-API][S-STATE] | **PiPhi safety advantage.** Keep named writes, no raw PDU, no broadcast and no caller address/function override. Note that profile authors remain trusted to mark the correct register writable. |
| **Initial setup** | Generic YAML validates configuration and starts a reconnect task; current HA guidance directs ordinary users to device-specific UI integrations where available.[HA-SCHEMA][HA-HUB][HA-DOC] | Parent network setup performs an immediate snapshot, but serial setup catches sidecar configuration/read failures, stores unavailable state, and still returns an apply response.[P-STATE][P-CONFIG] | **Gap.** Setup does not consistently fail or return an actionable typed error when the device/unit is unreachable. There is no assisted profile selection or safe connection test before acceptance. |
| **Reconfigure and removal** | YAML reload closes hubs, resets platforms and applies new YAML; shared config-entry connections are reference-counted and release on unload.[HA-SERVICE][HA-CONNECTION] | Parent closes/removes the old network client before trying replacement. Sidecar preserves an old session only when opening the candidate port fails, but accepts a candidate when the port opens even if every unit read fails.[P-STATE][S-STATE] | **Gap.** Make apply transactional end-to-end: validate, connect, prove the intended unit/profile, swap, then retire old resources. Removal does close clients/controllers. |
| **Restart and recovery** | HA retries initial connection every 60 seconds, uses three pymodbus request retries, closes on stop, marks failed entity reads unavailable and suppresses repeated identical hub errors.[HA-HUB][HA-ENTITY] | Network reads reconnect/retry once. Parent can reapply sidecar config after HTTP-level sidecar failure. `BusController.reconnect()` exists but has no production caller; point I/O errors only mark unavailable.[P-TCP][P-STATE][S-STATE] | **P0 gap.** Serial hot-unplug/replug or descriptor failure is not automatically reopened. “Bounded reconnect” and “hot-unplug recovery” are not supported claims. |
| **RTU/ASCII framing and timing** | HA delegates serial framing and retries to pinned upstream libraries.[HA-MANIFEST][HA-HUB] | Sidecar validates CRC/LRC, unit, function, exception and response byte counts and uses exclusive pyserial open.[S-TRANSPORT] | **Framing is credible; timing is incomplete.** There is no explicit RTU 3.5-character silent interval or local-echo/RS-485 direction handling, and parent delay is not a transport-wide invariant. The current Modbus serial guide is the authoritative requirement source.[MB-SERIAL] |
| **Diagnostics and privacy** | HA provides an admin-only WebSocket connection inventory and explains that serial “open” does not prove a unit responds.[HA-WS][HA-DOC] | PiPhi reports profile IDs/hashes, quality, latency, errors, unit health and queue metrics, and redacts selected key names/events.[P-HEALTH][P-STATE][S-STATE][S-TRANSPORT] | **Useful metrics, unsafe exposure boundary.** Parent and sidecar `/diagnostics`, `/state`, `/entities`, `/events` and related reads are not protected by the command/config authentication middleware. Example event POST routes are also unprotected. Entity values and operational metadata may therefore be disclosed to any reachable caller.[P-APP][P-RUNTIME][P-EVENTS][S-APP][S-RUNTIME][S-EVENTS] |
| **Serial privilege boundary** | HA commonly accesses serial in its own runtime; official docs cover USB adapters, proxies and serial servers.[HA-DOC] | Sidecar runs as UID 10001 and has no host-published port in its manifest, but maps host `/dev/serial` as `rwm`; config accepts any string path visible in that mapping.[S-DOCKER][S-MANIFEST][S-SCHEMA] | **Isolation is directionally good, least privilege is not achieved.** The claim “explicitly configured device mapping only” conflicts with the manifest's whole-tree mapping. |
| **Configuration persistence** | HA stores YAML/config entries and reconstructs integration state at restart.[HA-DOC][HA-CONNECTION] | Parent startup callback is explicitly a no-op placeholder; registries and active clients are process memory.[P-LIFECYCLE][P-STATE] | **P0 gap unless Core has an independently proven replay guarantee.** This package alone cannot restore existing configs after restart. |
| **Tests** | HA has first-party schema, service, platform, connection lifecycle and WebSocket tests at the pinned commit.[HA-TESTS] | PiPhi has 54 parent and 35 sidecar test-function definitions before parametrization, including protocol simulators, PTYs, malformed frames, auth, E2E parent↔sidecar and transactional sidecar reconfigure.[P-TESTS][S-TESTS] | **Strong pre-release evidence, not a tier.** There is no coverage measurement/gate, strict type check, serial timing test, true hot-unplug reopen test, authenticated-read test or production deployment test. A local rerun for this audit was blocked before collection by a missing `piphi_runtime_testkit_python` pytest plugin in the active environment; CI configuration, not a fresh green run, is the evidence recorded here. |
| **CI and release** | HA pins runtime requirements in its manifest and validates core through project CI.[HA-MANIFEST][HA-CORE] | Monorepo CI runs lock check, audit, pytest, validation and container build; release builds multi-arch images with SBOM and provenance attestation.[P-APP-META][S-APP-META][CI][RELEASE-CI] | **Good pipeline design with a reproducibility break.** Dockerfiles copy only `pyproject.toml` and run `pip install .`, so image dependencies are resolved from ranges rather than the `pdm.lock` that CI tests/audits. Both marketplace records remain draft/unverified/unrated.[P-DOCKER][S-DOCKER][P-MANIFEST][S-MANIFEST] |
| **Documentation** | Official HA docs include setup paths, terminology, complete YAML reference, security warning, connection inventory and issue guidance.[HA-DOC] | PiPhi READMEs summarize architecture and features; generated contract/release docs mostly list routes and generic release steps.[P-README][S-README][P-CONTRACT][S-CONTRACT] | **Gap.** Missing operator-grade field reference, profile authoring guide, removal/reconfigure steps, privacy disclosure, troubleshooting, known limitations, recovery behavior and a tested-device/profile support matrix. |

## Honest supported slice

### Supported now by reachable source paths

| Dimension | Supported slice |
|---|---|
| Network | Private/link-local/loopback IP literals or syntactically `.local`/`.lan` hostnames; TCP, MBAP-over-UDP, CRC-framed RTU-over-TCP, and server-authenticated TLS-wrapped Modbus/TCP. |
| Serial | Linux serial RTU or ASCII through pyserial, 1,200–921,600 baud, 7/8 data bits, N/E/O parity, 1/2 stop bits, one in-flight operation per configured session. |
| Reads | FC01 coils, FC02 discrete inputs, FC03 holding registers, FC04 input registers; units 1–247; network contiguous batching only. |
| Writes | FC05 single coil, FC06 single holding register, FC15 contiguous multiple coils, FC16 multiple holding registers; profile-bound, response-confirmed and read back. |
| Values | Bool; signed/unsigned 16/32/64; float16/32/64; bounded fixed ASCII/UTF-8 strings; enums; read-only bit masks; scale, offset, bounds, precision, invalid raw vectors and ABCD/BADC/CDAB/DCBA policies. |
| State | Last-good value retention with stale/unavailable quality, per-unit counters, polling groups and in-memory events/diagnostics. |

### Not supported or not proven

- Full Modbus Security conformance or mutual X.509 authentication.[MB-SOURCES]
- Unit 0/broadcast, arbitrary addresses, raw frames/PDUs, custom/vendor functions, FC08 diagnostics, FC20/21 file records, FC22 mask write, FC23 read/write multiple registers or FC43 device identification.[MB-SPEC]
- Signed/trusted profile distribution, arbitrary profile authenticity or vendor certification.
- Serial adjacent-read batching, RTU silent-interval enforcement, automatic serial descriptor reopen/hotplug recovery, cross-config bus sharing or fairness.
- Durable config/state restoration by these packages, transactional parent network reconfigure, discovery, repairs or assisted profile upgrade.
- Home Assistant entities, config entries, translations or an HA IQS tier; PiPhi entities are a different runtime contract.
- A field-validated compatibility promise beyond the small attributed fixture corpus and simulated/PTTY paths.

## Home Assistant Integration Quality Scale assessment

The current IQS has 54 rules: 20 Bronze, 10 Silver, 21 Gold and 3 Platinum. A tier requires every rule in that tier and all lower tiers; claims are recorded in `quality_scale.yaml`, checked by hassfest and approved by Home Assistant reviewers.[HA-IQS][HA-IQS-RULES] PiPhi is not a Home Assistant core integration, so it **cannot literally earn an HA tier**. The table below is an analogous gap assessment, not a badge.

| IQS level | Analogous PiPhi evidence | Assessment |
|---|---|---|
| **Bronze** | UI schema endpoint, stable point IDs, appropriate default polling, action registration at module startup, substantial tests and basic docs.[P-DISCOVERY][P-STATE][P-SCHEMA][P-README] | **Does not meet Bronze equivalence.** No tested UI config flow that proves connectivity before acceptance, no duplicate endpoint/device prevention, inconsistent setup failure, incomplete install/removal docs, no brand evidence, and no rule ledger. Several HA-specific rules are structurally inapplicable. |
| **Silver** | Deconfigure closes resources; failed values become unavailable/stale; maintainer metadata exists.[P-STATE][S-STATE][P-MANIFEST] | **Does not meet Silver equivalence.** No measured >95% per-module coverage, no production serial reconnect, repeated poll warnings are not transition-suppressed, no credential reauth/rotation user flow, and reconfigure is not consistently transactional. |
| **Gold** | Rich internal metrics and event transitions; some profile-composed devices.[P-STATE][S-STATE] | **Does not meet Gold equivalence.** No discovery, repairs, translations, device/state classes, stale-device UX, protected downloadable diagnostics, complete supported-device/function docs or robust reconfiguration flow. |
| **Platinum** | Network path is async; blocking serial I/O is moved to threads.[P-TCP][S-TRANSPORT] | **Does not meet Platinum equivalence.** No strict mypy gate; no shared injected HTTP session (a new `httpx.AsyncClient` is created for every sidecar call); and the serial implementation is a custom synchronous transport rather than a strictly typed async dependency.[P-SIDECAR] |

Home Assistant's generic Modbus component itself is **ungraded at the pinned commit**, so “equal to HA Modbus” must not be translated into any IQS tier.[HA-MANIFEST][HA-CORE]

## Safety invariants to preserve and strengthen

1. **No invocation-time transport override.** Callers select a stable point or named action; they never provide function, unit, address, raw PDU or frame.
2. **No broadcast writes.** Keep profile unit IDs at 1–247. The official HA terminology also identifies unit 0 as broadcast on serial/gateway connections.[HA-DOC]
3. **Writes are explicitly profile-authorized.** Read-only areas and points stay non-writable; values remain typed, finite, bounded and precision-checked.
4. **No blind write retry.** Preserve single-attempt writes, response validation and read-back. A timeout leaves outcome unknown and must be surfaced, not automatically repeated.
5. **Pulse reset is safety-critical.** Do not run pulse sleep/reset in an HTTP request coroutine without durable recovery. Persist an outstanding reset intent or move bounded pulse execution to a crash-safe controller before marketing pulses as safe.
6. **One in-flight request per physical link.** Preserve serialization, but key it by actual endpoint/bus across configs, not merely by config object. Upstream pymodbus explicitly requires application-level serialization.[PYMODBUS]
7. **Fail closed on identity and trust.** Production command/config APIs already require runtime/sidecar identity; extend authorization to every other mutating route and to state, entities, events and diagnostics. Profile hash is not profile trust.
8. **Validate the resolved destination.** Re-resolve and reject any public/non-local address at connect time, including every DNS result, rather than trusting only an IP literal or `.local`/`.lan` suffix.
9. **Least serial-device privilege.** Map only the selected stable device path, reject paths outside the allowed mount, and document udev/hotplug behavior.
10. **Never equate process, socket/port and unit health.** Keep `service_available`, `port_open` and responsive-unit state separate; do not accept a reconfiguration merely because the port opens.
11. **No raw frames or secrets in diagnostics.** Preserve sanitization and add explicit privacy tests over every externally reachable read route.
12. **Atomic config replacement.** A new config becomes active only after schema validation, endpoint ownership checks and a successful identity/read probe; otherwise the previous working config remains intact.

## Prioritized concrete next work

### P0 — release blockers

1. **Make restart and reconfigure real.** Implement startup config replay; stage parent clients/controllers before registry swap; prove the intended unit/profile responds; preserve the old config on all failure paths; add process-restart and sidecar-restart tests.
2. **Repair serial recovery and timing.** Invoke bounded close/reopen after descriptor/transport failure; handle unplug/replug; enforce the serial guide's RTU frame separation across reads and writes; add PTY tests for truncated frames, delayed bytes, stale input, local echo and reopen after descriptor replacement.[MB-SERIAL]
3. **Close API authorization and privacy gaps.** Apply runtime identity to `/state`, `/entities`, `/events`, `/diagnostics`, `/contract` where appropriate, all sidecar operational reads, and unprotected event/telemetry mutation routes. Define the small set of intentionally public liveness endpoints. Add route-enumeration tests proving unauthorized callers cannot mutate state or infer values, profile IDs, unit health or paths.
4. **Enforce least-privilege serial mapping.** Replace `/dev/serial` tree mapping with explicit stable device mapping/capability support. Validate canonical paths and ensure one physical bus cannot be configured twice under different IDs.
5. **Make releases reproducible.** Build images from the locked, audited dependency set (or generated hash-pinned requirements), then test that exact image. Keep SBOM/provenance attestation, publish immutable digest evidence, and change draft/unverified metadata only after qualification.
6. **Correct public claims immediately.** Rename TLS capability as server-authenticated TLS-wrapped Modbus/TCP unless mutual X.509 and Modbus Security conformance are implemented; remove hotplug, bounded reconnect, explicit-device-only and complete/parity claims from catalogs/docs until tests and production paths support them.
7. **Make pulse reset crash-safe or remove it.** A process cancellation/restart between set and reset can leave coils asserted. Use a durable deadline/reset journal reconciled at startup, or exclude pulse commands from the release.

### P1 — quality baseline

8. **Add measurable gates.** Enforce per-module coverage above 95% if targeting Silver equivalence, strict type checking, linting and protocol parser/property tests. Ensure a clean checkout can execute tests without ambient pytest plugins.[HA-IQS-RULES]
9. **Bound the whole scheduler.** Add per-bus/profile request-rate and queue budgets, fair scheduling across configs, queue wait deadlines/cancellation, and serial contiguous block planning that never crosses undeclared holes.
10. **Harden local-network policy.** Validate resolved IPs at every connection/reconnection, address DNS rebinding, make allowed subnets explicit, and test IPv4/IPv6/link-local/mDNS behavior.
11. **Finish operator documentation.** Add setup/reconfigure/removal procedures, every field and default, profile authoring/versioning, privacy/data exposure, known limits, security architecture, troubleshooting, supported functions/transports and recovery semantics.
12. **Turn diagnostics into a product surface.** Provide authenticated, downloadable, consistently redacted diagnostics with endpoint/port pseudonyms, config/release provenance, last-success age and actionable error taxonomy; avoid repeated identical logs.

### P2 — demand-driven breadth

13. Add device/state classes, richer semantic mappings and translations based on reviewed profiles rather than generic claims.
14. Expand the attributed fixture corpus and publish a tested profile/device/adapter matrix; distinguish simulator, vendor-document fixture and real-hardware evidence.
15. Add non-destructive uncommon function codes only for a concrete device/profile need. Keep raw PDU, broadcast and destructive diagnostics out of the normal product.
16. Consider mutual TLS/Modbus Security only with a complete certificate lifecycle, client identity, rotation and conformance plan.[MB-SOURCES]

## Primary sources

### Protocol and upstream

- **[MB-SOURCES]** Modbus Organization, [Specifications and Implementation Guides](https://www.modbus.org/modbus-specifications) — first-party links to Application Protocol V1.1b3, Serial Line V1.02, TCP/IP messaging and Modbus Security; describes TLS, X.509 server/client authentication and port 802.
- **[MB-SPEC]** Modbus Organization, [Modbus Application Protocol V1.1b3](https://www.modbus.org/file/secure/modbusprotocolspecification.pdf).
- **[MB-SERIAL]** Modbus Organization, [Modbus Serial Line Protocol and Implementation Guide V1.02](https://www.modbus.org/file/secure/modbusoverserial.pdf).
- **[PYMODBUS]** pymodbus project, [official client documentation](https://pymodbus.readthedocs.io/en/latest/source/client.html) — transports/framers, serialization requirement, reconnect/retry behavior, addressing, function APIs and quantity bounds.

### Home Assistant first-party

- **[HA-DOC]** Home Assistant, [Modbus integration documentation](https://www.home-assistant.io/integrations/modbus/).
- **[HA-CORE]** Home Assistant Core, [Modbus component at `a0f0cf28`](https://github.com/home-assistant/core/tree/a0f0cf28fea4e1dfea7937305808a3b5414111fd/homeassistant/components/modbus).
- **[HA-MANIFEST]** Home Assistant Core, [`manifest.json`](https://github.com/home-assistant/core/blob/a0f0cf28fea4e1dfea7937305808a3b5414111fd/homeassistant/components/modbus/manifest.json).
- **[HA-CONST]** Home Assistant Core, [`const.py`](https://github.com/home-assistant/core/blob/a0f0cf28fea4e1dfea7937305808a3b5414111fd/homeassistant/components/modbus/const.py).
- **[HA-SCHEMA]** Home Assistant Core, [`schemas.py`](https://github.com/home-assistant/core/blob/a0f0cf28fea4e1dfea7937305808a3b5414111fd/homeassistant/components/modbus/schemas.py).
- **[HA-HUB]** Home Assistant Core, [`modbus.py`](https://github.com/home-assistant/core/blob/a0f0cf28fea4e1dfea7937305808a3b5414111fd/homeassistant/components/modbus/modbus.py).
- **[HA-CONNECTION]** Home Assistant Core, [`connection.py`](https://github.com/home-assistant/core/blob/a0f0cf28fea4e1dfea7937305808a3b5414111fd/homeassistant/components/modbus/connection.py).
- **[HA-ENTITY]** Home Assistant Core, [`entity.py`](https://github.com/home-assistant/core/blob/a0f0cf28fea4e1dfea7937305808a3b5414111fd/homeassistant/components/modbus/entity.py).
- **[HA-SERVICE]** Home Assistant Core, [`services.py`](https://github.com/home-assistant/core/blob/a0f0cf28fea4e1dfea7937305808a3b5414111fd/homeassistant/components/modbus/services.py).
- **[HA-WS]** Home Assistant Core, [`websocket_api.py`](https://github.com/home-assistant/core/blob/a0f0cf28fea4e1dfea7937305808a3b5414111fd/homeassistant/components/modbus/websocket_api.py).
- **[HA-TESTS]** Home Assistant Core, [Modbus tests](https://github.com/home-assistant/core/tree/a0f0cf28fea4e1dfea7937305808a3b5414111fd/tests/components/modbus).
- **[HA-IQS]** Home Assistant developer documentation, [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
- **[HA-IQS-RULES]** Home Assistant developer documentation, [all 54 IQS rules](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/).

### PiPhi repository evidence

Parent integration:

- **[P-README]** [README](../README.md)
- **[P-MANIFEST]** [manifest](../manifest.json)
- **[P-APP-META]** [CI/release package metadata](../piphi-app.json)
- **[P-DOCKER]** [Dockerfile](../Dockerfile)
- **[P-LIFECYCLE]** [lifecycle](../src/piphi_network_modbus/lifecycle.py)
- **[P-STATE]** [state, polling, setup and commands](../src/piphi_network_modbus/state.py)
- **[P-TCP]** [network transports](../src/piphi_network_modbus/modbus_tcp.py)
- **[P-SCHEMA]** [profile/config schemas](../src/piphi_network_modbus/schemas.py)
- **[P-CODEC]** [profile codec](../src/piphi_network_modbus/profile_codec.py)
- **[P-SIDECAR]** [sidecar HTTP client](../src/piphi_network_modbus/sidecar_client.py)
- **[P-MODEL]** [point entity model](../src/piphi_network_modbus/modbus_model.py)
- **[P-COMPOSITE]** [composite model](../src/piphi_network_modbus/composite_model.py)
- **[P-APP]** [application route assembly](../src/piphi_network_modbus/app.py)
- **[P-RUNTIME]** [state/contract routes](../src/piphi_network_modbus/routes/runtime.py)
- **[P-EVENTS]** [event routes](../src/piphi_network_modbus/routes/events.py)
- **[P-CONFIG]** [config routes](../src/piphi_network_modbus/routes/config.py)
- **[P-HEALTH]** [health/diagnostics routes](../src/piphi_network_modbus/routes/health.py)
- **[P-DISCOVERY]** [discovery/UI schema routes](../src/piphi_network_modbus/routes/discovery.py)
- **[P-CONTRACT]** [generated runtime contract](contract.md)
- **[P-TESTS]** [tests](../tests/)

RTU sidecar:

- **[S-README]** [README](../../../services/piphi-modbus-rtu-sidecar/README.md)
- **[S-MANIFEST]** [manifest](../../../services/piphi-modbus-rtu-sidecar/manifest.json)
- **[S-APP-META]** [CI/release package metadata](../../../services/piphi-modbus-rtu-sidecar/piphi-app.json)
- **[S-DOCKER]** [Dockerfile](../../../services/piphi-modbus-rtu-sidecar/Dockerfile)
- **[S-STATE]** [controller, setup and recovery state](../../../services/piphi-modbus-rtu-sidecar/src/piphi_modbus_rtu_sidecar/state.py)
- **[S-TRANSPORT]** [serial transport, queue and sanitization](../../../services/piphi-modbus-rtu-sidecar/src/piphi_modbus_rtu_sidecar/transport.py)
- **[S-SCHEMA]** [sidecar schemas](../../../services/piphi-modbus-rtu-sidecar/src/piphi_modbus_rtu_sidecar/schemas.py)
- **[S-API]** [parent-sidecar API](../../../services/piphi-modbus-rtu-sidecar/src/piphi_modbus_rtu_sidecar/routes/sidecar_api.py)
- **[S-APP]** [sidecar authentication middleware](../../../services/piphi-modbus-rtu-sidecar/src/piphi_modbus_rtu_sidecar/app.py)
- **[S-RUNTIME]** [sidecar state/contract routes](../../../services/piphi-modbus-rtu-sidecar/src/piphi_modbus_rtu_sidecar/routes/runtime.py)
- **[S-EVENTS]** [sidecar event routes](../../../services/piphi-modbus-rtu-sidecar/src/piphi_modbus_rtu_sidecar/routes/events.py)
- **[S-CONTRACT]** [generated runtime contract](../../../services/piphi-modbus-rtu-sidecar/docs/contract.md)
- **[S-TESTS]** [tests](../../../services/piphi-modbus-rtu-sidecar/tests/)

Repository CI/release:

- **[CI]** [app CI](../../../../.github/workflows/apps-ci.yml) and [reusable app CI](../../../../.github/workflows/reusable-app-ci.yml)
- **[RELEASE-CI]** [release workflow](../../../../.github/workflows/release-app.yml)
