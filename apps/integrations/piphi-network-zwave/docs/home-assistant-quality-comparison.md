# PiPhi Z-Wave and Home Assistant Z-Wave JS: capability and quality audit

**Research cutoff:** 2026-11-15

**PiPhi source audited:** `piphi-network-zwave` `0.3.0` and `piphi-zwave-js-sidecar` `0.3.0`, treated as one delivery boundary; source, tests, manifests, CI, documentation and release metadata at workspace commit `e9c7fb55230a5512735f333c7f802e580f81743a` (the audited implementation is present in `8c4dc844ee51f8282382a2fb3d60f5978cb91a9f`)

**v0.3.1 remediation note:** the coordinated v0.3.1 update closes P0 items 1–3
below: confirmed-success handling for `SetValueResult`, supported `refreshInfo()`
interview refresh behavior, and default-deny authorization for every operational
route. The remaining P0/P1 items stay planned and are not marketplace claims;
qualification remains unverified with rollout at zero.

**v0.4.0 software-hardening note:** the coupled update adds full hashed Home ID
and controller/node/value identity, transactional and durable configuration,
single-device serial mapping, dependency readiness and stale-last-good recovery,
recursive security-material redaction, deterministic controller simulation,
bounded confirmed secure commissioning/exclusion/failed-node workflows, and
digest/identity-checked NVM backup/restore with rollback. These are software
contract results only; physical controller, security-class, RF mesh, device,
firmware, and NVM migration qualification remain unverified.

**External baseline:** Home Assistant Core `2026.11.1`, Z-Wave JS `v15.32.3`, and `zwave-js-server` `3.12.0`

**Method:** reachable production source outranks README, manifest and capability-catalog claims. Upstream Z-Wave JS capability is not PiPhi capability unless PiPhi exposes it safely and tests it. Software tests establish only the behavior they execute; they do not prove controller, RF, device or field interoperability.

## Executive conclusion

PiPhi has a useful **bounded Z-Wave value bridge**, not Home Assistant Z-Wave JS parity. Its honest supported slice is one locally attached serial controller, one active sidecar configuration, durable controller restoration, controller/node/value snapshots, bounded event replay, node/endpoint state for eight allow-listed command classes, five metadata-constrained value writes, three maintenance actions, and guarded administration APIs. The parent detects replay gaps or sidecar restarts and reconciles from a complete snapshot. The sidecar pins the audited Z-Wave JS version exactly and keeps controller ownership behind a separate non-root process.[P-STATE][P-MODEL][S-STATE][S-DRIVER][S-PACKAGE][S-DOCKER]

The v0.3.1 correctness defects are closed: re-interview uses `refreshInfo()`, and only confirmed `SetValueResult.Success` is reported as completion. v0.4.0 also closes the audited software gaps in route authorization, durable identity, restart restoration, transactional setup, and narrow serial mapping.

The larger product gap is physical qualification and protocol breadth. The software now implements bounded S2/DSK inclusion, exclusion, failed-node removal/replacement, and checked NVM backup/restore, but has no real-controller, RF, security-class, device, firmware, serial-hotplug, soak, or NVM migration evidence. SmartStart, Long Range administration, association/configuration-parameter management, route/heal controls, RF-region handling, controller statistics, firmware update, and controller migration remain unsupported.[P-CATALOG][S-CATALOG][ZWAVE-SERVER-SCHEMA]

The release metadata correctly says `draft`, `unverified` and `unrated`, with rollout at zero.[P-MANIFEST][S-MANIFEST] Keep those labels. Current PiPhi evidence does **not** demonstrate even an analogous Home Assistant Bronze tier, and PiPhi cannot literally receive a Home Assistant Integration Quality Scale tier because it is not a Home Assistant integration.

## What is being compared

