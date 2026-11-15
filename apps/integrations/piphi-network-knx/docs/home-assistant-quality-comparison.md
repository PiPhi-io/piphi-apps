# PiPhi KNX and Home Assistant KNX: capability and quality audit

> **Historical baseline:** This audit describes version 0.1.0 before remediation. Version 0.2.1 implements the deliberately bounded first protocol slice: pinned xknx transport, automatic/UDP/TCP tunnelling, active discovery, reviewed DPT 1.001/5.001/9.001 mappings, initialization reads, typed allowlisted writes, feedback-driven state, truthful availability, bounded traffic, durable lifecycle, fail-closed auth, privacy-bounded diagnostics, full CI, and a locked non-root container. ETS project import, KNX Secure, routing, broader DPT/entity coverage, and physical gateway qualification remain explicitly unavailable or unverified rather than overclaimed.

**Research cutoff:** 2026-11-15

**PiPhi source audited:** `piphi-network-knx` 0.1.0 source, tests, manifest, capability catalog, container, CI and release metadata in this repository

**Home Assistant baseline:** Core cutoff snapshot [`4d27057851a312994f68c3064365c8b34f805183`](https://github.com/home-assistant/core/tree/4d27057851a312994f68c3064365c8b34f805183), whose last KNX-component change was [`296ac4d97c0b602077087a0b662b90fea290e955`](https://github.com/home-assistant/core/commit/296ac4d97c0b602077087a0b662b90fea290e955); exact `xknx==4.1.1` reference [`e3d8212777160af85ea2ecb4e5b9c01d7e600b03`](https://github.com/XKNX/xknx/tree/e3d8212777160af85ea2ecb4e5b9c01d7e600b03); `xknxproject==3.10.0` reference [`1334c4e48ef9ba59b78af24d5c4ba68fcd21d7f9`](https://github.com/XKNX/xknxproject/tree/1334c4e48ef9ba59b78af24d5c4ba68fcd21d7f9); and first-party KNX documentation last changed at [`fc4e4718316657cd0487a2c1b70954cb90d29d82`](https://github.com/home-assistant/home-assistant.io/blob/fc4e4718316657cd0487a2c1b70954cb90d29d82/source/_integrations/knx.markdown)

**Method:** reachable production paths outrank names, manifests and planned catalogs. Tests prove only what they execute. Home Assistant's Integration Quality Scale (IQS) is used only as an analogy for PiPhi because PiPhi is not a Home Assistant Core integration.

## Executive conclusion

`piphi-network-knx` is currently a **generic generated runtime scaffold with KNX-labelled plans, not a KNX implementation**. It has no `xknx` or other KNX protocol dependency, KNXnet/IP socket/session, gateway scanner, project/keyring parser, group-address model, datapoint codec, telegram parser, entity mapping, bus reader or bus writer.[P-PROJECT][P-STATE][P-CATALOG] Applying any syntactically valid host immediately records `connected: true`; `refresh` only appends a `runtime.command.received` event; discovery always returns a demo device; and entities are demo-shaped regardless of the installation.[P-STATE][P-COMMAND][P-DISCOVERY][P-ENTITY]

The honest KNX protocol slice is therefore **none**. The supported product slice is limited to an in-memory PiPhi runtime contract: accept/remove generic configuration, expose synthetic connectivity and a demo entity, record local events, queue example telemetry, and reject commands other than the no-op `refresh`. The capability catalog is commendably explicit that transport, projects, group objects, DPTs, domain entities, secure handling and bus telemetry are `planned`, while arbitrary telegrams, unknown-DPT writes, address scans and ETS programming are `excluded`.[P-CATALOG] Those exclusions should remain safety boundaries, but the manifest's claims of KNX/IP compatibility, project import, full offline support, and project/datapoint-negotiated controls are not implemented and must not be published as current capability.[P-MANIFEST]

Home Assistant is not merely broader; it is a mature, first-party **Platinum** KNX integration. At the pinned source it uses exact `xknx==4.1.1`, supports automatic interface selection, UDP and TCP tunnelling, KNX IP Secure tunnelling, multicast routing, KNX IP Secure routing and KNX Data Secure, imports ETS project and keyring files, maps project DPT metadata, handles live and persisted telegram history, provides project-assisted entity suggestions, and implements 17 documented entity platforms plus triggers, reads, writes and exposures.[HA-MANIFEST][HA-DOC][HA-MODULE][HA-PROJECT][HA-TRIGGER] This breadth is a comparison baseline, not a requirement to clone every feature.

**Release judgment:** keep version 0.1.0 in draft/unverified/unrated status and do not expose it as a working KNX integration. Build and qualify a deliberately bounded first release before changing those labels. A defensible initial target is one KNX installation per runtime, automatic/manual UDP tunnelling plus TCP tunnelling, imported ETS project metadata, allowlisted standard-DPT group reads and writes, paired command/state addresses, bounded state initialization, incoming telegram events, deterministic identity, and explicit availability. Secure tunnelling/routing, multicast routing, Data Secure and broad HA-like entity semantics should remain unavailable until their complete credential, lifecycle, safety and hardware-test stories are implemented.

## Honest supported slice

### Supported now by reachable PiPhi source

| Dimension | Current support |
|---|---|
| Runtime configuration | Accept a `host` and optional generic fields inherited from `RuntimeConfig`; store entries in process memory; remove or snapshot-sync them. No host validation or connection probe occurs. |
| State and entities | Synthetic `connected: true`, host, alias and IDs; one generic `knx_device` per config, or a fallback demo entity when none exists. |
| Commands | `refresh` is accepted and recorded as a local event. It performs no network or bus refresh. Other commands fail closed. |
| Events and telemetry | Local configuration/command/example events and example `connected: true` telemetry. No KNX telegram event exists. |
| Safety posture | No bus code means it cannot currently send a harmful KNX telegram. Planned/unsafe commands are not advertised and unsupported command names return 400. |

### Not supported or not proven

- Any KNXnet/IP transport: discovery/search, UDP or TCP tunnelling, multicast routing, NAT/route-back, heartbeat, reconnect, tunnel endpoint allocation, KNX IP Secure or KNX Data Secure.
- ETS `.knxproj` project or `.knxkeys` keyring import, project versioning, password handling, secure-key lifecycle, group-object flags, filter-table awareness or project-derived entity suggestions.
- Group or individual address parsing, duplicate individual-address detection, DPT encode/decode, DPT validation, paired command/state addresses, passive addresses or deterministic group-derived entity IDs.
- Bus reads, startup state initialization, writes, response/confirmation handling, readback, timeout outcome handling, telegram receive/deduplication, persisted telegram history, or incoming/outgoing telegram triggers.
- Real connection availability, reconnect, restart recovery, atomic reconfigure, stale state, per-entity quality, queue bounds, backpressure, outgoing rate limiting or routing-busy handling.
- Any field compatibility or hardware qualification. There are no KNX simulators, captured fixtures, gateways, routers, certified products or physical installations represented in tests.

The `bridge_address` and `protocol` fields shown by `/ui-config` and declared editable by the manifest are not fields on `DeviceConfig`; conversely, generic `api_key`, `base_url`, polling and service fields exist in the model but not the KNX UI schema.[P-CONTRACT][P-SCHEMA][P-MANIFEST] This is additional evidence that the current configuration surface is scaffold residue rather than a usable KNX contract.

## Evidence table

| Area | Home Assistant first-party baseline | PiPhi source evidence | Audit result |
|---|---|---|---|
| **Implementation and exact dependency** | Manifest pins `xknx==4.1.1` at commit `e3d8212`, `xknxproject==3.10.0`, a KNX frontend and telegram store; no floating protocol dependency.[HA-MANIFEST][XKNX-CHANGELOG] | Dependencies are FastAPI, Uvicorn and PiPhi Runtime Kit only. `pdm.lock` contains no `xknx`.[P-PROJECT][P-LOCK] | **No KNX implementation.** Adopt an exact, locked protocol reference and record its upstream commit; do not infer capability from the catalog's link to the moving `xknx` default branch. |
| **Tunnelling, routing and lifecycle** | `ConnectionConfig` covers automatic, UDP tunnel, TCP tunnel, secure TCP tunnel, routing and secure routing; HA enables auto-reconnect and starts/stops xknx with the config entry. xknx 4.1.1 fixes stale channel/sequence ACKs, reconnect cancellation, partial TCP frames and shutdown during reconnect.[HA-MODULE][XKNX-CONNECTION][XKNX-CHANGELOG] | `apply_config` never opens a socket and startup sync is an explicit no-op. Removal only deletes an in-memory record.[P-STATE][P-LIFECYCLE] | **Absent, P0.** Connection state must come from the protocol session, not config presence. Restart recovery and shutdown need integration tests. |
| **KNX Secure** | HA supports keyring-backed Data Secure plus IP Secure tunnelling/routing, and redacts keyring password, user password, device authentication and backbone key in diagnostics.[HA-DOC][HA-MODULE][HA-DIAGNOSTICS] | Secure/keyring fields, parser, storage and crypto do not exist.[P-SCHEMA] | **Absent.** Leave all secure modes unsupported in the first bounded release unless full `.knxkeys` import, secret storage/redaction, rotation/reconfigure and Data Secure replay/freshness behavior are implemented. KNX Association identifies IP Secure and Data Secure as distinct protections.[KNX-SECURE] |
| **Gateway and duplicate identity** | Only one HA KNX config entry is allowed; TCP/secure tunnel endpoints are selectable and current/occupied slots are shown. Routing requires a unique individual address, and HA's docs require exclusive use of a tunnel endpoint.[HA-MANIFEST][HA-FLOW][HA-DOC] | Registry identity is generated from generic config, while applying a repeated ID overwrites it. There is no duplicate-host, gateway serial, tunnel endpoint or individual-address check; discovery always identifies `demo-device`.[P-STATE][P-DISCOVERY] | **Absent.** Use stable gateway identity (serial/host individual address where available), prevent duplicate physical endpoints and require a unique routing individual address. KNX Association says each interface/tunnel needs its own individual address.[KNX-IDENTITY] |
| **Project import and mapping** | HA parses password-protected ETS projects with pinned xknxproject, stores project info/devices/group addresses, maps project DPTs into xknx and offers semantics-based entity suggestions while reporting duplicates.[HA-PROJECT][HA-SUGGESTIONS] | The catalog marks project import and every group-object/DPT/entity family `planned`; there is no upload endpoint or parser.[P-CATALOG][P-ROUTES] | **Absent.** A project should inform mapping, not silently expose every group address. Require review/allowlisting, preserve project provenance/hash, reject unresolved DPTs for typed entities, and report duplicate mappings. |
| **Group objects, flags and topology** | HA models configured write/state/passive addresses and project metadata; docs explain the first address as active and the remainder as passive. HA does not claim to enforce every ETS C/R/W/T/U/I flag at runtime.[HA-DOC][HA-ENTITY] | No address or object model exists. The catalog proposes exposing C/R/W/T/U/read-on-init metadata but does not implement it.[P-CATALOG] | **Absent.** Import flags as evidence and warnings, but do not equate ETS flags with authorization. PiPhi must maintain its own explicit read/write allowlist. KNX Association defines flag semantics and filter-table consequences.[KNX-GROUP][KNX-FILTER] |
| **DPTs** | xknx provides a broad standardized DPT registry; HA uses configured platform DPTs or imported project DPT metadata for decoding, events and reads.[HA-PROJECT][HA-SERVICE][XKNX-CHANGELOG] | No DPT classes or codec. The manifest and marketplace description imply datapoint negotiation despite all DPT work being planned.[P-MANIFEST][P-CATALOG] | **Absent and overclaimed.** Start with an explicit DPT allowlist driven by real profiles/installations; never infer meaning from payload width alone and never write an unknown DPT. |
| **Entities and addresses** | 17 documented platforms: binary sensor, button, climate, cover, date, datetime, fan, light, notify, number, scene, select, sensor, switch, text, time and weather. UI/YAML entities have stable unique IDs; command, state and passive address roles are explicit.[HA-DOC][HA-ENTITY] | Every config produces the same generic entity with `connected` and no-op `refresh`; fallback returns a demo entity even with no configuration.[P-ENTITY][P-CONTRACT] | **No KNX entities.** Do not target all 17 initially. Begin with sensor, binary sensor, switch and dimmable light only when their DPT/address semantics and state feedback are proven. Remove fallback/demo production entities. |
| **Reads and availability** | Push updates drive state. State updater reads configured state addresses on initialization and, by default, after 60 minutes without an update; xknx 4.1.1 coalesces reads sharing an address. All KNX entities are unavailable when the connection is down.[HA-DOC][HA-ENTITY][XKNX-CHANGELOG] | Applying config immediately sets `connected: true`; `/state?refresh=true` invokes generic runtime state behavior but no KNX read. No stale/unavailable model exists.[P-STATE][P-RUNTIME] | **False-positive availability, P0.** Distinguish process health, IP session, bus reachability and datapoint freshness. Never report connected before protocol setup succeeds. |
| **Writes, confirmation and readback** | Entity methods and `knx.send` encode typed or raw GroupValueWrite/Response telegrams. xknx processes the outgoing telegram into local entity state after link-layer send; normal group writes are not per-command application readback. `knx.read` can wait two seconds for a GroupValueResponse.[HA-SERVICE][XKNX-REMOTE] | `refresh` only records receipt. There is no group write, confirmation, readback or unknown-outcome state.[P-STATE] | **Absent.** PiPhi should be safer than HA's broad raw service: named/project-bound writes only, explicit DPT/range, no arbitrary telegram API, and optional bounded readback only where a distinct readable state address is defined. Do not blindly retry timed-out writes. |
| **Telegram events and persistence** | `knx.telegram` triggers filter destination, APCI and direction and include raw/decoded/project metadata. HA stores incoming/outgoing telegram history in SQLite or PostgreSQL with retention and bounded buffering.[HA-TRIGGER][HA-TELEGRAMS][HA-DOC] | `/events` contains only local runtime events; example POST routes can manufacture events. No telegram record, filter or persistence exists.[P-EVENTS] | **Absent.** Keep raw payloads out of general automation events by default; emit bounded normalized events with direction/source/destination, DPT, quality and redaction policy. |
| **Rate limiting and bus safety** | HA exposes a 0–60 telegram/s option; default `0` disables it and HA's docs recommend that default. xknx serializes its outgoing queue, supports a rate limiter, limits state reads to two concurrent workers, coalesces shared-address reads, serializes routing sends, waits after routing indications and honors `ROUTING_BUSY`.[HA-DOC][HA-FLOW][HA-MODULE][XKNX-QUEUE][XKNX-STATE][XKNX-ROUTING] KNX Association warns that bus load above 50% can increase sporadic failures; telegrams/s is not equivalent to bus-load percentage.[KNX-BUS] | No bus, queue, rate setting, destination budget or backpressure. Generic command behavior declares retries even though the no-op is marked idempotent.[P-BEHAVIORS] | **Absent, P0 before writes.** Bound queue size and age, reads per startup window, writes per endpoint/address and automation fanout. Rate limiting alone is insufficient if the queue is unbounded. |
| **Reconfigure, unload and restart** | HA has a reconfigure flow, reloads the entry, closes xknx and telegram storage on unload, persists entry/project/entity data and auto-reconnects.[HA-FLOW][HA-INIT][HA-MODULE] | Reapplying overwrites the registry without staging or probing; startup config recovery is a no-op; all active configuration/state is process memory.[P-STATE][P-LIFECYCLE] | **P0 gap.** Candidate config must connect and prove identity before an atomic swap. Replay persisted config on restart and retain the last working config on failed reconfigure. |
| **Diagnostics and privacy** | HA diagnostics redact secure credentials and external DB DSN; project name is redacted. Diagnostics are an authenticated HA support surface, though they still intentionally contain topology/config metadata.[HA-DIAGNOSTICS] | `/diagnostics`, `/state`, `/entities` and `/events` have no visible route guard; tests configure/read/deconfigure without credentials. Diagnostics expose active config IDs and events can contain hosts. No explicit privacy tests exist.[P-APP][P-HEALTH][P-EVENTS][P-TESTS] | **P0 boundary gap.** Define one public liveness route; authenticate every operational read and mutation; redact hosts, individual/group addresses, project names/hashes and all key material according to a documented support bundle policy. |
| **Tests** | HA has 74 KNX test files at the pinned tree, covering config, connection variants, platforms, project storage/suggestions, secure configuration, telegrams, services, diagnostics, repairs and lifecycle.[HA-TESTS] The exact xknx release has its own protocol tests.[XKNX-TESTS] | Three small test modules check route presence, generic fixtures, catalog consistency, one config event and rejection of three unsupported commands. There is no protocol or hardware test because there is no protocol path.[P-TESTS] | **Scaffold conformance only.** It does not support a KNX quality claim. Add protocol simulators, malformed/duplicate/loss/reconnect tests, project fixtures with provenance, and a published physical gateway/router matrix. |
| **CI and release** | HA pins runtime requirements and marks the reviewed integration Platinum.[HA-MANIFEST][HA-IQS-FILE] | App metadata uses `legacy-static`; repository CI therefore validates metadata and returns without running the declared install/tests. Container build is disabled in CI. Release qualification follows the same path. Docker ignores `pdm.lock` and installs dependency ranges. Manifest remains draft/unverified/unrated, points to Docker Hub while release metadata targets GHCR, and no package tag was found.[P-APP-META][CI-RUNNER][P-DOCKER][P-MANIFEST][RELEASE-CI] | **P0 release gap.** Enforce lock install, tests, validation and exact-image smoke tests; build from the lock; align registry references; retain SBOM/provenance support; publish only immutable digest evidence after qualification. |
| **Hardware qualification** | HA and xknx provide broad software evidence but do not make every installation/device interchangeable; operators configure group addresses and interface details. KNX Association separately lists certified products and requires accredited interworking/functionality testing plus hardware declarations/tests for KNX product certification.[HA-DOC][KNX-CERT] | Marketplace claims compatibility with “KNX/IP projects and datapoints represented in the imported project,” but no imported project or hardware evidence exists.[P-MANIFEST] | **Unqualified.** Publish tested gateway/router model, firmware, transport/security mode, project source, entity/DPT slice and duration. Do not imply KNX certification; software integration qualification is not KNX product certification. |

## Analogical Home Assistant IQS assessment

Home Assistant's KNX integration is explicitly `platinum`, with a checked `quality_scale.yaml`; Platinum requires all applicable Bronze, Silver, Gold and Platinum rules.[HA-MANIFEST][HA-IQS-FILE][HA-IQS] PiPhi cannot literally earn an HA tier. The assessment below asks whether comparable evidence exists, not whether HA-specific architecture has been copied.

| IQS level | Analogous PiPhi evidence | Assessment |
|---|---|---|
| **Bronze** | A UI-schema endpoint, required generic runtime routes, unsupported-command rejection, maintainer metadata and basic scaffold tests exist.[P-CONTRACT][P-TESTS] | **Does not meet Bronze equivalence.** Setup never tests KNX communication, discovery is fake, duplicate setup is allowed, the advertised entity is not functional, documentation is generated/starter text, config fields disagree, and normal CI skips tests. |
| **Silver** | Deconfigure removes in-memory entries and the generic runtime kit provides a lifecycle shell.[P-STATE][P-LIFECYCLE] | **Does not meet Silver equivalence.** No real availability, recovery, unload of protocol resources, actionable connection errors, >95% measured coverage, credential/keyring lifecycle, or unavailable/recovered logging exists. |
| **Gold** | A diagnostics route and a detailed planned capability catalog exist.[P-HEALTH][P-CATALOG] | **Does not meet Gold equivalence.** Diagnostics are not privacy-bounded, discovery/project import/entity mapping/repairs/reconfigure/operator docs are absent, and no supported hardware/function matrix exists. |
| **Platinum** | FastAPI handlers are async and source has type annotations.[P-ROUTES] | **Does not meet Platinum equivalence.** There is no async KNX dependency, strict type-check gate or meaningful integration architecture to assess. |

## Safety invariants to preserve and implement

1. **No arbitrary bus API.** Normal callers select an imported, reviewed datapoint or named action; they never supply a raw telegram, APCI, individual destination, unknown DPT or invocation-time group address.
2. **Project data is metadata, not authorization.** Importing an ETS project must not automatically make every writable group address writable. Require an explicit allowlist and preserve project hash/version provenance.
3. **Known DPT before decode or write.** Unknown, conflicting or width-only DPTs may be monitored as opaque metadata but may not become typed entities or write targets. KNX Association treats DPT as part of Group Object/Group Address configuration.[KNX-GROUP]
4. **Separate command and feedback.** Prefer distinct write and state addresses. A locally transmitted GroupValueWrite is not actuator readback; mark commanded/assumed state separately until feedback arrives.
5. **No blind write retry.** A timeout can mean the actuator changed but the confirmation/feedback was lost. Surface an unknown outcome; retry only an operation with proven idempotence and an installation-specific policy.
6. **Bound all traffic and memory.** Enforce per-interface outgoing rate, bounded queue depth/age, startup-read budget, duplicate read coalescing, fair automation fanout and routing-busy backoff. Reject rather than accumulate beyond the budget.
7. **One owner per physical identity.** Reject duplicate gateway serial/endpoint/tunnel slot and duplicate routing individual address. A tunnel endpoint must not be shared; a routing individual address must be unique and topology-correct.[HA-DOC][KNX-IDENTITY]
8. **Fail closed on secure metadata.** Never downgrade a secure group to plain communication. Keep keyring, backbone key, user password, authentication code and group keys encrypted at rest where the platform supports it, out of logs/events/diagnostics, and replaceable through reconfigure.[KNX-SECURE]
9. **Transactional configuration.** Parse and validate project/keyring, resolve interface identity, establish the candidate session and perform a bounded safe probe before activation. Failed reconfigure leaves the previous session and mapping intact.
10. **Truthful health.** Distinguish runtime alive, IP session connected, bus traffic observed, datapoint initialized and datapoint stale. Never derive connectivity from configuration presence.
11. **No commissioning or topology mutation.** Keep individual-address programming, application download, device reset, parameter/group-link changes, broad scans and ETS replacement outside the integration.
12. **Minimize event data.** Telegram events are allowlisted and bounded; default automation surfaces use decoded values and pseudonymized identity where possible. Raw telegram history and full project topology require an authenticated administrative surface and retention controls.

## Prioritized concrete work

### P0 — blockers before any working KNX release

1. **Correct claims and release gates now.** Keep publication draft/unverified/unrated; remove or clearly mark unimplemented KNX/IP, project import, compatibility and offline-support claims; remove production demo entities/discovery; align GHCR image references; make CI run lock verification, tests, validation, container build and an exact-image smoke test.
2. **Choose and freeze the bounded architecture.** Either embed an exact locked `xknx` release or build the catalog's sidecar with an equally explicit versioned contract. Document process/secret boundaries. Do not advertise sidecar behavior before the sidecar exists.
3. **Implement real connection ownership and recovery.** Start with automatic/manual UDP and TCP tunnelling only; model stable gateway/tunnel identity, exclusive endpoint ownership, heartbeat/reconnect, connection-derived availability, orderly unload and durable config replay. Add loss, stale ACK, reconnect, shutdown and restart tests based on xknx 4.1.1's corrected cases.[XKNX-CHANGELOG]
4. **Implement reviewed project-to-datapoint configuration.** Parse password-protected `.knxproj` through a pinned parser, preserve project hash/version, validate addresses and DPTs, surface flags and conflicts, and require explicit selection of exposed entities/write targets. Fail closed when metadata is missing or ambiguous.
5. **Implement the first safe semantic slice.** Limit v1 to sensor, binary sensor, switch and dimmable light with a documented DPT/address matrix, paired command/state addresses, initialization reads, feedback/assumed-state distinction, typed/ranged writes and unknown-outcome handling. No raw send API.
6. **Build bus budgets before enabling writes.** Bound queues, queue age, reads and writes; coalesce state reads; serialize protocol sends; honor routing/tunnel flow control from the chosen upstream; block unsafe automation fanout and never blindly retry a write.
7. **Close API and privacy boundaries.** Authenticate config/deconfigure, commands, state, entities, events, diagnostics and telemetry mutation; leave only minimal liveness public. Add route-enumeration and redaction tests covering hosts, addresses, project metadata and every secure secret class.

### P1 — quality baseline after the bounded protocol slice works

8. Add transactional reconfigure and project/keyring update with rollback; report duplicate physical identity and mapping conflicts as actionable errors.
9. Add normalized incoming/outgoing telegram events, bounded persistence/retention and filters; keep raw history administrative and opt-in.
10. Replace scaffold tests with malformed-frame, duplicate/loss/reorder, read timeout, queue saturation, restart, privacy and end-to-end gateway-simulator tests. Enforce coverage and strict typing rather than declaring `legacy-static`.
11. Write operator documentation for prerequisites, ETS tunnel/dummy-device/filter-table setup, every field/default, DPT/address mapping, availability semantics, removal/reconfigure, privacy, troubleshooting, known limits and safe rollback.
12. Qualify real hardware: at least two certified KNX/IP interfaces from different vendors for UDP/TCP tunnelling, recorded firmware and long-running reconnect/load tests. Publish failures and exclusions as well as passes.

### P2 — demand-driven breadth

13. Add multicast routing only after unique individual-address checks, topology guidance, routing-busy/load tests and multiple-router hardware qualification.
14. Add KNX IP Secure tunnelling/routing and Data Secure only with complete keyring import, secure storage, rotation, redaction, replay/freshness, secure-group no-downgrade and hardware evidence.
15. Expand entity/DPT families from attributed installation needs. Add climate, covers, fan, metering, scenes and time/date independently; do not use Home Assistant's 17-platform breadth as a checklist detached from fixtures.
16. Add project semantic suggestions only as reviewed proposals with duplicate/conflict reporting. Keep ETS programming, broad scans, raw telegram writes and topology mutation excluded.

## Validation performed and environmental limits

- `pdm lock --check` completed successfully.
- `PYTHONPATH=src pdm run python scripts/validate.py` completed: `PiPhi scaffold validation passed.` This validator checks manifest/route/behavior consistency, not KNX behavior.
- The default `pdm run pytest` did not reach collection because the active shared environment auto-loaded a missing `piphi_runtime_testkit_python` pytest plugin. A second run with plugin autoload disabled and `PYTHONPATH=src` also failed during collection because the shared environment had inconsistent OpenTelemetry packages (`opentelemetry._logs.severity` missing). No test result is claimed.
- No KNX interface, router, ETS project/keyring, bus simulator or physical installation was available. Protocol and hardware behavior therefore could not be exercised; none exists in the PiPhi source path to exercise.
- Repository inspection found no matching release tag for this package. CI/release conclusions are static workflow analysis, not a claim about externally retained GitHub Actions history or an OCI registry.

## Primary sources

### Home Assistant and exact upstream references

- **[HA-CORE]** Home Assistant Core, [KNX component at `296ac4d9`](https://github.com/home-assistant/core/tree/296ac4d97c0b602077087a0b662b90fea290e955/homeassistant/components/knx).
- **[HA-MANIFEST]** Home Assistant Core, [`manifest.json` at `296ac4d9`](https://github.com/home-assistant/core/blob/296ac4d97c0b602077087a0b662b90fea290e955/homeassistant/components/knx/manifest.json) — exact requirements and Platinum/single-entry metadata.
- **[HA-DOC]** Home Assistant, [KNX documentation at `fc4e4718`](https://github.com/home-assistant/home-assistant.io/blob/fc4e4718316657cd0487a2c1b70954cb90d29d82/source/_integrations/knx.markdown).
- **[HA-INIT]** Home Assistant Core, [setup, unload and migration](https://github.com/home-assistant/core/blob/296ac4d97c0b602077087a0b662b90fea290e955/homeassistant/components/knx/__init__.py).
- **[HA-MODULE]** Home Assistant Core, [xknx construction, transport/secure config, connection state and events](https://github.com/home-assistant/core/blob/296ac4d97c0b602077087a0b662b90fea290e955/homeassistant/components/knx/knx_module.py).
- **[HA-FLOW]** Home Assistant Core, [config, reconfigure, gateway scan, tunnel endpoint and options flow](https://github.com/home-assistant/core/blob/296ac4d97c0b602077087a0b662b90fea290e955/homeassistant/components/knx/config_flow.py).
- **[HA-PROJECT]** Home Assistant Core, [ETS project storage and DPT mapping](https://github.com/home-assistant/core/blob/296ac4d97c0b602077087a0b662b90fea290e955/homeassistant/components/knx/project.py).
- **[HA-SUGGESTIONS]** Home Assistant Core, [project functional-block entity suggestions](https://github.com/home-assistant/core/blob/296ac4d97c0b602077087a0b662b90fea290e955/homeassistant/components/knx/storage/entity_suggestions/functional_blocks.py).
- **[HA-ENTITY]** Home Assistant Core, [availability, stable identity and lifecycle](https://github.com/home-assistant/core/blob/296ac4d97c0b602077087a0b662b90fea290e955/homeassistant/components/knx/entity.py).
- **[HA-SERVICE]** Home Assistant Core, [typed/raw writes and response reads](https://github.com/home-assistant/core/blob/296ac4d97c0b602077087a0b662b90fea290e955/homeassistant/components/knx/services.py).
- **[HA-TRIGGER]** Home Assistant Core, [telegram trigger](https://github.com/home-assistant/core/blob/296ac4d97c0b602077087a0b662b90fea290e955/homeassistant/components/knx/trigger.py).
- **[HA-TELEGRAMS]** Home Assistant Core, [telegram history, retention and bounded buffer](https://github.com/home-assistant/core/blob/296ac4d97c0b602077087a0b662b90fea290e955/homeassistant/components/knx/telegrams.py).
- **[HA-DIAGNOSTICS]** Home Assistant Core, [diagnostic redaction](https://github.com/home-assistant/core/blob/296ac4d97c0b602077087a0b662b90fea290e955/homeassistant/components/knx/diagnostics.py).
- **[HA-IQS-FILE]** Home Assistant Core, [KNX `quality_scale.yaml`](https://github.com/home-assistant/core/blob/296ac4d97c0b602077087a0b662b90fea290e955/homeassistant/components/knx/quality_scale.yaml).
- **[HA-TESTS]** Home Assistant Core, [KNX tests at the pinned commit](https://github.com/home-assistant/core/tree/296ac4d97c0b602077087a0b662b90fea290e955/tests/components/knx).
- **[HA-IQS]** Home Assistant developer documentation, [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/) and [rules](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/).
- **[XKNX]** XKNX, [exact 4.1.1 source at `e3d8212`](https://github.com/XKNX/xknx/tree/e3d8212777160af85ea2ecb4e5b9c01d7e600b03).
- **[XKNX-CHANGELOG]** XKNX, [4.1.1 and 4.1.0 changes](https://github.com/XKNX/xknx/blob/e3d8212777160af85ea2ecb4e5b9c01d7e600b03/docs/changelog.md#411-tunnel-robustness-2026-11-05).
- **[XKNX-CONNECTION]** XKNX, [connection types and reconnect configuration](https://github.com/XKNX/xknx/blob/e3d8212777160af85ea2ecb4e5b9c01d7e600b03/xknx/io/connection.py).
- **[XKNX-QUEUE]** XKNX, [telegram queue and outgoing rate limiter](https://github.com/XKNX/xknx/blob/e3d8212777160af85ea2ecb4e5b9c01d7e600b03/xknx/core/telegram_queue.py).
- **[XKNX-STATE]** XKNX, [state updater and read concurrency](https://github.com/XKNX/xknx/blob/e3d8212777160af85ea2ecb4e5b9c01d7e600b03/xknx/core/state_updater.py).
- **[XKNX-ROUTING]** XKNX, [routing flow control](https://github.com/XKNX/xknx/blob/e3d8212777160af85ea2ecb4e5b9c01d7e600b03/xknx/io/routing.py).
- **[XKNX-REMOTE]** XKNX, [remote-value send, local outgoing processing and state reads](https://github.com/XKNX/xknx/blob/e3d8212777160af85ea2ecb4e5b9c01d7e600b03/xknx/remote_value/remote_value.py).
- **[XKNX-TESTS]** XKNX, [tests at the exact reference](https://github.com/XKNX/xknx/tree/e3d8212777160af85ea2ecb4e5b9c01d7e600b03/test).
- **[XKNXPROJECT]** xknxproject, [exact 3.10.0 source at `1334c4e`](https://github.com/XKNX/xknxproject/tree/1334c4e48ef9ba59b78af24d5c4ba68fcd21d7f9).

### KNX Association guidance

- **[KNX-GROUP]** KNX Association, [Group Object](https://support.knx.org/hc/en-us/articles/360008521939-Group-Object) and [Group Address panel details](https://support.knx.org/hc/en-us/articles/360022048059-Group-Address-panel-detailed) — DPT and C/R/W/T/U/I flag meanings.
- **[KNX-FILTER]** KNX Association, [Filter tables](https://support.knx.org/hc/en-us/articles/115003363245-Filter-tables) — interface associations, dummy devices and coupler filter-table consequences.
- **[KNX-BUS]** KNX Association, [Groups Diagnostics](https://support.knx.org/hc/en-us/articles/360019068120-Groups-Diagnostics) — diagnostic guidance and the warning that bus load above 50% can cause sporadic failures.
- **[KNX-IDENTITY]** KNX Association, [Connection Manager details](https://support.knx.org/hc/en-us/articles/4402353231762-Connection-Manager-Detailed) and [unique additional addresses](https://support.knx.org/hc/en-us/articles/4688187652114-There-are-no-more-unique-additional-addresses-available) — unique/topology-correct individual addresses and tunnel identities.
- **[KNX-SECURE]** KNX Association, [KNX Secure devices](https://support.knx.org/hc/en-us/articles/360000216419-KNX-Secure-Devices), [Secure Tunnelling](https://support.knx.org/hc/en-us/articles/360000653399-Secure-Tunneling), [KNX Data Secure](https://support.knx.org/hc/en-us/articles/360012689639-KNX-Data-Secure), and [keyring use outside ETS](https://support.knx.org/hc/en-us/articles/360001582259-Use-keyring-outside-ETS-Falcon-SDK).
- **[KNX-CERT]** KNX Association, [certified-product directory](https://www.knx.org/knx-en/for-professionals/get-started/certified-knx-products), [product testing](https://support.knx.org/hc/en-us/articles/4587619778706-Product-testing), and [certification](https://support.knx.org/hc/en-us/articles/4590640219922-Certification-by-KNX-Association).

### PiPhi repository evidence

- **[P-PROJECT]** [Python project and dependencies](../pyproject.toml)
- **[P-LOCK]** [dependency lock](../pdm.lock)
- **[P-README]** [README](../README.md)
- **[P-MANIFEST]** [manifest and marketplace claims](../manifest.json)
- **[P-APP-META]** [CI/release package metadata](../piphi-app.json)
- **[P-DOCKER]** [container build](../Dockerfile)
- **[P-CATALOG]** [implemented/planned/excluded capability catalog](../capability-catalog.json)
- **[P-CONTRACT]** [runtime contract definitions](../src/piphi_network_knx/contract.py)
- **[P-SCHEMA]** [configuration model](../src/piphi_network_knx/schemas.py)
- **[P-STATE]** [registry, synthetic state and no-op command action](../src/piphi_network_knx/state.py)
- **[P-LIFECYCLE]** [startup lifecycle](../src/piphi_network_knx/lifecycle.py)
- **[P-APP]** [route assembly](../src/piphi_network_knx/app.py)
- **[P-ROUTES]** [route package](../src/piphi_network_knx/routes/)
- **[P-COMMAND]** [command dispatch](../src/piphi_network_knx/routes/commands.py)
- **[P-DISCOVERY]** [demo discovery and UI schema](../src/piphi_network_knx/routes/discovery.py)
- **[P-ENTITY]** [demo-shaped entities](../src/piphi_network_knx/routes/entities.py)
- **[P-RUNTIME]** [generic state route](../src/piphi_network_knx/routes/runtime.py)
- **[P-HEALTH]** [health and diagnostics](../src/piphi_network_knx/routes/health.py)
- **[P-EVENTS]** [local/example events](../src/piphi_network_knx/routes/events.py)
- **[P-BEHAVIORS]** [automation behavior metadata](../src/behaviors.json)
- **[P-TESTS]** [tests](../tests/)
- **[CI-RUNNER]** [repository app CI runner](../../../../scripts/run_app_ci.py) and [workflow](../../../../.github/workflows/apps-ci.yml)
- **[RELEASE-CI]** [repository release workflow](../../../../.github/workflows/release-app.yml)
