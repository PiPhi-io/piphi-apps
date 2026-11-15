# PiPhi Modbus and Home Assistant Modbus: capability and quality audit

**Research cutoff:** 2026-11-15

**PiPhi source audited:** parent `0.10.0`, RTU sidecar `0.8.0`, their tests, manifests, CI and release metadata in this repository

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

That is useful protocol breadth. It should still not be described as literal Home Assistant parity or as an HA quality tier. The `0.10.0`/`0.8.0` candidates close the audit's highest-risk implementation gaps: startup config replay uses the Runtime SDK snapshot/Core flow; network and serial replacements are probed before swap; serial descriptor failures reopen once; RTU frame separation is enforced; every operational route except liveness is authenticated; pulse resets have a durable recovery journal; DNS results are revalidated as local; serial access is narrowed to stable `/dev/serial/by-id` paths with duplicate physical-bus rejection; and images install hash-locked dependencies on a digest-pinned base.[P-LIFECYCLE][P-STATE][P-TCP][S-STATE][S-TRANSPORT][P-APP][S-APP][P-DOCKER][S-DOCKER] TLS remains server-authenticated rather than mutual-certificate Modbus Security, serial reads remain one point per transaction, and serial behavior is validated with simulators and PTYs rather than a physical adapter; hardware compatibility is therefore not guaranteed.[P-MANIFEST][S-MANIFEST][MB-SOURCES]

Home Assistant remains the broader user-facing baseline: its generic YAML integration supports TCP, UDP, RTU-over-TCP, serial RTU and serial ASCII, four data areas, seven entity platforms, broad decode/transform options, polling, writes, reload, and connection inventory.[HA-DOC][HA-SCHEMA][HA-HUB][HA-WS] Its generic raw write actions are deliberately broader and less profile-constrained than PiPhi's model.[HA-SERVICE] That breadth is not itself a quality rating: the examined Home Assistant Modbus manifest has no `quality_scale`, and the integration has no `quality_scale.yaml` at the pinned commit.[HA-MANIFEST][HA-CORE]

**Release judgment:** approved for publication. The known software P0 blockers are closed in the `0.10.0`/`0.8.0` candidates. Physical-adapter qualification is not a release gate; publish with the explicit limitation that serial coverage is simulator/PTTY-based and hardware compatibility is not guaranteed. Marketplace cutover still requires verification of the exact published image and release evidence.

## What is being compared

The Modbus Application Protocol defines function-code behavior and the four logical data areas; device meaning, scaling, units and safe writable ranges come from device documentation rather than the base protocol.[MB-SPEC] The official serial guide is the current implementation reference for new serial implementations, while the older serial document is explicitly legacy-only.[MB-SOURCES]

Home Assistant's generic Modbus integration is a broad operator-configured adapter. PiPhi is instead a profile-driven bridge with a privileged serial helper. A fair comparison therefore separates:

1. **Protocol breadth** — transports, functions, data areas and codecs.
2. **Product quality** — setup, reconfigure, recovery, diagnostics, privacy, documentation, tests and release evidence.
3. **Safety policy** — what callers are intentionally unable to do.

## Evidence table