Home Assistant's first-party integration is a mature product surface built over `zwave-js-server` through `zwave-js-server-python`; PiPhi embeds `zwave-js` directly in its managed sidecar.[HA-DOC][HA-CORE][HA-PYTHON][ZWAVE-SERVER-README] The architectural difference is valid, but it means protocol-library breadth cannot substitute for product behavior.

This audit separates:

1. **Protocol breadth** — what Z-Wave JS can do.
2. **Exposed behavior** — what the PiPhi parent/sidecar path actually makes available.
3. **Quality evidence** — lifecycle, failure semantics, identity, security, diagnostics, documentation, tests and release qualification.

## Evidence table

| Area | Home Assistant first-party baseline | PiPhi source evidence | Audit result |
|---|---|---|---|
| **Architecture and dependency** | HA connects to a separately managed Z-Wave JS server using the first-party Python client and server schema.[HA-CORE][HA-PYTHON][ZWAVE-SERVER-SCHEMA] | A Node sidecar owns the serial controller and embeds exact `zwave-js` `15.32.3`; the Python parent polls authenticated snapshot/event endpoints.[S-PACKAGE][S-DRIVER][P-SIDECAR] | **Sound seam, narrow product.** Exact Z-Wave JS pinning is good. Parent and sidecar must nevertheless be qualified and released as one compatibility boundary. |
| **Controller setup** | HA config flow supports server discovery/manual URL setup, validation, duplicate prevention, reconfigure and migration paths.[HA-CONFIG][HA-INIT] | One mapped controller is accepted; candidate setup must become ready and expose full network/controller hashes before atomic replacement. An optional expected controller hash pins restoration.[S-STATE][S-SCHEMA][P-SCHEMA] | **Narrow but fail-closed in software.** Physical adapter aliasing and migration remain unqualified. |
| **Controller lifecycle** | HA handles connect/disconnect, config entry unload/reload, client events, driver readiness and server version compatibility.[HA-INIT][HA-TESTS] | Both runtimes restore persisted configuration, preserve the previous session/model on failed replacement, use bounded recovery, and expose dependency readiness.[S-DRIVER][S-STATE][P-STATE] | **Strong software lifecycle, incomplete system proof.** No physical hot-unplug/replug, crash-loop, or soak qualification. |
| **Configuration persistence** | HA config entries survive restart and are set up again by Core.[HA-INIT][HA-CONFIG] | Parent and sidecar atomically persist controller configuration and restore it during lifespan startup; parent can verify the expected controller hash.[P-LIFECYCLE][P-STATE][S-STATE] | **Software restart restoration implemented.** Simultaneous process and physical-controller recovery still needs hardware qualification. |
| **Inclusion/exclusion and security** | HA exposes inclusion, exclusion, S2/DSK handling, SmartStart provisioning and related events through the server/client stack.[HA-DOC][HA-SERVICES][ZWAVE-SERVER-SCHEMA] | Authenticated admin routes require exact confirmations, S2-only DSK/classes, serialized sessions, cancellation, and bounded timeouts.[P-CATALOG][S-CATALOG] | **Implemented but hardware-unqualified.** SmartStart/QR provisioning and physical security-class negotiation are not claimed. |
| **Long Range and network administration** | Current HA/server surfaces include controller/network operations and evolving Z-Wave Long Range support where the adapter/region supports it.[HA-DOC][ZWAVE-SERVER-SCHEMA] | No LR node provisioning, RF-region, route, heal, association, configuration-parameter, failed-node, statistics or controller reset surface.[P-CATALOG] | **Not supported.** Do not inherit these capabilities from upstream `zwave-js`. |
| **Command-class coverage** | HA discovery maps Z-Wave values/events into `binary_sensor`, `button`, `climate`, `cover`, `event`, `fan`, `humidifier`, `light`, `lock`, `number`, `select`, `sensor`, `siren`, `switch` and `update` platforms.[HA-INIT][HA-ENTITY][HA-CORE] | Parent recognizes Binary Switch 37, Multilevel Switch 38, Meter 50, Sensor Multilevel 49, Thermostat Mode 64, Thermostat Setpoint 67, Door Lock 98 and Battery 128.[P-MODEL] | **Honest small allow-list.** Useful, but not broad device-platform parity. Values from all other command classes may exist in sidecar snapshots but do not become semantic PiPhi capabilities. |
| **Value writes** | HA entities/services interpret server responses and expose platform-appropriate controls.[HA-ENTITY][HA-SERVICES] | Parent permits only negotiated metadata-declared writes; sidecar re-resolves metadata and accepts only confirmed `SetValueResult.Success`.[P-MODEL][S-DRIVER] | **Fail-closed software contract.** Physical RF outcomes and device-specific supervision still need qualification.[ZWAVE-NODE] |
| **Node interview and refresh** | HA follows server-supported node interview/re-interview and refresh semantics.[HA-DOC][ZWAVE-SERVER-SCHEMA] | Refresh values calls `refreshValues()` and re-interview calls the supported `refreshInfo()` path.[S-DRIVER] | **Implemented in software; physical timing and sleeping-node behavior remain unqualified.** |
| **Events and replay** | HA consumes server events, dispatches value notifications and device events, and dynamically reconciles entities/devices.[HA-INIT][HA-ENTITY][HA-TESTS] | Sidecar uses a bounded sequenced buffer with stream ID and drop count. Parent detects gaps, stream changes and restart-like counter resets, then resynchronizes via snapshot.[S-TRANSPORT][S-STATE][P-STATE] | **One of the strongest PiPhi areas.** Still polling rather than a persistent event stream; no durable replay across sidecar restart, and generic event delivery is not equivalent to HA event-platform coverage. |
| **Entity and device identity** | HA device/entity identity uses stable identifiers from the Z-Wave network/device model and reconciles discovered/removed values.[HA-ENTITY][HA-TESTS] | Sidecar derives full SHA-256 network, controller, node and value identities; parent entity IDs include full controller/node hashes and endpoint.[P-MODEL][P-SCHEMA] | **Stable pseudonymous identity implemented.** Physical replacement/reinclusion reconciliation still needs device testing. |
| **Availability and stale state** | HA reacts to node/server availability, retains registry semantics, and has extensive entity lifecycle tests.[HA-ENTITY][HA-TESTS] | Parent derives connected/availability from snapshot readiness/status and marks the sidecar unavailable after transport failures; resync replaces normalized models.[P-STATE][P-MODEL] | **Basic behavior exists.** No explicit last-seen/staleness policy for sleeping nodes, device-removal UX, or field evidence across battery devices and restart cycles. |
| **Firmware and NVM** | HA exposes firmware update behavior and controller backup/restore/migration workflows where supported.[HA-DOC][HA-SERVICES][ZWAVE-SERVER-SCHEMA] | NVM backup/restore verifies digest and controller identity, takes a rollback backup, and checks postconditions. Firmware and migration remain absent.[P-CATALOG] | **Guarded software NVM lifecycle implemented, hardware-unqualified.** Firmware and cross-controller migration are not supported. |
| **Diagnostics, repairs and redaction** | HA has downloadable diagnostics with explicit redaction and repair flows for actionable problems.[HA-DIAGNOSTICS][HA-CORE][HA-TESTS] | Authenticated diagnostics expose bounded operational metadata; recursive redaction removes security keys, DSKs, raw frames, NVM, tokens and private fields. Public health is minimal.[S-STATE][S-TRANSPORT][P-HEALTH] | **Privacy boundary materially improved.** No HA-like repair workflow or downloadable support bundle. |
| **Authorization boundary** | HA diagnostic/service APIs sit behind authenticated HA permissions; its integration does not expose an unauthenticated local management API.[HA-DIAGNOSTICS][HA-SERVICES] | Both runtimes default-deny every operational route and leave only `/health` public; test-only bypass requires an explicit non-production flag.[S-AUTH][S-CONFIG][P-CONFIG][P-AUTH] | **P0 gap closed in software.** Deployment still must provision and rotate the internal token. |
| **Serial privilege boundary** | HA deployment guidance supports local USB adapters and remote servers.[HA-DOC] | Sidecar runs non-root/read-only and maps one host by-id device to `/dev/zwave-controller`; runtime path validation is allow-listed.[S-DOCKER][S-MANIFEST] | **Least-privilege mapping implemented.** Physical hotplug and descriptor replacement remain unqualified. |
| **Tests** | HA has a large first-party suite covering setup, migration, discovery, platforms, services, events, diagnostics and failures.[HA-TESTS] | Deterministic parent and fake-controller suites cover auth, redaction, identity, transaction rollback, replay/recovery, commissioning serialization, failed-node actions and NVM lifecycle.[P-TESTS][S-TESTS] | **Strong software baseline, insufficient physical qualification.** No controller/device matrix, RF loss, sleeping-node, hotplug, firmware, migration or soak evidence. |
| **CI and release metadata** | HA pins requirements and validates the integration in Core CI; the current manifest has no `quality_scale`, and no current `quality_scale.yaml` is present.[HA-MANIFEST][HA-CORE] | Frozen installs, strict TypeScript, package validators, monorepo validation, pinned base images and non-root runtimes are exercised. Both manifests remain draft/unverified/unrated.[P-DOCKER][S-DOCKER][CI][RELEASE-CI][P-MANIFEST][S-MANIFEST] | **Good release mechanics, no hardware release qualification.** Status metadata remains intentionally conservative. |
| **Documentation** | HA documents setup, supported adapters/features, inclusion/exclusion, security, troubleshooting, backups, migration, services and events.[HA-DOC] | PiPhi README/generated contract/release docs describe architecture and routes; catalogs separate implemented/planned/excluded groups.[P-README][S-README][P-CONTRACT][S-CONTRACT][P-CATALOG] | **Gap.** Missing operator-grade commissioning, controller ownership, restart/recovery, supported-device matrix, deconfigure/reconfigure, privacy, backup/migration and known-limit guidance. |

