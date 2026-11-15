# PiPhi Matter sidecar: Home Assistant quality comparison

**Research cutoff:** 2026-11-15  
**Audited PiPhi release:** `piphi.service.matter-sidecar` `0.2.0-alpha.4`  
**Comparison baseline:** Home Assistant Core `dev` and its first-party Matter documentation as of the cutoff; OHF Matter Server `1.4.0` (the version PiPhi pins) and `1.6.0` (current at the cutoff); final Python Matter Server `8.1.2`; public CSA/Matter guidance.

## Executive conclusion

PiPhi has a credible **developer-preview controller facade**, not a Home Assistant-equivalent Matter integration and not a generally supported Matter controller. Its honest supported slice is:

- one Linux, host-networked, unprivileged Node.js sidecar;
- one locally persisted Matter fabric delegated to OHF `matter-server`;
- on-network discovery and setup-code commissioning through the upstream WebSocket client;
- write-only default Wi-Fi and Thread credential setters;
- endpoint discovery for nine explicitly recognized device types and a small cluster projection;
- read state for On/Off, level, temperature, humidity, occupancy, illuminance encoding, contact state, battery and availability;
- `on`, `off`, `toggle`, and a snapshot-style `refresh`; and
- an in-memory, 1,000-record event journal and shallow process health/diagnostics.

That slice is useful, but almost all controller correctness—fabric credentials, attestation, commissioning, subscriptions, node cache and removal—is inherited from upstream rather than verified end to end by PiPhi. PiPhi adds mapping and policy, but its ten tests use `FakeMatterBackend`; there is no test against a real Matter Server, simulated Matter device, BLE adapter, Thread border router, recovery cycle, or restored fabric. The local audit command (`npm ci && npm run check && npm test && npm run validate && npm run build`) passed all ten tests and reported no production dependency vulnerability, but this is contract/unit evidence only.

**Release judgment:**