| Area | Home Assistant first-party baseline | PiPhi source evidence | Audit result |
|---|---|---|---|
| **Transports** | Generic YAML supports TCP, UDP, RTU-over-TCP, serial RTU and serial ASCII.[HA-DOC][HA-SCHEMA] A separate shared-connection API supports TCP, UDP, TLS and serial parameters for device integrations.[HA-CONNECTION] | Network client implements TCP, UDP, CRC-framed RTU-over-TCP and server-authenticated TLS; the sidecar implements serial RTU and ASCII with bounded reopen and RTU frame separation.[P-TCP][S-TRANSPORT] | **Broad bounded slice.** PiPhi has six selectable paths. TLS is not full Modbus Security (see below). Serial behavior is simulator/PTTY-tested; hardware compatibility is not guaranteed. |
| **Functions and data areas** | Generic entities use FC01/02/03/04 reads and FC05/06/15/16 writes through pymodbus; all four areas are configurable.[HA-HUB][HA-CONST][HA-DOC] | `FUNCTION_BY_AREA` implements FC01–04; point writes choose FC05, FC06 or FC16 and coil groups use FC15.[P-TCP][S-TRANSPORT] | **Useful core slice matched.** No mask write, read/write multiple registers, file records, device identification, diagnostics or vendor functions. This exclusion is acceptable if stated, not hidden under “generic parity.” |
| **Protocol limits** | The upstream client API documents up to 2,000 contiguous bits and approximately 125 registers for standard reads, and requires applications to serialize client calls.[PYMODBUS] | Network planner caps bits at 2,000 and registers at 125 and serial/network paths serialize requests.[P-TCP][S-TRANSPORT] | **Mostly sound.** FC16 schema uses 123 registers and FC15 uses 1,968 coils, consistent with bounded request design. Serial reads do not batch adjacent points. |
| **TLS / security protocol** | The shared HA connection library models TLS for device-specific integrations; generic YAML does not expose TLS.[HA-CONNECTION][HA-DOC] | PiPhi uses Python TLS, a configured CA, hostname verification and port 802, but supplies no client certificate and sends its normal MBAP framing.[P-TCP] | **Call this “server-authenticated TLS-wrapped Modbus/TCP,” not certified Modbus Security.** The Modbus Organization describes Modbus Security as TLS with X.509 authentication of both server and client on port 802.[MB-SOURCES] |
| **Addresses and profiles** | YAML lets the operator declare hub, unit, address, type and transforms per entity.[HA-DOC][HA-SCHEMA] | Pydantic models bind profile ID/version/provenance, unit, area, address, width, codec and writability; duplicate IDs, overlap and writes to read-only areas are rejected.[P-SCHEMA][S-SCHEMA] | **Good structural boundary, not a trust system.** Provenance is free text, profiles are inline user input, and hashes detect identity/change but there is no signature, trusted issuer or catalog verification. |
| **Decoding** | Supports signed/unsigned 16/32/64-bit values, float16/32/64, strings, custom `struct`, swaps, scaling, offset, precision and value policies.[HA-DOC][HA-SCHEMA][HA-ENTITY] | Supports corresponding fixed numeric types, strings, four ordering policies, enums, read-only bitfields, scale/offset, invalid vectors, bounds and precision.[P-SCHEMA][P-CODEC][S-SCHEMA] | **Strong safe subset.** Excluding executable/custom structures is reasonable. “Parity” is still too broad because HA exposes more per-platform transforms, device/state classes and semantic mappings. |
| **Entities** | Seven actual Home Assistant platforms: binary sensor, climate, cover, fan, light, sensor and switch.[HA-CONST][HA-DOC] | PiPhi emits its own point models and generic profile-composed models, including switch/number/select-like points and light/fan/cover/climate composites.[P-MODEL][P-COMPOSITE] | **Not one-for-one platform parity.** The models do not establish HA entity lifecycle behavior, device classes, state classes, translations or complete platform semantics. |
| **Polling and batching** | Default entity interval is 15 s, zero disables polling, requests serialize behind a hub lock, and `virtual_count` combines contiguous values.[HA-DOC][HA-HUB][HA-ENTITY] | Parent schedules groups with priority, jitter and backoff. Network reads coalesce only exactly contiguous points. Sidecar refresh loops over each point.[P-STATE][P-TCP][S-STATE] | **Good network primitive; incomplete system behavior.** No global/profile rate budget, no scheduler fairness proof, no serial block planner, and due groups run sequentially across every config, so one slow bus can delay unrelated buses. |
| **Writes** | Generic services accept caller-selected hub, unit, address and value; entity platforms also write configured targets and some verify state.[HA-SERVICE][HA-ENTITY] | PiPhi accepts point/command IDs, re-resolves immutable profile bindings, disallows unit 0 by schema, checks responses and reads back.[P-STATE][P-TCP][S-API][S-STATE] | **PiPhi safety advantage.** Keep named writes, no raw PDU, no broadcast and no caller address/function override. Note that profile authors remain trusted to mark the correct register writable. |
| **Initial setup** | Generic YAML validates configuration and starts a reconnect task; current HA guidance directs ordinary users to device-specific UI integrations where available.[HA-SCHEMA][HA-HUB][HA-DOC] | Parent network setup performs an immediate snapshot, but serial setup catches sidecar configuration/read failures, stores unavailable state, and still returns an apply response.[P-STATE][P-CONFIG] | **Gap.** Setup does not consistently fail or return an actionable typed error when the device/unit is unreachable. There is no assisted profile selection or safe connection test before acceptance. |
| **Reconfigure and removal** | YAML reload closes hubs, resets platforms and applies new YAML; shared config-entry connections are reference-counted and release on unload.[HA-SERVICE][HA-CONNECTION] | Parent and sidecar stage candidates, require a successful profile/unit probe, swap only after success, and preserve the old working client/controller on failure.[P-STATE][S-STATE] | **Strong bounded behavior.** Removal closes clients/controllers; failed replacement is typed and non-destructive. |
| **Restart and recovery** | HA retries initial connection every 60 seconds, uses three pymodbus request retries, closes on stop, marks failed entity reads unavailable and suppresses repeated identical hub errors.[HA-HUB][HA-ENTITY] | Network reads reconnect/retry once; serial descriptor/transport failures close and reopen once before retrying reads, while writes are never replayed; parent startup rehydrates configs from the mounted snapshot and Core.[P-TCP][P-STATE][P-LIFECYCLE][S-STATE] | **Strong bounded recovery.** Automated PTY/unit coverage proves descriptor replacement behavior. No physical adapter was used, so hardware compatibility is not guaranteed. |
| **RTU/ASCII framing and timing** | HA delegates serial framing and retries to pinned upstream libraries.[HA-MANIFEST][HA-HUB] | Sidecar validates CRC/LRC, unit, function, exception and response byte counts, uses exclusive pyserial open, and enforces 3.5 character times (or 1.75 ms above 19,200 baud) between RTU frames.[S-TRANSPORT] | **Core framing/timing is implemented.** Local echo and custom RS-485 direction control remain adapter-specific exclusions requiring concrete hardware demand.[MB-SERIAL] |
| **Diagnostics and privacy** | HA provides an admin-only WebSocket connection inventory and explains that serial “open” does not prove a unit responds.[HA-WS][HA-DOC] | PiPhi reports profile IDs/hashes, quality, latency, errors, unit health and queue metrics, redacts selected key names/events, and requires runtime/sidecar identity for every operational route; only `/health` is public.[P-HEALTH][P-STATE][S-STATE][S-TRANSPORT][P-APP][S-APP] | **Protected useful metrics.** Route-enumeration tests prove unauthenticated callers cannot read values/metadata or invoke example mutation routes. |
| **Serial privilege boundary** | HA commonly accesses serial in its own runtime; official docs cover USB adapters, proxies and serial servers.[HA-DOC] | Sidecar runs as UID 10001, has no host-published port, maps only `/dev/serial/by-id`, rejects other production paths, and prevents two configs from claiming the same resolved physical device.[S-DOCKER][S-MANIFEST][S-STATE] | **Substantially narrowed.** Per-device container mapping would be still tighter, but requires platform support for config-time device grants. |
| **Configuration persistence** | HA stores YAML/config entries and reconstructs integration state at restart.[HA-DOC][HA-CONNECTION] | Parent startup uses the Runtime SDK to load Core's mounted snapshot, then fetch and apply the latest authenticated Core configuration.[P-LIFECYCLE][P-STATE] | **Implemented.** Startup replay uses the same typed, probed apply path as live configuration. |
| **Tests** | HA has first-party schema, service, platform, connection lifecycle and WebSocket tests at the pinned commit.[HA-TESTS] | PiPhi includes protocol simulators, PTYs, malformed frames, auth route enumeration, E2E parent↔sidecar, transactional reconfigure, startup replay, RTU timing, serial reopen and durable pulse recovery.[P-TESTS][S-TESTS] | **Strong release evidence, not a tier.** Fresh locked-environment runs pass all 70 parent and 63 sidecar tests. Coverage measurement and strict typing remain future improvements; physical hardware testing is not a publication requirement. |
| **CI and release** | HA pins runtime requirements in its manifest and validates core through project CI.[HA-MANIFEST][HA-CORE] | Monorepo CI runs lock check, audit, pytest, validation and container build; Dockerfiles export hash-pinned production requirements from `pdm.lock` on a digest-pinned base; release builds multi-arch images with SBOM and provenance attestation.[P-APP-META][S-APP-META][P-DOCKER][S-DOCKER][CI][RELEASE-CI] | **Reproducible dependency input implemented.** Both marketplace records remain draft/unverified/unrated pending qualification.[P-MANIFEST][S-MANIFEST] |
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
- Serial adjacent-read batching, custom local-echo/RS-485 direction handling, cross-config bus sharing or scheduler fairness proof.
- Discovery, repairs, assisted profile upgrade or durable restoration of last-good point values (configuration itself is replayed).
- Home Assistant entities, config entries, translations or an HA IQS tier; PiPhi entities are a different runtime contract.
- A field-validated compatibility promise beyond the small attributed fixture corpus and simulated/PTTY paths.