## Honest supported slice

### Supported by reachable production paths

| Dimension | Supported slice |
|---|---|
| Controller | One narrowly mapped local serial controller and one active sidecar configuration; Z-Wave JS `15.32.3`; non-root/read-only sidecar; persistent cache/lock/state directories. |
| Read model | Complete controller/node snapshots and node/endpoint value metadata; status, readiness, manufacturer/product/firmware metadata when supplied upstream. |
| Semantic command classes | Binary Switch (37), Multilevel Switch (38), Sensor Multilevel (49), Meter (50), Thermostat Mode (64), Thermostat Setpoint (67), Door Lock (98), Battery (128). |
| Writes | Metadata-declared writable binary switch, level, lock mode, thermostat mode and thermostat setpoint, with parent-side checks, sidecar metadata re-resolution, and confirmed-success result handling. Generic `set_value` remains internal and unadvertised. |
| Maintenance | Ping, refresh node values, supported `refreshInfo()` re-interview, and reconnect driver. |
| Events/recovery | Bounded sequenced replay, stream IDs, drop counters, snapshot reconciliation after gaps/restarts, parent polling backoff and sidecar driver-error restart scheduling. |
| Diagnostics | Controller lifecycle/readiness, redacted path/Home ID suffix, node counts, queue depth/capacity/drop count, reconnect count and last error code. |
| Administration | Confirmed, serialized and time-bounded S2/DSK inclusion, exclusion, failed-node removal/replacement, and digest/identity-checked NVM backup/restore with rollback. |