- The repository and released artifact call themselves **`0.2.0-alpha.4`**, not beta. The alpha label is honest and should remain.
- A PiPhi **beta claim is not justified**. PiPhi pins OHF Matter Server `1.4.0`; that exact upstream tag described itself as a beta, “not yet officially re-certified by the CSA,” said it had generally been tested with a simple light, and documented that Wi-Fi should work while Thread required a network name that was not provided ([OHF Matter Server 1.4.0 README](https://github.com/matter-js/matterjs-server/blob/v1.4.0/README.md)). PiPhi's own README expressly says real-device verification is still required for Wi-Fi, Thread, BLE, subscription recovery and representative vendors ([PiPhi README](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/README.md)).
- The packaged artifact is nevertheless a real prerelease: the `alpha.4` GitHub release is marked prerelease and supplies an immutable image digest plus release evidence ([PiPhi alpha.4 release](https://github.com/PiPhi-io/piphi-apps/releases/tag/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4)). Build provenance, SBOM generation and multi-architecture publication are good supply-chain evidence, but do not establish runtime Matter quality.

PiPhi should not be described as “Home Assistant quality,” “production ready,” “Matter 1.6 compatible” in the broad product sense, or as supporting BLE/Thread commissioning without prominent qualification. A defensible description is: **alpha, local Matter controller facade for experimental Wi-Fi/Ethernet devices already reachable on-network; limited lights/plugs and basic sensors; Thread/BLE and recovery are unverified.**

## Source and evidence method

Only first-party sources were used:

- PiPhi source, tests, manifests, workflows, tags and releases;
- Home Assistant source and official integration/developer documentation;
- OHF's `matterjs-server` and archived `python-matter-server` source/documentation; and
- CSA's public Matter handbook and security/privacy publications.

The public specification text available without CSA membership is not a substitute for the normative member specification. Requirements below therefore distinguish public Matter architecture guidance from implementation-quality expectations.

## Evidence table

| Area | PiPhi evidence | First-party baseline | Assessment |
|---|---|---|---|
| Architecture | Spawns `matter-server`, connects with `@matter-server/ws-client`, and stores under one configured directory ([backend](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/src/matterjs-backend.ts)). | The final Python server owns node storage, interviews and subscriptions behind a WebSocket API so the fabric can continue while a consumer is down ([Python server development docs](https://github.com/matter-js/python-matter-server/blob/main/DEVELOPMENT.md)). OHF JS is its drop-in successor ([OHF README](https://github.com/matter-js/matterjs-server/blob/main/README.md)). | Sound separation, mostly inherited upstream. PiPhi does not negotiate or enforce WebSocket schema compatibility. |
| Runtime/version | Pins `matter-server` and client `1.4.0`, matter.js `0.17.9`; runtime is Node 24 ([package](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/package.json)). | OHF `1.4.0` was a beta; current `1.6.0` was released 2026-11-14 and supports Matter 1.6 ([1.6.0 release](https://github.com/matter-js/matterjs-server/releases/tag/v1.6.0)). Python server ended at `8.1.2` and is archived in favor of JS ([Python server README](https://github.com/matter-js/python-matter-server)). | Pinning is reproducible, but PiPhi froze a beta controller two stable minor releases behind current at cutoff. |
| Network/container | Host networking, loopback API/backend, non-privileged user, persistent path and optional interface selection ([manifest](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/src/manifest.json), [Dockerfile](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/Dockerfile)). | Matter requires IPv6, link-local multicast, correct Router Advertisement/RIO handling, host networking, and careful firewall/conntrack handling; self-managed containers are explicitly unsupported for HA users ([OHF OS requirements](https://github.com/matter-js/matterjs-server/blob/main/docs/os_requirements.md), [OHF Docker docs](https://github.com/matter-js/matterjs-server/blob/main/docs/docker.md), [HA Matter docs](https://www.home-assistant.io/integrations/matter/)). | Necessary defaults, not sufficient. No preflight or repair for IPv6, multicast, interface, RIO, firewall, TBR, or same-LAN requirements. |
| Commissioning | Discovers commissionables and calls `commissionWithCode`; supports `network_only`; auto-adds returned endpoints ([service](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/src/service.ts)). | Matter commissioning includes discovery, PASE, fail-safe, attestation, CSR/NOC installation, network provisioning, operational discovery, CASE and completion ([CSA commissioning guide](https://handbook.buildwithmatter.com/how-it-works/commisioning)). HA provides mobile BLE flows, new-device and multi-admin flows, and guided prerequisites ([HA Matter docs](https://www.home-assistant.io/integrations/matter/)). | Upstream performs protocol steps; PiPhi exposes only setup-code commission. No parse/validate flow, timeout control, attestation result UX, actionable reasons, cancellation, rollback, or partial-success reconciliation. |
| BLE | `MATTER_ENABLE_BLE=false` by default; when true it passes adapter `0` ([backend](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/src/matterjs-backend.ts)). | OHF requires either host BLE access (preferably BlueZ D-Bus with `/run/dbus` and `NOBLE_BINDINGS=dbus`) or BLE proxy; HA intentionally commissions through its Companion app/proxy ([OHF Docker docs](https://github.com/matter-js/matterjs-server/blob/main/docs/docker.md), [HA Matter docs](https://www.home-assistant.io/integrations/matter/#bluetooth-used-during-commissioning)). | **Not supported by the shipped manifest.** It exposes no D-Bus mount, adapter permission, binding choice, or proxy. An environment toggle alone is not deployable BLE evidence. |
| Thread | Accepts one default operational dataset and relies on host network/TBR. | Thread devices need BLE commissioning, a Thread border router and working IPv6 routing; Matter operational traffic is IPv6 ([CSA transports](https://handbook.buildwithmatter.com/how-it-works/connectivity-transports), [OHF OS requirements](https://github.com/matter-js/matterjs-server/blob/main/docs/os_requirements.md)). | **Unverified/experimental.** No TBR discovery/status, dataset validation/status, network selection, RIO check, topology, or recovery evidence. The pinned upstream `1.4.0` README itself documented a Thread limitation. |
| Fabric/credentials | Upstream owns fabric; PiPhi sets a fixed label and exposes set/clear for one Wi-Fi and one Thread default. API is loopback by default ([backend](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/src/matterjs-backend.ts), [app](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/src/app.ts)). | A fabric shares a root of trust and Fabric ID; NOCs bind node identity and keys; a device can hold several independent fabrics ([CSA fabric guide](https://handbook.buildwithmatter.com/how-it-works/fabric)). OHF supports named network credentials, fabric listing/removal and commissioning windows ([OHF WebSocket API](https://github.com/matter-js/matterjs-server/blob/main/docs/websockets_api.md)). | Minimal single-fabric administration only. No fabric inventory, multi-admin sharing, ACL/binding management, credential summary/selection/rotation workflow, or controller identity export. |
| Subscriptions/events | Calls `startListening`; reconnects after `connection_lost`; keeps a volatile 1,000-event queue ([backend](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/src/matterjs-backend.ts), [service](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/src/service.ts)). | OHF auto-subscription is the normal reliable path and re-establishes after connection loss; `start_listening` supplies current nodes and streams updates ([OHF WebSocket API](https://github.com/matter-js/matterjs-server/blob/main/docs/websockets_api.md)). | Correct delegation in principle. No real restart/offline/sleepy-device test; no durable cursor, overflow signal or backfill. `server_shutdown` only marks disconnected and does not trigger PiPhi reconnect. |
| Device/entity model | One PiPhi entity/device per endpoint; nine device-type names; generic class chosen from a few capabilities; no parent/bridge model ([capabilities](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/src/capabilities.ts), [service](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/src/service.ts)). | HA's first-party integration maps dedicated platforms including binary sensor, button, camera, climate, cover, event, fan, light, lock, number, select, sensor, siren, switch, update, vacuum, valve and water heater ([HA Matter source directory](https://github.com/home-assistant/core/tree/dev/homeassistant/components/matter)); it tracks bridges/composed endpoints and stable entities. | Very narrow mapping. Dimmable endpoints report brightness but cannot set it. No color, cover, HVAC, lock, fan, valve, media/camera, energy, OTA, ICD, bridge hierarchy, dynamic endpoint lifecycle or per-feature entities. |
| Availability/recovery | Node `available` becomes `connected`; backend connection has bounded retries; managed child gets five restart attempts. | HA reloads its config entry after listener disconnect, raises repair issues (including IPv6 disabled), validates server versions and marks entities unavailable ([HA integration source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/matter/__init__.py)). | Partial. Node availability exists, but no repair surface, no stale-device policy and no proven post-restart convergence. `/health` returns HTTP 200 when degraded, so the Docker healthcheck treats `ok:false` as healthy. |
| Diagnostics | Returns process booleans/counts/start time/last startup error and three asserted security flags ([app](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/src/app.ts)). | HA provides integration- and device-level downloads with server info, node attributes, cluster/network details and explicit redaction ([HA diagnostics source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/matter/diagnostics.py), [HA docs](https://www.home-assistant.io/integrations/matter/#downloading-diagnostics)). OHF exposes server diagnostics, node/IP/ping, Thread diagnostics and topology. | Inadequate for field support. No versions/schema/fabric ID, nodes, subscriptions, IPs, interface, TBR, Thread/Wi-Fi state, event loss, child status or logs. `credentials_exposed:false` is an assertion, not an audit. |
| Backup/restore | Declares `/var/lib/piphi/matter` as a volume; no backup API, consistency procedure, restore docs, encryption, test or release gate. | OHF says the storage contains fabric IDs, keys and certificates, requires backup before migration, and forbids two controllers using the same fabric data concurrently ([OHF migration guide](https://github.com/matter-js/matterjs-server/blob/main/docs/migration.md)). HA creates an add-on backup before uninstalling an integration-created Matter app ([HA integration source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/matter/__init__.py)). | Critical gap. Persistence is not backup. Loss of this storage loses controller identity; an unsafe clone can create two active copies of the same controller. |
| Security/privacy | Loopback defaults, unprivileged container, no arbitrary cluster invocation, filtered updates for clusters 31/49/62/63, write-only credential endpoints. | CSA calls for layered security, protected messages, attestation, confidentiality/integrity, identity and data minimization ([CSA security principles](https://csa-iot.org/wp-content/uploads/2022/06/Matter-Security-Privacy_one-pager.pdf), [security white paper](https://csa-iot.org/developer-resource/white-paper-matter-security-and-privacy-copy)). | Good least-privilege direction, incomplete boundary. There is no application authentication if the API is rebound. Generic `node_added`/`node_updated` events forward a whole sanitized node object and bypass the sensitive-cluster filter, so the claim that events never expose credentials/security metadata is not demonstrated. Storage secrets are not documented as encrypted at rest. |
| Tests/CI | Typecheck, ten fake-backend tests, catalog validation, production audit, compile and OCI build on changes; release builds amd64/arm64 with SBOM/provenance ([app declaration](https://github.com/PiPhi-io/piphi-apps/blob/apps/piphi.service.matter-sidecar/v0.2.0-alpha.4/apps/services/piphi-network-matter/piphi-app.json), [CI](https://github.com/PiPhi-io/piphi-apps/blob/main/.github/workflows/reusable-app-ci.yml), [release workflow](https://github.com/PiPhi-io/piphi-apps/blob/main/.github/workflows/release-app.yml)). | HA IQS Silver requires >95% per-module coverage; Gold requires diagnostics, discovery, repairs and extensive user docs ([IQS rules](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules)). | Good basic CI and supply chain. No coverage measurement, upstream compatibility matrix, integration/radio/hardware tests, soak/fault injection, restored-backup test, or conformance/certification evidence. |

## Feature and behavior gaps

### 1. Commissioning and multi-admin

PiPhi exposes only “discover” and “commission with code.” It does not expose the upstream operations needed for a complete controller UX: onboarding-payload parsing, filtered on-network commissioning, commissioning-window creation, fabric listing/removal, ACLs, bindings, or meaningful commissioning error categories. HA supports both adding a new device and sharing an already commissioned device into HA's fabric, then sharing it onward and managing fabrics ([HA Matter docs](https://www.home-assistant.io/integrations/matter/)).

Commissioning is not transactional at the PiPhi layer. Once upstream returns a commissioned node, PiPhi configures each normalized endpoint one at a time. A failure while saving one endpoint can leave a valid fabric member with only a partial PiPhi alias/config set. There is no job ID, progress, cancel, timeout, idempotency key, compensating removal, or explicit reconciliation operation.

The delete URL is especially unsafe: `DELETE /v1/registry/:nodeId/:endpointId` ignores `endpointId` and removes the **whole node**. The path implies endpoint deletion even though Matter fabric membership is node-scoped. This must be renamed and guarded before broader use.

### 2. Fabric and credential lifecycle

The controller storage is security-critical state, not a cache. It contains the controller CA/fabric identity, keys and certificates; CSA public guidance explains that fabric credentials establish the shared security domain ([CSA fabric guide](https://handbook.buildwithmatter.com/how-it-works/fabric)). PiPhi neither inventories that state nor defines its lifecycle.

Missing lifecycle behaviors include:

- explicit first-run fabric creation and durable identity reporting;
- safe network-credential replacement/selection (upstream supports named credentials; PiPhi only addresses `default`);
- multi-admin commissioning windows and per-node fabric management;
- controller decommission/reset with typed confirmation;
- encrypted backup/export policy, quiesced snapshot semantics and restore validation;
- clone detection and a prohibition on simultaneously running restored duplicates; and
- migration/version compatibility checks before opening existing storage.

### 3. Subscriptions, event delivery and recovery

PiPhi sensibly leaves normal subscriptions to Matter Server. However, its own delivery contract is weaker than the upstream contract:

- PiPhi events are memory-only and disappear on restart.
- A cursor not found returns the complete retained queue rather than an explicit cursor-expired error.
- Evicting old records is silent; consumers cannot detect loss.
- `node_added` and endpoint changes do not establish/update PiPhi configs unless commissioning happened through PiPhi's own endpoint.
- `server_shutdown` does not enter the reconnect loop.
- The reconnect loop is bounded and has no supervisor-visible exhausted state beyond a volatile event.
- There is no test that state converges after server restart, device restart, network partition, sleepy-device interval, bridge endpoint add/remove, event burst, or PiPhi restart.

Recovery should be state reconciliation first and event replay second. On every reconnect, PiPhi should rebuild its authoritative node/endpoint view from `start_listening`, diff it against durable config, publish additions/removals/availability changes, and make event loss explicit.

### 4. Device and entity semantics

The mapper is cluster-presence driven and deliberately small. That is preferable to claiming a global superset, but it does not implement the Matter device model with HA-like fidelity:

- one endpoint becomes one coarse entity instead of multiple feature entities;
- Descriptor parent relationships, bridged devices and composed devices are ignored;
- feature maps, attribute constraints, null/unknown values and quality flags are not modeled;
- device-type revisions and cluster revisions are ignored;
- `brightness_percent` is read-only despite classifying the endpoint as a switch;
- illuminance is correctly labeled raw Matter encoding, but is not converted to an illuminance entity;
- no event-type semantic mapping exists for switches/buttons;
- metadata omits serial number, software/hardware version, network type, IPs and topology; and
- unsupported device types still appear as generic devices, which can be mistaken for supported control.

The support statement should list tested **device/cluster combinations**, not merely Matter versions. “Matter 1.6” describes a protocol/data-model revision, not implementation of all 1.6 device types.

### 5. Thread and IPv6

Host network mode is necessary but does not establish Thread support. The host must correctly process IPv6 Router Advertisements and Route Information Options; a TBR must provide routing; link-local multicast and mDNS must work; and stateful firewalls can silently drop sleepy-device reports unless UDP conntrack timeouts are suitable ([OHF OS requirements](https://github.com/matter-js/matterjs-server/blob/main/docs/os_requirements.md)).

Before Thread can be supported, PiPhi needs preflight and diagnostics for:

1. IPv6 enabled on the selected interface;
2. multicast/mDNS reachability and same-LAN assumptions;
3. discovered TBRs and selected Thread network;
4. operational dataset validation and non-secret summary;
5. RIO-installed route visibility;
6. BLE/proxy availability for commissioning;
7. stateful-firewall warning for sleepy devices; and
8. tested recovery with at least two TBRs and sleepy end devices.

### 6. Diagnostics and supportability

The current `/diagnostics` is effectively an expanded health response. It cannot answer the first field questions: which controller/schema version is running, which fabric is active, which nodes are subscribed, which interface and addresses are used, why a node is unavailable, whether a TBR is visible, whether the child is restarting, or whether events were dropped.

Add separate redacted integration and node diagnostics. At minimum include component/schema versions, uptime/restart counters, selected interface, non-secret credential presence, fabric ID hash (not raw keys), node availability/interview/subscription summaries, endpoint/device types, network type/IP diagnostics, TBR/topology summary, event-watermark/drop counters, recent typed errors and storage health. Redaction must be allow-list based and tested with canary secrets.

### 7. Privacy and security boundary

The default boundary—both HTTP facade and WebSocket server on loopback—is a good starting point. It assumes PiPhi Core and the sidecar share one trusted host. If `MATTER_API_HOST` or backend host is changed, there is no authentication, authorization, TLS, origin restriction, CSRF model or per-operation identity. The service therefore must **refuse non-loopback binding unless an authenticated transport is configured**.

The event redaction has a concrete structural hole. Individual `attribute_updated` and `node_event` records drop four sensitive clusters, but every other upstream event is wrapped wholesale. OHF documents `node_added` and `node_updated` as carrying complete node data including `attributes` ([OHF WebSocket events](https://github.com/matter-js/matterjs-server/blob/v1.4.0/docs/websockets_api.md#events)). PiPhi can therefore place security/network attributes into `/v1/events` without path-based filtering. Replace generic recursive serialization with a schema-aware allow-list; do not return full node objects through the public journal.

## Home Assistant Integration Quality Scale assessment

The [Home Assistant Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale) formally grades Home Assistant Core integrations. PiPhi is a platform service, not an HA integration, so it cannot honestly claim an official IQS tier. The assessment below applies the published rules **analogically** to identify evidence maturity.

### Result: below Bronze / ungraded

PiPhi does not meet the all-rules requirement for Bronze. Relevant positives are local push behavior, typed source, unique endpoint IDs, fail-closed actions, startup connection testing, open-source dependencies and basic high-level/API documentation. Blocking Bronze-equivalent gaps include:

- no UI config/onboarding flow or full error-path config tests;
- no step-by-step installation prerequisites for IPv6, BLE, Wi-Fi, Thread and TBRs;
- no removal/reset instructions and no warning that node deletion removes fabric membership;
- no documented actions/conditions/triggers with fields and examples;
- no user-customizable stable multi-entity model; and
- no duplicate controller/fabric setup prevention.

### Silver-equivalent gaps

- no >95% per-module coverage measurement (and no coverage command at all);
- no owner field in the service manifest equivalent to HA `codeowners`;
- no robust one-time unavailable/recovered logging contract;
- no proven unload/reload and post-disconnect convergence;
- no reauthentication/credential replacement flow; and
- errors are flattened to HTTP 400/422 strings without stable translated categories.

### Gold-equivalent gaps

- diagnostics are not field-usable;
- no repair issues for IPv6, TBR, BLE, storage, schema or credential problems;
- no complete device/entity grouping, bridge hierarchy or dynamic endpoint behavior;
- no stale-device reconciliation;
- no supported/unsupported device matrix, troubleshooting, update semantics or automation examples; and
- no localization, entity categories, default-disable policy or translated exceptions/icons.

### Platinum-equivalent observations

The service is asynchronous and TypeScript-typed, but there is no strictness claim comparable to HA strict mypy, and the rubric's injected shared HTTP session is not directly applicable. Platinum cannot be considered before lower tiers.

## Safety invariants

These are release-blocking invariants for any beta or production claim.

1. **One active controller identity:** never run two processes from the same restored fabric storage; startup must lock storage and documentation must forbid clones.
2. **Fabric state is durable:** no successful commissioning response until upstream fabric/node state and PiPhi config are durably committed or explicitly marked for reconciliation.
3. **No implicit fabric reset:** missing, unreadable, incompatible or empty storage must fail closed; it must never silently create a replacement fabric over a prior installation.
4. **No endpoint-shaped node deletion:** decommission operations must be node-scoped, clearly named, confirmed and idempotent; endpoint removal must never silently remove a whole node.
5. **Secrets never cross read APIs:** setup payloads, Wi-Fi passwords, Thread datasets, operational private keys and equivalent secrets must not appear in logs, errors, events, health, diagnostics or telemetry. Tests must inject canary secrets through every path.
6. **Non-secret security metadata is minimized:** ACL, NOC, group-key and network-commissioning attributes must be excluded unless a privileged, purpose-specific diagnostic export requires redacted forms.
7. **Loopback is mandatory by default:** a non-loopback HTTP/WebSocket listener must require authenticated, authorized and encrypted transport and must emit a high-severity diagnostic warning.
8. **Capabilities are negotiated, not inferred globally:** commands may be advertised only when the endpoint's device type, server cluster, feature map and required command/attribute support permit them.
9. **Commands fail closed:** no arbitrary cluster invocation; constraints, timed-interaction requirements and dangerous-device confirmation policies are validated before dispatch.
10. **Availability is truthful:** stale cache is never represented as fresh; service-backend loss and node loss are distinct; health endpoints and container healthchecks agree on degraded/unhealthy state.
11. **Event loss is observable:** every stream has monotonic durable watermarks or an explicit reset/overflow signal; an unknown cursor is never treated as success.
12. **Reconnect reconciles:** after any restart or partition, the full node/endpoint state is re-read and diffed before normal event delivery resumes.
13. **Backups are consistent and restorable:** backup quiesces or uses an upstream-supported consistent snapshot, includes all fabric/config state, is access-controlled, and is proven by an automated restore test.
14. **Thread claims require network evidence:** no Thread support claim without IPv6/RIO, TBR, BLE/proxy, dataset, sleepy-device and multi-TBR tests on supported host configurations.
15. **Upstream compatibility is gated:** startup verifies WebSocket schema range and CI tests every supported PiPhi/upstream version pair; unsupported versions fail with a typed remediation.
16. **Attestation policy is explicit:** commissioning UI/API distinguishes certified, test and rejected devices; bypassing attestation requires informed, audited user intent.

## Prioritized next work

### P0 — required before any beta claim

1. **Define and publish the narrow support contract.** State Ethernet/on-network and limited Wi-Fi first; mark BLE and Thread unsupported until verified; list exact device types, clusters, commands, upstream version and host requirements.
2. **Close the event privacy hole.** Allow-list public event shapes; recursively filter node snapshots by endpoint/cluster/attribute; add canary-secret tests for credentials, setup codes, network commissioning, ACL, NOC and group-key data.
3. **Fix destructive semantics.** Replace endpoint-shaped registry deletion with an explicit node decommission endpoint, confirmation token/idempotency, typed outcome and recovery guidance.
4. **Make storage lifecycle safe.** Add exclusive locking, permission checks, deterministic persistent-volume ownership, startup identity/schema validation, backup/restore procedure and a restored-fabric integration test. Document that duplicate restored instances must never run concurrently.
5. **Add a real integration harness.** Run the pinned Matter Server and a controllable virtual Matter device; test commission, subscribe, command, node/server restart, disconnect/reconnect, decommission and restored storage. Measure coverage and establish a threshold.
6. **Correct health/recovery.** Make the healthcheck inspect JSON `ok`, reconnect after `server_shutdown`, expose restart/exhaustion state, and prove state reconciliation after reconnect.
7. **Pin support to a reviewed upstream.** Evaluate current stable OHF `1.6.0`; either upgrade with schema/integration tests or explicitly time-bound the `1.4.0` beta dependency. Do not equate upstream protocol support with PiPhi feature support.

### P1 — required for a useful limited beta

1. Build a commissioning job model with payload parsing, typed reasons, progress, timeout/cancel, idempotency and partial-success reconciliation.
2. Deliver deployable BLE via a least-privilege D-Bus mount or BLE proxy; test it in the released container on both architectures.
3. Add IPv6/mDNS/interface/TBR/RIO preflight, repair messages and Thread dataset validation/status.
4. Implement integration- and node-level redacted diagnostics, event drop counters and support bundles.
5. Model bridge/composed endpoint parentage and dynamic endpoint add/remove; split endpoints into stable feature entities.
6. Add brightness control and only then expand one reviewed cluster/device family at a time with conformance fixtures and real representative hardware.
7. Add fabric inventory, open commissioning window, multi-admin management and safe fabric removal by using the typed upstream API.

### P2 — quality and breadth

1. Test a published device matrix across Wi-Fi, Ethernet, Thread, bridges, sleepy devices and multiple vendors/TBRs; publish known limitations.
2. Add soak, burst/backpressure, network-partition, power-loss, corrupt-storage and OTA/fabric migration tests.
3. Add OTA, ICD and topology only after their security, resource and failure semantics are specified.
4. Build user-facing install/removal/troubleshooting/backup documentation and automation examples.
5. Track an IQS-inspired checklist in-repo, while clearly calling it internal and not an official HA tier.

## Bottom line

PiPhi's best current asset is architectural restraint: it uses the first-party OHF controller rather than reimplementing Matter, keeps listeners on loopback, persists the fabric, and allow-lists mutations. Its biggest risk is that this sound foundation can look more complete than the PiPhi-owned layer actually is. The source and tests support an **alpha for developers evaluating a limited local endpoint projection**. They do not support a beta reliability claim, broad Matter 1.6 capability claim, deployable BLE/Thread claim, or Home Assistant quality-tier claim.