## Home Assistant Integration Quality Scale assessment

The current IQS has 54 rules: 20 Bronze, 10 Silver, 21 Gold and 3 Platinum. A tier requires every rule in that tier and all lower tiers; claims are recorded in `quality_scale.yaml`, checked by hassfest and approved by Home Assistant reviewers.[HA-IQS][HA-IQS-RULES] PiPhi is not a Home Assistant core integration, so it **cannot literally earn an HA tier**. The table below is an analogous gap assessment, not a badge.

| IQS level | Analogous PiPhi evidence | Assessment |
|---|---|---|
| **Bronze** | UI schema endpoint, stable point IDs, connectivity-probed atomic setup, duplicate physical serial-bus prevention, appropriate default polling, action registration at module startup, substantial tests and basic docs.[P-DISCOVERY][P-STATE][P-SCHEMA][P-README] | **Does not meet literal Bronze.** PiPhi is not an HA config-entry integration and has no HA brand/rule ledger; install/removal documentation also remains incomplete. Several HA-specific rules are structurally inapplicable. |
| **Silver** | Deconfigure closes resources; failed values become unavailable/stale; serial transport failures reopen; reconfigure is transactional; maintainer metadata exists.[P-STATE][S-STATE][P-MANIFEST] | **Does not meet Silver equivalence.** No measured >95% per-module coverage, repeated poll warnings are not transition-suppressed, and there is no credential reauth/rotation user flow. |
| **Gold** | Rich protected metrics, event transitions, local-target DNS enforcement and profile-composed devices.[P-STATE][P-TCP][S-STATE] | **Does not meet Gold equivalence.** No discovery, repairs, translations, device/state classes, stale-device UX, downloadable diagnostics or complete supported-device documentation. |
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