### Not supported or not proven

- SmartStart provisioning, QR workflows, S0 commissioning, or physical S2/security-class qualification.
- Z-Wave Long Range network administration.
- Network healing/routes; RF region; associations; configuration parameters; controller/node statistics.
- Firmware update, controller migration, NVM format migration, or hardware-proven disaster recovery.
- Broad Home Assistant platform semantics, dynamic discovery parity, repairs, translations, device/state classes, or every value type Z-Wave JS can expose.
- Hardware-proven node replacement/node-ID reuse behavior or controller migration identity semantics.
- Multiple controllers, remote Z-Wave JS servers or a general arbitrary Z-Wave API.
- Real controller, real device, RF, security, sleeping-node, Long Range, firmware or migration interoperability evidence.
- Any Home Assistant IQS tier or formal parity claim.

## Home Assistant Integration Quality Scale assessment

The current IQS contains 54 cumulative rules: 20 Bronze, 10 Silver, 21 Gold and 3 Platinum. A Home Assistant integration must satisfy every rule at and below its tier; claims are recorded in `quality_scale.yaml` and reviewed through Home Assistant's process.[HA-IQS][HA-IQS-RULES] PiPhi is not an HA integration, so the assessment below is an analogy, not a badge. Current HA Z-Wave JS itself has neither a `quality_scale` field in its `2026.11.1` manifest nor a `quality_scale.yaml`; historical labels should not be presented as its current formal tier.[HA-MANIFEST][HA-CORE]

