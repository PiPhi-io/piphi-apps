# PiPhi Zigbee delivery-stack quality comparison

**Research cutoff:** 2026-11-15

**PiPhi revision audited:** [`8c69c0d`](https://github.com/PiPhi-io/piphi-apps/tree/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652)
**Scope:** `apps/integrations/piphi-network-zigbee` 0.1.10 and `apps/services/piphi-network-zigbee2mqtt` 0.1.18, assessed as one delivery stack.

## Executive conclusion

The stack has a useful **early supported slice**, but it is not yet safe to describe as a general-purpose, production-complete Zigbee integration. It can detect likely serial coordinators, render and atomically write a narrow Zigbee2MQTT configuration, supervise an upstream Zigbee2MQTT process, list retained devices, time-bound permit-join, scan a network map, import a device by IEEE address, subscribe to basic state/availability, and publish four generic commands. Those paths have meaningful unit tests.

The comparison is deliberately **not a parity claim**. Home Assistant ZHA directly owns one coordinator and implements the Zigbee application model through `zha`/`zigpy`; PiPhi owns a Zigbee2MQTT process and translates an MQTT contract. The appropriate upstream behavioral authority for PiPhi is therefore Zigbee2MQTT, while ZHA is an analogical benchmark for onboarding, recovery, diagnostics, identity, entity quality, and safety UX. ZHA itself documents that a coordinator must not be used by another application, and Zigbee2MQTT states the same single-owner invariant ([HA docs](https://github.com/home-assistant/home-assistant.io/blob/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f/source/_integrations/zha.markdown#troubleshooting), [Z2M FAQ](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/faq/README.md#general-limitations-that-apply-to-all-zigbee-implementations)).

**Release recommendation: do not represent the stack as production-ready until the P0 boundary issues are closed.** Most importantly:

1. the privileged sidecar exposes coordinator configuration, process control, arbitrary config paths, MQTT credentials, and Docker-socket-backed operations without route-level authorization;
2. `mqtts://` selects port 8883 but neither PiPhi MQTT client enables TLS, while the UI/config model cannot carry Zigbee2MQTT CA/client-certificate settings;
3. PiPhi computes interview/coordinator import eligibility in the sidecar but does not enforce it when integration discovery imports the retained device list;
4. there is no coordinator ownership claim/lock, Zigbee network backup/restore or migration workflow, or safe network-key lifecycle.

### Post-audit remediation status

The 0.1.11 integration / 0.1.19 sidecar release closes three findings from the
audited revision: production sidecar deployments now fail closed unless Core
supplies a valid bearer token, `mqtts://` uses certificate and hostname
verification in both PiPhi MQTT clients and the broker health check, and device
discovery rejects coordinators plus unsupported or incomplete interviews. The
remaining P0 ownership, host-privilege, network-secret, backup, and migration
work still blocks a production-ready or HA Bronze-equivalent claim.

The 0.1.20 sidecar release adds persistent, atomic coordinator claims keyed by
Core's stable adapter identity; explicit reuse/form-new semantics; exact
network-key and extended-PAN validation; secret-redacted API serialization;
private configuration and backup files; a checksummed network-data backup; and
a verified-backup gate before PAN, extended-PAN, or network-key changes. It also
allowlists managed Docker/PM2 images, names, paths, environment, and network
mode. The listing remains unrated because an actual adapter in-use probe,
Docker-socket/root privilege removal, encrypted export and tested restore, and
guided coordinator migration are still outstanding.

The 0.1.21 sidecar release adds an OS-level in-use probe before a newly claimed
serial coordinator is configured. Linux checks `/proc` file descriptors for an
already-open radio and reports the holding process; proxy platforms use an
exclusive serial open, while network coordinators receive a reachability probe
with an explicit warning that remote exclusivity cannot be proven. It also
captures bounded full-data backups with version/adapter compatibility metadata
and supports an explicitly confirmed, stopped-coordinator restore with an
automatic rollback backup. This closes the local-radio preflight and basic
restore gaps but does not remove the remaining privilege, encrypted export, or
guided migration blockers.

The 0.1.22 release candidate removes those three implementation blockers. Linux
sidecar deployment is non-root and no longer receives the Docker socket,
`/dev/bus/usb`, privileged mode, or any coordinator device. Core's existing
authenticated managed-runtime helper discovers read-only stable serial links,
validates the selected discovery identity, and maps only that coordinator into
the digest-pinned Zigbee2MQTT workload. Backups can be exported and imported in
an authenticated, passphrase-derived AES-256-GCM format. Coordinator migration
now has a deterministic plan/apply flow with compatibility validation, target
exclusivity probe, explicit confirmation, restore, retargeting, and automatic
rollback. Cross-family migration fails closed without an explicit evidence
reference. These changes justify closing the code-level P0 items, but **do not
justify a quality promotion**: representative USB coordinator discovery,
start/restart/unplug recovery, encrypted restore, and migration must pass on
released Core and sidecar artifacts first. The listing therefore remains
`unrated`.

The right near-term product claim is: **“PiPhi-managed Zigbee2MQTT bridge setup plus a tested basic MQTT device-state/control adapter for a constrained set of exposes.”**

## Comparison model and source baseline

- **ZHA baseline:** Home Assistant Core `4d270578` (manifest requires `zha==2.4.3` and `zha-quirks==2.4.1`) and Home Assistant documentation `8d777bfc`, both observed at the cutoff ([manifest](https://github.com/home-assistant/core/blob/4d27057851a312994f68c3064365c8b34f805183/homeassistant/components/zha/manifest.json), [docs](https://github.com/home-assistant/home-assistant.io/blob/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f/source/_integrations/zha.markdown)).
- **Zigbee2MQTT baseline:** owning-project docs at `c5763c30`; PiPhi pins its managed upstream container by digest, but does not record the human-readable Zigbee2MQTT version in its manifest or runtime diagnostics ([PiPhi manifest](https://github.com/PiPhi-io/piphi-apps/blob/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652/apps/services/piphi-network-zigbee2mqtt/src/manifest.json#L68-L75)).
- **IQS use:** this is an **analogical** application of Home Assistant's current quality dimensions, not an official score. ZHA has no `quality_scale.yaml` at the audited Core revision, and PiPhi is not a Home Assistant Core integration. HA defines Bronze through Platinum cumulatively and reserves special tiers for integrations not on that scale ([IQS definition](https://github.com/home-assistant/developers.home-assistant/blob/50b518898989b67bb76b69827f227aa6f0acd32a/docs/core/integration-quality-scale/index.md)).

## Honest supported slice

The following is reachable in the audited source and is suitable for a constrained claim:

- Linux container and Windows/macOS proxy metadata, with Docker or PM2 supervision plans; immutable upstream Zigbee2MQTT image digest in the sidecar manifest ([manifest](https://github.com/PiPhi-io/piphi-apps/blob/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652/apps/services/piphi-network-zigbee2mqtt/src/manifest.json#L15-L45), [supervisor](https://github.com/PiPhi-io/piphi-apps/blob/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652/apps/services/piphi-network-zigbee2mqtt/src/piphi_network_zigbee2mqtt/supervisor.py#L131-L218)).
- Serial enumeration and heuristic hints for `zstack`, `ember`, `deconz`, `zigate`, and `zboss`, preferring Linux stable symlinks when present ([detector](https://github.com/PiPhi-io/piphi-apps/blob/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652/apps/services/piphi-network-zigbee2mqtt/src/piphi_network_zigbee2mqtt/adapter_detector.py#L13-L76)). Detection is not qualification.
- Config render/write/apply for MQTT server/base topic, serial port/adapter/baudrate/LED, frontend, availability, channel/PAN/extended PAN/network key; changed-config restart policy and a TCP reachability check ([model](https://github.com/PiPhi-io/piphi-apps/blob/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652/apps/services/piphi-network-zigbee2mqtt/src/piphi_network_zigbee2mqtt/bridge_models.py#L43-L90), [apply](https://github.com/PiPhi-io/piphi-apps/blob/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652/apps/services/piphi-network-zigbee2mqtt/src/piphi_network_zigbee2mqtt/routes/bridge.py#L121-L185)).
- Retained `bridge/devices` inventory, transaction-correlated permit-join (1–254 seconds, optionally via a named device), and manual raw network-map requests ([MQTT bridge client](https://github.com/PiPhi-io/piphi-apps/blob/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652/apps/services/piphi-network-zigbee2mqtt/src/piphi_network_zigbee2mqtt/zigbee2mqtt_mqtt.py#L39-L138)). These conform to the owning project's documented topics ([Z2M MQTT API](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/usage/mqtt_topics_and_messages.md#zigbee2mqttbridgerequestpermit_join)).
- Stable PiPhi device identity prefers Zigbee IEEE address; friendly name is legacy/fallback identity. Exposes are flattened to a small capability vocabulary, with writable controls gated by Zigbee2MQTT expose access metadata ([normalizer](https://github.com/PiPhi-io/piphi-apps/blob/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652/apps/integrations/piphi-network-zigbee/src/piphi_network_zigbee/zigbee_devices.py#L128-L196)).
- Exact per-device state and availability subscriptions; state normalization for common sensors/safety signals; command publication for refresh, on/off/toggle, brightness, and color temperature ([runtime](https://github.com/PiPhi-io/piphi-apps/blob/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652/apps/integrations/piphi-network-zigbee/src/piphi_network_zigbee/mqtt_runtime.py#L235-L288)).
- Config-file writes use a temporary file replacement and retain one `.bak` copy of the prior YAML ([store](https://github.com/PiPhi-io/piphi-apps/blob/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652/apps/services/piphi-network-zigbee2mqtt/src/piphi_network_zigbee2mqtt/config_store.py#L9-L36)). This is config-write rollback material, **not** a Zigbee network backup.
- CI/release infrastructure supports per-app declared checks, multi-architecture OCI publication, SBOM, provenance, and attestations ([CI declaration](https://github.com/PiPhi-io/piphi-apps/blob/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652/apps/services/piphi-network-zigbee2mqtt/piphi-app.json#L14-L23), [release workflow](https://github.com/PiPhi-io/piphi-apps/blob/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652/.github/workflows/release-app.yml#L138-L157)).

## Evidence table

| Area | Reachable PiPhi behavior | Owning-project / ZHA benchmark | Assessment |
|---|---|---|---|
| Architecture and ownership | Sidecar starts Zigbee2MQTT; integration talks to sidecar for inventory and directly to MQTT for device traffic. No direct Zigbee stack exists in PiPhi. | ZHA is a direct `zigpy` coordinator integration and single-instance hub; Z2M is a single-coordinator bridge whose API is MQTT ([ZHA manifest](https://github.com/home-assistant/core/blob/4d27057851a312994f68c3064365c8b34f805183/homeassistant/components/zha/manifest.json), [Z2M topics](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/usage/mqtt_topics_and_messages.md)). | Correct high-level layering, but no coordinator lease, in-use probe, duplicate-instance prevention, or explicit handoff. Never run ZHA and this stack against the same radio. |
| Hardware discovery / qualification | Enumerates serial ports and guesses stack from strings; broad manifest choices include maintained, unmaintained, and experimental adapter families. Network coordinator discovery is metadata/manual config, not implemented mDNS qualification. | ZHA has explicit USB and Zeroconf match tables and probes the radio; Z2M labels zStack/Ember/deCONZ recommended, ZiGate unmaintained, ZBOSS experimental ([ZHA config flow](https://github.com/home-assistant/core/blob/4d27057851a312994f68c3064365c8b34f805183/homeassistant/components/zha/config_flow.py#L175-L258), [Z2M adapters](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/adapters/README.md)). | **Gap.** Heuristic confidence is not a tested hardware matrix; PiPhi exposes unsupported confidence through UX without warnings. |
| Coordinator setup | Can render serial and advanced network settings and supervise Docker/PM2. | ZHA probes, verifies/deprecates radio types, forms or reuses network settings, and detects duplicate/moved ports ([flow](https://github.com/home-assistant/core/blob/4d27057851a312994f68c3064365c8b34f805183/homeassistant/components/zha/config_flow.py#L175-L395)). | **Partial.** PiPhi does not verify that the selected adapter actually speaks the selected protocol before committing configuration. |
| Permit-join / interview | Time-bounded permit-join with optional router/coordinator target. Sidecar derives `import_eligible=false` for coordinator, unsupported, failed, and in-progress interviews. | Z2M publishes current `interview_state`, device join/interview events, manual re-interview, and secure install-code APIs ([topics](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/usage/mqtt_topics_and_messages.md#zigbee2mqttbridgeevent)). | **Critical integration break:** discovery normalizes every returned object and drops/ignores `import_eligible`, so coordinator/incomplete/unsupported entries can still be offered. No interview progress/event stream, retry, install code, or close-join-on-error UX. |
| Device identity | IEEE address is primary; normalized IEEE becomes device/config ID; friendly name fallback remains. | Z2M device topics are friendly-name based, while retained inventory includes IEEE and interview status; ZHA models devices/endpoints around IEEE and endpoint identity. | **Good base, fragile routing.** A rename changes the MQTT topic but PiPhi has no rename-event reconciliation. Friendly-name fallback and normalization can collide. |
| Endpoint and entity mapping | One PiPhi `zigbee_device` entity per physical device. Nested expose features are flattened; only first metadata record per capability survives. Endpoint is metadata only. | Z2M documents endpoint-specific exposes and request targeting; ZHA exposes many typed HA domains and endpoint-aware device signatures ([Z2M topics](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/usage/mqtt_topics_and_messages.md#exposesoptions), [ZHA supported domains](https://github.com/home-assistant/home-assistant.io/blob/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f/source/_integrations/zha.markdown#L14-L34)). | **Large behavior gap.** Multi-endpoint switches/lights and repeated properties collapse; enum, color, thermostat, fan, lock, valve, siren, groups, scenes, binding, options, and many compound exposes are not represented. |
| Commands | MQTT publish for `state`, `brightness`, `color_temp`; `/get` refresh. Access flags gate controls when expose metadata is present. | Z2M defines commands per device expose and allows endpoint-aware operations. ZHA exposes domain-native services/entities. | **Narrow slice.** Publish success is treated as command success; no device/bridge acknowledgement, endpoint selector, min/max enforcement, transition/color/cover commands, or error correlation. Brightness clamp hides invalid input. |
| MQTT topics | Per-entry server/base topic and derived friendly-name topic; exact state and availability subscriptions. | Z2M allows `/` in friendly names and defines retained inventory/availability plus bridge state/info/health/event topics ([topics](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/usage/mqtt_topics_and_messages.md#zigbee2mqttfriendly_name)). | **Gap.** No topic grammar/wildcard validation, ACL model, bridge online/offline subscription, inventory-change subscription, or atomic rename handling. Separate integration and sidecar clients duplicate credentials and connection policy. |
| MQTT authentication / TLS | Username/password in URL or sidecar fields; password omitted from snapshots and some process output is redacted. | Z2M supports `mqtts://`, CA, client key/cert, hostname verification, client ID, protocol/QoS/retention settings, and secret-file indirection ([MQTT config](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/configuration/mqtt.md)). | **P0.** PiPhi maps `mqtts://` to 8883 but never calls Paho TLS setup. Config cannot carry CA/client cert or verification policy. `/v1/config/*` responses include rendered YAML (including password). No least-privilege topic ACL contract is documented/tested. |
| Network keys | Renderer accepts optional PAN ID, extended PAN ID, channel, and network key or `GENERATE`. | Z2M documents that changing network key/PAN ID requires repairing devices; network details live in coordinator and data directory ([FAQ](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/faq/README.md#what-does-and-does-not-require-re-pairing-of-all-devices)). ZHA diagnostics redact network keys and extended PAN IDs ([diagnostics](https://github.com/home-assistant/core/blob/4d27057851a312994f68c3064365c8b34f805183/homeassistant/components/zha/diagnostics.py#L27-L37)). | **P0/P1.** No exact 16-byte/range validation, generation ceremony, secret-at-rest design, read redaction, destructive-change confirmation, or key rotation/migration policy. Render/apply echoes the key and MQTT password. |
| Backup / restore | One overwritten `.bak` for `configuration.yaml`; persistent Z2M data volume. No API to request/export/import/verify a Z2M data backup. | Z2M has `bridge/request/backup`; coordinator backups are supported only for zStack and Ember. Moving an instance requires the whole data directory. ZHA performs automatic/manual network backups and guided restore ([Z2M API](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/usage/mqtt_topics_and_messages.md#zigbee2mqttbridgerequestbackup), [ZHA docs](https://github.com/home-assistant/home-assistant.io/blob/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f/source/_integrations/zha.markdown#backups-and-migration)). | **Major gap.** A YAML backup is not network recovery. No schedule, encryption, download, restore drill, compatibility check, or failure rollback. |
| Migration | Serial path can be changed and process restarted; this is not a coordinator migration workflow. | Z2M limits supported coordinator backup/restore and warns cross-family migration may require repair; ZHA backs up, resets old radio, restores chosen backup, handles IEEE overwrite, and reports progress/errors ([Z2M FAQ](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/faq/README.md#how-do-i-migrate-from-one-adapter-to-another), [ZHA flow](https://github.com/home-assistant/core/blob/4d27057851a312994f68c3064365c8b34f805183/homeassistant/components/zha/config_flow.py#L396-L641)). | **Absent.** PiPhi must not imply changing `serial.port` is safe migration. |
| OTA | Upstream Z2M may perform OTA, but PiPhi exposes no OTA capability, status, check/update/abort/schedule API, or safety UX. | Z2M provides update state/progress and explicit check/update/abort/schedule/downgrade topics with congestion/bricking warnings; ZHA uses Update entities and warnings ([Z2M OTA](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/usage/ota_updates.md), [ZHA docs](https://github.com/home-assistant/home-assistant.io/blob/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f/source/_integrations/zha.markdown#ota-updates-of-zigbee-device-firmware)). | **Absent at PiPhi boundary.** Do not claim OTA support merely because upstream has it. |
| Availability | Enables Z2M availability and subscribes to per-device retained availability. Initial config state is set `connected=true`, `availability=true`; any device payload sets `connected=true`. | Z2M uses different active/passive timeouts and retained availability; ZHA exposes configurable mains/battery unavailable windows ([Z2M availability](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/configuration/device-availability.md), [ZHA options](https://github.com/home-assistant/home-assistant.io/blob/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f/source/_integrations/zha.markdown#global-options)). | **Partial and misleading on startup.** Broker/bridge/device status are conflated. No stale-state timestamp, bridge last-will handling, backoff visibility, or once-off recovery logging. |
| Recovery | MQTT subscriber requests Paho reconnect delay and Docker uses `unless-stopped`; apply can restart. | HA Silver emphasizes automatic recovery without log flooding; Z2M exposes bridge state/health and coordinator checks. | **Partial.** No on-disconnect state transition, supervised retry state machine, coordinator health request, missing-router check, startup restoration of sidecar state, or repair guidance. |
| Diagnostics / privacy | Basic active IDs/counts; sidecar snapshot, adapter path, supervisor status; MQTT URL serializer strips userinfo; supervisor output redacts common secret patterns. | ZHA includes versions, redacted config/network/application state, device model summaries, and energy scan, explicitly redacting IEEE, keys, PAN identity, and alarm code ([diagnostics](https://github.com/home-assistant/core/blob/4d27057851a312994f68c3064365c8b34f805183/homeassistant/components/zha/diagnostics.py)). | **Below useful supportability.** No Z2M version/commit, adapter firmware, bridge state/health, channel/PAN-safe summary, queue/reconnect counters, last seen, or downloadable per-device diagnostics. Sensitive device inventory/raw payloads appear in runtime state/events, while render/apply can return secrets. No retention/privacy statement. |
| API privilege boundary | Sidecar runs as root, is declared privileged, mounts `/dev/bus/usb`, RW data, and RW Docker socket; bridge routes have no visible auth dependency. Caller chooses config path, Docker image/name/mount/device/network/env, PM2 path/script/env. | Neither ZHA nor Z2M docs justify exposing an unauthenticated orchestration API. | **P0.** If reachable by an untrusted client, this is host-control capability. Core ingress metadata is not route authorization. Require authenticated authorization, fixed allowlisted paths/images/actions, and removal or mediation of Docker socket/root privilege. |
| CI / release | Sidecar: install/check, audit, Ruff, validate, tests, container build. Integration: install/check and tests only; container build disabled despite OCI artifact. Release can emit SBOM/provenance. | HA quality guidance expects tested config flows, high coverage, diagnostics, documentation, owner, typing, and robust offline handling. | **Uneven.** Integration omits lint, audit, validator, coverage gate, and container build. This audit repaired its stale release-workflow test to inspect the monorepo release path and current OCI evidence gates. The base image in the integration Dockerfile remains unpinned. |

## Feature and behavior gaps

### Coordinator and network lifecycle

- No exclusive ownership record keyed by stable USB identity/network coordinator address; no probe for an already-open radio; no guided stop/claim/handoff.
- No verified form-new/reuse-existing distinction. Rendering configuration can silently create or alter a network according to upstream defaults.
- No backup request, encrypted export, restore validation, restore execution, scheduled backup, compatibility matrix, or recovery drill.
- No supported migration state machine. Adapter family, coordinator IEEE, network data, and device rejoin implications are not validated.
- No network-key secret lifecycle or destructive-change guard.

### Pairing, interview, and inventory

- Eligibility is calculated but not enforced across the sidecar-to-integration seam.
- No bridge event subscription, dynamic add/remove/rename reconciliation, interview progress, interview retry, device removal, or secure install-code flow.
- Permit-join is time-bounded, but there is no authorization/confirmation/audit policy commensurate with opening a security boundary and no guaranteed close in cleanup/error paths.

### Devices, endpoints, and commands

- One generic entity collapses endpoint-specific and repeated exposes. It does not model Zigbee2MQTT groups/scenes/bindings.
- Only a fixed property map is retained; unknown exposes disappear as capabilities even when upstream supports them.
- Commands are not endpoint-aware and do not validate expose ranges/enum values beyond three hand-written converters.
- MQTT delivery is not Zigbee command completion. There is no response correlation or command state convergence.
- Friendly-name changes and topic hierarchy changes are not reconciled while IEEE identity remains stable.

### Operations, security, and privacy

- MQTT TLS is functionally absent despite accepting `mqtts://`; mutual TLS and certificate validation configuration are absent.
- Broker authorization boundaries are undefined. At minimum, the integration should get only required per-device read/write topics and the sidecar only required bridge topics; credentials should not be shared or embedded in URLs.
- Sidecar orchestration is over-privileged and unauthenticated in source. Render/apply responses expose secrets.
- Diagnostics lack actionable bridge/radio/software evidence and explicit redaction tests; runtime events retain full raw Zigbee payloads with no documented bounds/retention.
- No hardware qualification table ties PiPhi version + Zigbee2MQTT version/digest + adapter model/firmware + OS/runtime + tested backup/migration outcome.

## Analogical Home Assistant IQS assessment

This assessment uses the [current HA IQS characteristics](https://github.com/home-assistant/developers.home-assistant/blob/50b518898989b67bb76b69827f227aa6f0acd32a/docs/core/integration-quality-scale/index.md) as review prompts only.

| Tier | Analogical result for the combined stack | Why |
|---|---|---|
| Bronze | **Not demonstrated** | There is UI-contract metadata, ownership metadata, docs, and a passing mocked test suite, but the end-to-end setup does not test/claim the coordinator before configuration, discovery admits ineligible devices, and critical orchestration routes lack an enforced trust boundary. |
| Silver | **Not demonstrated** | Some MQTT reconnect and supervisor behavior exists, but offline/online semantics, auth recovery, safe credential handling, automatic bridge/device recovery, and detailed troubleshooting are incomplete. No coverage threshold is enforced. |
| Gold | **Not demonstrated** | Discovery and basic diagnostics exist, but typed/dynamic entities, endpoint fidelity, reconfiguration/repairs, stale-device handling, OTA, comprehensive supported-function docs, hardware qualification, and downloadable privacy-safe diagnostics are absent. |
| Platinum | **Not demonstrated** | Code has type hints but no strict-type gate; synchronous Paho operations are moved to threads rather than using one fully async shared client; duplicated short-lived clients and one subscriber per server are not an efficiency claim. |

Positive foundations worth preserving are stable IEEE-first identity, expose access gating, request/response transaction IDs, bounded network-map parsing, atomic config replacement, secret-pattern redaction, immutable upstream image digest, and supply-chain attestations.

## Safety invariants

These should be executable tests and product constraints, not just documentation:

1. **Exactly one owner per coordinator.** PiPhi must not start or reconfigure Zigbee2MQTT until it has a stable coordinator identity and exclusive claim; it must reject a radio in use by ZHA, another Z2M instance, or another process.
2. **No coordinator means no mutation.** Detection and read-only checks precede config write, network formation, permit-join, reset, restore, or restart.
3. **Pairing is explicit, authenticated, scoped, and bounded.** Default closed; maximum duration enforced; optional join-via target validated; every open/close audited; failure attempts to close; coordinator/unsupported/incomplete devices never become normal entities.
4. **IEEE address is physical identity; friendly name is routing metadata.** Rename must update topics atomically without duplicating or replacing the PiPhi device. Identity collisions fail closed.
5. **Endpoint identity is never discarded when it changes semantics.** Repeated properties on different endpoints cannot collapse into one actuator or command target.
6. **MQTT transport claims are truthful.** `mqtts://` must perform certificate-validated TLS; otherwise it must be rejected. Credentials never appear in URLs, API responses, logs, diagnostics, events, or generated artifacts beyond the protected Z2M secret/config store.
7. **Least-privilege topics.** Integration and sidecar use separate broker principals and allowlists; wildcard/base-topic changes cannot escape the assigned namespace.
8. **Publishing is not actuation success.** Commands distinguish broker acceptance, Z2M response, device acknowledgement/state convergence, timeout, and retryability.
9. **Availability has layers.** Broker, Zigbee2MQTT bridge, coordinator, and device availability are separate; startup is unknown until evidence arrives; stale retained state carries source timestamp.
10. **Network secrets are generated, validated, and recoverable.** A new network gets a cryptographically generated supported key; existing keys are never regenerated accidentally; key/PAN/channel changes require backup and explicit destructive confirmation.
11. **Backup before destructive change.** Verified, downloadable, encrypted backup of the full Z2M data set and supported coordinator backup precedes migration/key/PAN/channel/radio changes. Restore is compatibility-checked and tested.
12. **Migration is a state machine, not a port edit.** Supported source/target pairs are allowlisted; old radio stop/reset and coordinator IEEE implications are explicit; rollback and re-pair guidance are preserved.
13. **OTA is opt-in and observable.** One device at a time by default, warnings shown, progress/abort/recovery supported, battery/network constraints exposed, and upstream firmware source identified.
14. **Sidecar cannot become arbitrary host control.** No unauthenticated bridge routes, caller-selected host paths/images/scripts/env, raw Docker socket, or unnecessary root/privileged mode. Every mutating operation is authorized and allowlisted.
15. **Diagnostics are useful and private.** Include version/digest, adapter model/firmware, bridge health/state, reconnect/error summaries, and redacted device diagnostics; redact keys, credentials, IEEE identifiers where exported, and user naming/location data by policy.
16. **Claims follow qualification.** A platform/adapter/feature is advertised only after automated contract tests and recorded hardware evidence for the exact upstream digest.

## Prioritized work

### P0 — release blockers

1. **Secure and reduce the sidecar boundary.** Add mandatory Core service authentication and operation-level authorization to every `/v1` mutation/read containing sensitive inventory; remove caller-controlled config paths, images, mounts, scripts, environment and network mode; mediate or eliminate Docker socket; run non-root and non-privileged where possible. Add negative authorization tests.
2. **Implement real MQTT security.** One shared connection policy with verified TLS for `mqtts://`, CA/client cert/server-name support, separate sidecar/integration principals, topic ACL documentation/tests, secret references instead of URL userinfo, and redaction of rendered config/API errors. Reject unsupported secure settings rather than downgrading silently.
3. **Enforce coordinator and interview eligibility end to end.** Filter coordinator, unsupported, failed, pending, and in-progress inventory before discovery; subscribe to bridge events and only import after successful supported interview. Add tests proving these objects cannot configure entities.
4. **Add coordinator ownership and safe setup.** Stable hardware identity, duplicate/in-use probe, exclusive lease, actual adapter protocol probe, explicit form/reuse decision, and failure-safe release. Document that the same coordinator cannot be shared with ZHA/another Z2M.
5. **Protect Zigbee network material.** Validate 16-byte key values/ranges and PAN identifiers; generate unique secrets for new networks; prevent secret echo; store with restrictive permissions; force verified backup plus explicit confirmation before network identity changes.
6. **Deliver backup/restore before migration claims.** Wrap Z2M backup API, capture the full persistent data directory, encrypt/export/verify it, expose compatibility, and implement a tested restore. Clearly label adapter backup support (currently zStack/Ember per owning docs).

### P1 — reliable supported product

1. Build an endpoint-aware entity mapper from the complete Zigbee2MQTT expose schema. Preserve unknown exposes, repeated endpoint properties, units/ranges/enums, and stable entity IDs. Add typed classes for the first qualified domains rather than claiming all Zigbee devices.
2. Replace publish-only commands with schema-driven endpoint-aware commands and correlated Z2M/device outcomes. Add rename/remove/re-interview/configure flows and dynamic inventory reconciliation.
3. Model broker, bridge, coordinator, and device health separately. Subscribe to bridge state/info/health/event, mark startup unknown, track last-seen/source timestamps, implement bounded reconnect/backoff, and expose repairs.
4. Implement a guided, compatibility-checked coordinator migration state machine with backup, stop/claim, restore, IEEE handling, rollback, and post-migration verification. Do not generalize ZHA's migration support to Z2M; follow Z2M's narrower adapter matrix.
5. Add privacy-safe downloadable diagnostics with PiPhi/upstream versions and digest, adapter firmware/model, redacted config, bridge health, recent bounded errors, and per-device interview/expose summary. Add redaction regression tests.
6. Establish hardware qualification: recommended/experimental/unsupported labels aligned to upstream, exact tested models/firmware/OS/runtime, USB and Ethernet cases, restore/migration evidence, and release gates. Remove broad unqualified choices from default UX.
7. Bring integration CI to sidecar baseline: validator, Ruff, dependency audit, coverage threshold, OCI build, and a pinned base image. Keep the repaired release-workflow test aligned with the monorepo release path.

### P2 — completeness and quality

1. Add groups, scenes, binding/unbinding, reporting configuration, install-code commissioning, network/channel guidance, topology interpretation, and coordinator checks through constrained APIs.
2. Surface Zigbee2MQTT OTA as a guarded PiPhi update model: availability, source/release notes, check, schedule, update, progress, abort, downgrade policy, post-update re-interview, and congestion/bricking warnings.
3. Add reconfigure/repair flows, translated errors and names, stale-device cleanup, entity categories/default-disabled noisy diagnostics, examples, known limitations, removal instructions, and recovery runbooks.
4. Consolidate MQTT sessions into an async, observable client layer with bounded queues, QoS policy, cancellation-safe lifecycle, and metrics; add strict typing and performance/soak tests.
5. Publish a versioned PiPhi↔Zigbee2MQTT compatibility matrix and automated contract suite against the pinned upstream image, including malformed/oversized retained payloads and broker disconnect/restart scenarios.

## Validation performed and limits

Original audit gates were executed from this checkout on 2026-11-15. The P0
release-candidate reassessment on 2026-11-16 additionally recorded:

- sidecar tests: **61 passed**;
- sidecar validator and Ruff: **passed**;
- production dependency audit: **no known vulnerabilities**;
- local AMD64 container build: **passed**;
- built container UID/GID and writable data check: **1000:1000, passed**;
- integration tests: **210 passed**;
- focused Core managed-runtime and Zigbee contract tests: **35 passed**;
- Core Compose managed-helper configuration render: **passed**.

Original audit results:

- integration `scripts/validate.py`: **passed**;
- sidecar `scripts/validate.py`: **passed**;
- sidecar `ruff check .`: **passed**;
- sidecar tests: **27 passed**;
- integration tests initially reported **207 passed, 1 failed** because `tests/test_release.py::test_release_pipeline_enforces_supply_chain_gates` still read a removed per-app `.github/workflows/release.yml`. The test was repaired during audit review to assert the monorepo OCI release, SBOM, provenance, evidence, proposal and GitHub-release gates. A subsequent isolated Python 3.12 run completed with **208 passed**.

No live MQTT broker, coordinator, Zigbee devices, PM2 host, Windows/macOS proxy,
hardware migration, RF behavior, or OTA target was available. Backup encryption,
restore, migration, rollback, and Docker supervision were exercised locally or
with mocks, but not against representative radios. Consequently this
reassessment verifies source, contracts, a local container build, and automated
failure behavior—not successful radio operation or hardware qualification.
Multi-architecture images and attestations remain release-workflow evidence.

## Primary source index

- [Audited PiPhi integration](https://github.com/PiPhi-io/piphi-apps/tree/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652/apps/integrations/piphi-network-zigbee)
- [Audited PiPhi sidecar](https://github.com/PiPhi-io/piphi-apps/tree/8c69c0d1715c2bdecdb2d5125e4eef2395cf4652/apps/services/piphi-network-zigbee2mqtt)
- [Home Assistant ZHA implementation](https://github.com/home-assistant/core/tree/4d27057851a312994f68c3064365c8b34f805183/homeassistant/components/zha) and [first-party ZHA documentation](https://github.com/home-assistant/home-assistant.io/blob/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f/source/_integrations/zha.markdown)
- [Home Assistant Integration Quality Scale](https://github.com/home-assistant/developers.home-assistant/blob/50b518898989b67bb76b69827f227aa6f0acd32a/docs/core/integration-quality-scale/index.md)
- Zigbee2MQTT owning-project docs: [MQTT API](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/usage/mqtt_topics_and_messages.md), [MQTT security/config](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/configuration/mqtt.md), [availability](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/configuration/device-availability.md), [adapters/backups](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/adapters/README.md), [migration FAQ](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/faq/README.md), and [OTA](https://github.com/Koenkk/zigbee2mqtt.io/blob/c5763c305a61a1dc7a6428b6fa81df6f87b3f9e2/docs/guide/usage/ota_updates.md).