### P0 — implemented in the `0.10.0` / `0.8.0` candidates

The original blocker list is retained below as an acceptance record. Local echo, custom RS-485 direction control and per-device container grants are explicit unsupported or platform-dependent limitations, not publication gates or claims made by the generic runtime.

1. **Restart and transactional reconfigure — implemented.** Startup rehydrates through the Runtime SDK; candidate clients/controllers prove profile response before swap; failed replacement preserves the previous working resources.
2. **Serial recovery and timing — implemented for the generic contract.** Descriptor/transport failures close and reopen once, writes are not replayed, and RTU separation is enforced and tested.[MB-SERIAL]
3. **API authorization and privacy — implemented.** Runtime/sidecar identity protects every operational read and mutation; only `/health` is public, with route-enumeration tests.
4. **Serial isolation — implemented to the current platform boundary.** The mount is narrowed to stable `/dev/serial/by-id`, production rejects other paths, and canonical duplicate physical buses are rejected. Per-device grants remain a platform enhancement.
5. **Reproducible image inputs — implemented.** Digest-pinned base images install hash-locked production dependencies exported from the audited lockfiles. SBOM/provenance publication remains in release CI.
6. **Public claims — corrected.** TLS is named server-authenticated TLS-wrapped Modbus/TCP; the catalogs avoid literal HA parity/complete and explicit-single-device claims.
7. **Pulse reset recovery — implemented.** Reset intents are persisted before assertion, deleted only after confirmed reset, and reconciled through the probed config path after restart.

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