| IQS level | Analogous PiPhi evidence | Assessment |
|---|---|---|
| **Bronze** | UI schema, manifests, authenticated setup/removal, durable hashed identity, transactional readiness, restart restoration, tests and basic docs.[P-DISCOVERY][P-MANIFEST][P-STATE][P-TESTS] | **No formal equivalence claim.** The prior software blockers are closed, but there is no PiPhi-to-IQS rule ledger or physical install/removal qualification. |
| **Silver** | Bounded retry/recovery, transactional replacement, redaction/auth tests, and maintainer metadata.[P-STATE][S-STATE][P-MANIFEST] | **Does not meet Silver equivalence.** No measured >95% coverage or real serial/controller recovery and device lifecycle evidence. |
| **Gold** | Snapshot/replay observability, metadata-based models and selected redaction.[P-STATE][P-MODEL][S-TRANSPORT] | **Does not meet Gold equivalence.** No discovery/commissioning product, repairs, translations, robust device lifecycle, downloadable diagnostics, complete reconfigure flow, field-tested device matrix, firmware or backup/migration UX. |
| **Platinum** | Parent and sidecar use async application control flow; blocking protocol work is delegated to Z-Wave JS.[P-STATE][S-DRIVER] | **Does not meet Platinum equivalence.** Lower tiers are unmet; no analogous strict typing/coverage evidence across the delivery boundary, shared-client/resource rule ledger, or mature dependency/lifecycle proof. |

## Safety invariants to preserve and strengthen

1. **One owner per controller.** Keep a single sidecar process and exclusive logical ownership for each physical adapter; reject aliases to an already-owned canonical device.
2. **No arbitrary Z-Wave API.** Preserve named, reviewed commands. Do not expose raw serial frames, arbitrary command-class calls, controller reset or unrestricted `setValue` to normal automation callers.
3. **Writes must remain metadata-authorized.** Continue re-resolving the value ID against current node metadata and reject non-writeable, secret, missing, out-of-range or unknown-state values.
4. **Protocol acceptance is not command success.** Inspect `SetValueResult.status`; only success may emit a completion event. Preserve structured non-success/uncertain outcomes and reconcile observed state without falsely claiming completion.[ZWAVE-NODE]
5. **Do not blindly retry writes.** A timeout can leave the RF outcome unknown. Surface uncertainty and refresh state; never duplicate a lock, setpoint or actuator command merely because transport acknowledgement was lost.
6. **Commissioning is administrator-only and physical-presence-sensitive.** Future inclusion/exclusion, DSK, SmartStart, failed-node and reset flows require explicit authorization, bounded sessions, audit events and cancellation/recovery semantics.
7. **Secrets never enter normal state/events.** Preserve exclusion of network keys, full DSKs, raw NVM and raw frames; add tests covering every snapshot, event, diagnostic and error path.
8. **Stable identity includes the network.** Use controller Home ID plus durable node/device identity. Never let a reused node ID silently inherit the removed device's state, permissions or automation identity.
9. **Snapshots are authoritative after replay uncertainty.** Preserve stream ID, sequence and drop detection; clear/reconcile removed values and nodes explicitly after resync.
10. **Sleeping is not dead.** Availability, refresh, queue timeout and repairs must respect sleeping-node behavior and avoid wake-up storms.
11. **Configuration changes are transactional.** Validate canonical adapter identity, open/start a candidate, confirm controller Home ID and compatibility, then swap. On failure retain the previous known-working session and parent model.
12. **Least privilege at every hop.** Authenticate all management/state routes except narrowly defined liveness, bind services privately, use constant-time token comparison, and map only the chosen serial device.
13. **Backups precede destructive administration.** Do not expose controller reset, migration, NVM restore or mass exclusion until backup format, compatibility, encryption, confirmation and rollback behavior are proven.
14. **Upstream capability is never an implicit product claim.** Every exposed feature needs a PiPhi API, failure model, test evidence, operator documentation and qualification scope.

## Prioritized concrete next work

### Closed in v0.4.0 software gates (formerly P0)

Items 1–7 below are retained as the audit trail; the coordinated v0.4.0 source and deterministic tests implement them. Their physical-controller aspects remain part of P1 qualification.

1. **Fix command truthfulness.** Decode `SetValueResult`; reject every non-success status with a stable error code; represent timeout/unknown separately; emit completion only on actual success; add tests for `EndpointNotFound`, `NotImplemented`, `InvalidValue`, timeout and success.[ZWAVE-NODE]
2. **Fix the interview command.** Replace `node.interview()` with the supported `refreshInfo()` behavior (or deliberately configure and document manual interviews), verify progress/error semantics, and test with the exact pinned Z-Wave JS API.[ZWAVE-NODE]
3. **Close authorization gaps.** Protect sidecar config/sync/deconfigure/state/entities/diagnostics and all operational routes; protect both parent deconfigure routes and sensitive reads. Add route-enumeration tests proving anonymous callers can do no mutation or data extraction. Leave only `/health` public if required.
4. **Bind durable identity.** Carry full Home ID internally from sidecar snapshot to parent identity; combine it with node/device identity and endpoint; detect node replacement and stale entity removal. Do not use literal `primary` as network identity.
5. **Implement restart restoration.** Define and test Core-to-parent config replay, parent-to-sidecar reapply, sidecar restart, parent restart and simultaneous restart. Fail visibly if restoration cannot establish the expected Home ID.
6. **Make setup/reconfigure atomic end-to-end.** Do not record `zwave.config.applied` when initial sidecar synchronization fails. Stage and verify the candidate controller before stopping/replacing the parent supervisor or previous working model.
7. **Restrict serial access.** Map only an approved stable adapter path, canonicalize/validate it, detect duplicate physical ownership, and test unplug/replug and descriptor replacement.

### P1 — defensible quality baseline

8. **Build a hardware qualification rig.** Test at least representative mains, sleeping battery, switch/dimmer, sensor, lock and thermostat devices across documented controllers; include restart, RF loss, interview, failed writes and node removal/reuse. Publish exact firmware/controller/device evidence.
9. **Add measurable gates.** Enforce clean-checkout tests, strict TypeScript and Python typing, per-module coverage (over 95% if targeting Silver analogy), dependency audit policy, container smoke tests and a parent↔real-sidecar contract test. The audit environment lacked `piphi_runtime_testkit_python`, `tsx` and `tsc`; make bootstrap deterministic.
10. **Harden recovery and queues.** Prove driver restart after serial errors, preserve/expire queued commands safely, distinguish sleeping-node delay from failure, bound snapshot/event payloads, and soak-test replay gaps, event storms and controller flapping.
11. **Deliver authenticated support diagnostics.** Produce a downloadable redacted bundle with release/config provenance, Home ID pseudonym, adapter pseudonym, queue/replay health, node status and actionable errors; add full-output secret/path tests and repair links.
12. **Finish operator documentation.** Document supported controllers/devices/command classes, setup, ownership, reconfigure/remove, restart behavior, backups (currently absent), security/privacy, sleeping nodes, troubleshooting, known defects and exact unsupported features.

### P2 — demand-driven product breadth

13. Implement administrator-only inclusion/exclusion first, including explicit S2 grants, DSK verification, SmartStart lifecycle, cancellation, audit and recovery; qualify with real hardware before advertising discovery.
14. Add failed-node removal/replacement, associations and configuration parameters with guardrails and device-specific tests.
15. Add route/statistics/RF-region and Long Range administration only where controller capability and regional safety can be proven.
16. Add signed/validated firmware workflows with progress, wake-up handling, failure recovery and version reconciliation.
17. Add encrypted NVM backup/restore and controller migration with adapter/version compatibility checks, confirmation and disaster-recovery drills.
18. Expand semantic models/platform behavior from demonstrated devices and command classes, not from the raw breadth of Z-Wave JS.

## Audit execution note

The source and committed test suites were inspected. A fresh local test run could not be completed in the existing environment: `pdm run pytest -q` stopped before collection because `piphi_runtime_testkit_python` was not installed; `npm test` could not find `tsx`; and `npm run check` could not find `tsc`. `npm audit --omit=dev --audit-level=high` completed with three moderate `minimatch` findings and no high-severity failure. These environment results neither invalidate committed tests nor count as a green verification run.

## Primary sources

### Home Assistant and its first-party Z-Wave stack

- **[HA-DOC]** Home Assistant, [Z-Wave integration documentation](https://www.home-assistant.io/integrations/zwave_js/).
- **[HA-CORE]** Home Assistant Core, [Z-Wave JS component at `2026.11.1`](https://github.com/home-assistant/core/tree/2026.11.1/homeassistant/components/zwave_js).
- **[HA-TESTS]** Home Assistant Core, [Z-Wave JS tests at `2026.11.1`](https://github.com/home-assistant/core/tree/2026.11.1/tests/components/zwave_js).
- **[HA-MANIFEST]** Home Assistant Core, [`manifest.json` at `2026.11.1`](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/zwave_js/manifest.json).
- **[HA-INIT]** Home Assistant Core, [`__init__.py` at `2026.11.1`](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/zwave_js/__init__.py).
- **[HA-CONFIG]** Home Assistant Core, [`config_flow.py` at `2026.11.1`](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/zwave_js/config_flow.py).
- **[HA-DIAGNOSTICS]** Home Assistant Core, [`diagnostics.py` at `2026.11.1`](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/zwave_js/diagnostics.py).
- **[HA-ENTITY]** Home Assistant Core, [`entity.py` at `2026.11.1`](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/zwave_js/entity.py).
- **[HA-SERVICES]** Home Assistant Core, [`services.yaml` at `2026.11.1`](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/zwave_js/services.yaml).
- **[HA-PYTHON]** Home Assistant Libraries, [`zwave-js-server-python`](https://github.com/home-assistant-libs/zwave-js-server-python).
- **[HA-IQS]** Home Assistant developer documentation, [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
- **[HA-IQS-RULES]** Home Assistant developer documentation, [all Integration Quality Scale rules](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/).

### Z-Wave JS upstream

- **[ZWAVE-NODE]** Z-Wave JS, [`Node.ts` at `v15.32.3`](https://github.com/zwave-js/zwave-js/blob/v15.32.3/packages/zwave-js/src/lib/node/Node.ts) — `interview()`/`refreshInfo()` behavior and `setValue()`/`SetValueResult` statuses.
- **[ZWAVE-SERVER-SCHEMA]** Z-Wave JS Server, [API schema at `3.12.0`](https://github.com/zwave-js/zwave-js-server/blob/3.12.0/API_SCHEMA.md).
- **[ZWAVE-SERVER-README]** Z-Wave JS Server, [README at `3.12.0`](https://github.com/zwave-js/zwave-js-server/blob/3.12.0/README.md).

### PiPhi repository evidence

Parent integration:

- **[P-README]** [README](../README.md)
- **[P-MANIFEST]** [manifest](../manifest.json)
- **[P-CATALOG]** [capability catalog](../capability-catalog.json)
- **[P-DOCKER]** [Dockerfile](../Dockerfile)
- **[P-LIFECYCLE]** [runtime lifecycle](../src/piphi_network_zwave/lifecycle.py)
- **[P-STATE]** [supervisor, replay, state and commands](../src/piphi_network_zwave/state.py)
- **[P-MODEL]** [command-class normalization, identity and write policy](../src/piphi_network_zwave/zwave_model.py)
- **[P-SCHEMA]** [configuration schema](../src/piphi_network_zwave/schemas.py)
- **[P-SIDECAR]** [sidecar client](../src/piphi_network_zwave/sidecar_client.py)
- **[P-AUTH]** [runtime authorization](../src/piphi_network_zwave/runtime_auth.py)
- **[P-CONFIG]** [configuration/deconfiguration routes](../src/piphi_network_zwave/routes/config.py)
- **[P-HEALTH]** [health and diagnostics routes](../src/piphi_network_zwave/routes/health.py)
- **[P-DISCOVERY]** [discovery/UI schema routes](../src/piphi_network_zwave/routes/discovery.py)
- **[P-CONTRACT]** [generated contract](contract.md)
- **[P-TESTS]** [tests](../tests/)

Sidecar:

- **[S-README]** [README](../../../services/piphi-zwave-js-sidecar/README.md)
- **[S-MANIFEST]** [manifest](../../../services/piphi-zwave-js-sidecar/manifest.json)
- **[S-CATALOG]** [capability catalog](../../../services/piphi-zwave-js-sidecar/capability-catalog.json)
- **[S-PACKAGE]** [`package.json`](../../../services/piphi-zwave-js-sidecar/package.json) and [`package-lock.json`](../../../services/piphi-zwave-js-sidecar/package-lock.json)
- **[S-DOCKER]** [Dockerfile](../../../services/piphi-zwave-js-sidecar/Dockerfile)
- **[S-DRIVER]** [Z-Wave JS driver session](../../../services/piphi-zwave-js-sidecar/src/driver-session.ts)
- **[S-STATE]** [configuration transaction, queues, snapshot and command completion](../../../services/piphi-zwave-js-sidecar/src/state.ts)
- **[S-TRANSPORT]** [bounded replay, command queue and sanitization](../../../services/piphi-zwave-js-sidecar/src/transport.ts)
- **[S-AUTH]** [sidecar authorization boundary](../../../services/piphi-zwave-js-sidecar/src/authorization.ts)
- **[S-CONFIG]** [sidecar configuration routes](../../../services/piphi-zwave-js-sidecar/src/routes/config.ts)
- **[S-SCHEMA]** [sidecar types/config contract](../../../services/piphi-zwave-js-sidecar/src/types.ts)
- **[S-CONTRACT]** [generated contract](../../../services/piphi-zwave-js-sidecar/docs/contract.md)
- **[S-TESTS]** [tests](../../../services/piphi-zwave-js-sidecar/tests/)

Repository CI/release:

- **[CI]** [application CI](../../../../.github/workflows/apps-ci.yml) and [reusable application CI](../../../../.github/workflows/reusable-app-ci.yml)
- **[RELEASE-CI]** [application release workflow](../../../../.github/workflows/release-app.yml)
