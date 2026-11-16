# PiPhi Matter.js Sidecar

PiPhi's local Matter controller service, powered by [matter.js](https://github.com/matter-js/matter.js) through the Open Home Foundation `matter-server` packages.

The sidecar owns the Matter fabric, commissioned-node inventory, subscriptions, discovery, and command transport. PiPhi Core consumes the stable HTTP facade on port `8710`; the supervised Matter.js WebSocket backend remains loopback-only on port `5580`.

## Why Matter.js

The original alpha used `chip-tool` subprocesses, regex parsing, and a manually maintained registry. This version uses the typed `@matter-server/ws-client` contract and Matter.js-native persistent storage. It no longer builds or ships a separate `matter-chip-tool` image.

## Runtime model

- Node.js 24 and TypeScript
- `matter-server` 1.6.0 backed by its aligned matter.js 0.18.1 build
- WebSocket schema compatibility is enforced for the reviewed range 13–15
- Persistent controller data under `/var/lib/piphi/matter`
- Exclusive storage leasing prevents two controller processes from sharing one fabric identity
- Host networking for IPv6 and mDNS
- BLE disabled by default and enabled explicitly with `MATTER_ENABLE_BLE=true`
- PiPhi API and Matter.js backend bound to loopback by default
- Production API routes require `PIPHI_MATTER_SIDECAR_TOKEN` (or the Core-injected internal token)
- Mutating device commands restricted to negotiated, allow-listed actions

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Sidecar and Matter.js connection health |
| `GET` | `/diagnostics` | Sanitized operational diagnostics |
| `GET` | `/v1/devices/discover` | Commissioned endpoints and negotiated capabilities |
| `GET` | `/v1/discovery/commissionables` | Discover devices in commissioning mode |
| `POST` | `/v1/commission/code` | Commission using a QR/manual setup payload |
| `POST` | `/v1/commission/wifi` | Experimentally provision a factory-reset Wi-Fi device over BLE using write-only setup and network credentials |
| `POST` | `/v1/commission/thread` | Experimentally commission a Thread device with a one-shot write-only operational dataset |
| `GET` | `/v1/registry` | Matter.js-owned commissioned-node inventory |
| `POST` | `/v1/nodes/:node/decommission` | Decommission a whole node after matching `confirm_node_id` |
| `POST` | `/v1/admin/backup/quiesce` | Stop controller I/O while retaining its exclusive storage lease |
| `POST` | `/v1/admin/backup/resume` | Resume the controller after Core snapshots the persistent volume |
| `GET/POST/DELETE` | `/v1/configs` | Manage PiPhi aliases and enabled endpoints |
| `POST` | `/v1/telemetry/poll` | Return the current subscription-backed cache |
| `GET` | `/v1/events` | Read the bounded Matter event journal |
| `GET` | `/v1/matter/snapshot` | Read the redacted controller snapshot and replay watermark |
| `GET` | `/v1/matter/events` | Read sequenced transport events with explicit gap detection |
| `GET` | `/v1/preflight` | Read redacted controller, interface, and IPv6 readiness checks |
| `POST` | `/v1/commands/invoke` | Invoke an allow-listed negotiated command |
| `POST/DELETE` | `/v1/credentials/wifi` | Legacy persistent write is rejected; delete remains available to clear a pre-upgrade default credential |
| `POST/DELETE` | `/v1/credentials/thread` | Persistent writes are rejected; delete remains available for defensive cleanup |

Credentials and setup payloads are never returned by health, discovery, telemetry, events, or diagnostics.
The legacy endpoint-shaped registry deletion route returns `410` and never removes a node.
The API refuses non-loopback binding; remote access must go through authenticated PiPhi Core APIs.
Never clone and run a restored Matter storage directory concurrently with its source instance.

The release qualification command `npm run qualify:backup-restore` starts the real pinned
Matter Server, creates a checksummed backup while quiesced, restores it into an empty target,
verifies the same hashed controller identity, rejects a competing lease holder, and proves
that corrupt or incomplete archives fail before mutating the restore target.

`npm run qualify:virtual-device` is the host-network qualification for the supported
on-network slice. It starts a real matter.js virtual On/Off light, commissions it through the
pinned Matter Server, verifies negotiated capabilities, command execution, subscription-backed
state and events, restores the controller into an empty storage directory, reconnects and controls
the already commissioned device with the preserved controller identity, and then verifies node
decommissioning. The test is opt-in because
its IPv6/mDNS requirements are not available in every generic CI runner; its source is still
strictly type-checked and parsed by ordinary CI.

## Backup and restore

PiPhi Core must call the authenticated backup-quiesce endpoint with
`{"confirmation":"quiesce-matter-controller"}`, wait for `202`, snapshot the complete
Matter persistent volume, and always call the resume endpoint afterward. Quiescing stops
Matter Server but retains the exclusive storage lease so another controller cannot open the
fabric during the snapshot. Restore is an offline operation: stop the container, restore the
complete volume into an empty target, preserve owner-only permissions, and start exactly one
controller instance. Never merge storage trees or run the source and restored copy together.

## Development

```bash
npm install
npm run check
npm test
npm run validate
npm run build
MATTER_STORAGE_DIR=./matter-state npm start
```

## Container

```bash
docker build -t ghcr.io/piphi-io/matter-sidecar:dev .
docker run --rm --network host \
  -v "$PWD/matter-state:/var/lib/piphi/matter" \
  ghcr.io/piphi-io/matter-sidecar:dev
```

BLE commissioning is optional and disabled by default. The supported experimental deployment uses
the BlueZ D-Bus binding without privileged mode or raw-HCI capabilities:

```bash
docker run --rm --network host \
  -e MATTER_ENABLE_BLE=true -e NOBLE_BINDINGS=dbus \
  -v /run/dbus:/run/dbus:ro \
  --security-opt apparmor=piphi-matter-ble \
  -v "$PWD/matter-state:/var/lib/piphi/matter" \
  ghcr.io/piphi-io/matter-sidecar:dev
```

The host must run BlueZ with a powered `hci0`, and its D-Bus policy must permit the non-root
container process to scan, connect, and use GATT. Load the reviewed profile before starting the
container with `sudo apparmor_parser -r deploy/apparmor/piphi-matter-ble`; do not use
`apparmor=unconfined`. `GET /v1/preflight` reports
`ready_for_ble_wifi` only when IPv6/on-network readiness, the D-Bus binding, Matter Server BLE,
BlueZ, and the powered adapter all pass. Do not grant blanket privileged-container access.

`POST /v1/commission/wifi` serializes attempts, stores credentials under a unique temporary ID,
uses that exact ID for BLE commissioning, and removes it in `finally` after success or failure.
The setup payload, SSID, and password are never returned. Startup deletes any orphaned
`piphi-provision-*` credential slots left by a process or host crash before the API becomes ready.
Controller storage remains owner-only because a crash can leave a credential on disk until that
cleanup completes; storage encryption is still recommended before promoting BLE beyond experimental status.

`POST /v1/commission/thread` similarly installs the operational dataset only for one serialized
commissioning attempt and removes it in `finally` after success or failure. Startup also removes an
orphaned Thread dataset before readiness. Persistent Thread dataset writes return `410`.

Qualify the exact release image on a Linux Docker host before promotion:

```bash
npm run qualify:release-image -- ghcr.io/piphi-io/matter-sidecar:0.2.0
```

The qualifier inspects the image's non-root user and `/var/lib/piphi/matter` volume,
then runs it with host networking, an allocated loopback port, a bearer token, and a
temporary named volume. It waits for the backend—not merely HTTP—to be healthy,
checks snapshot authentication and schema 15, and proves that the hashed controller
identity survives container replacement with the same volume. It always removes the
temporary container and volume. This host-network Docker check is intentionally not
part of generic CI.

## Capability coverage

[`src/capability-catalog.json`](src/capability-catalog.json) is the machine-readable source of truth for implemented, planned, and deliberately excluded Matter capabilities. Capabilities are negotiated per endpoint from its Descriptor and server clusters rather than advertising a global superset.

This alpha has physical Wi-Fi plug and BLE-to-Wi-Fi commissioning evidence for a TP-Link KP125M
(hardware 1.0, firmware 1.0.0), including subscriptions, restart, empty-volume controller restore,
restored control, and decommissioning. It still requires representative Ethernet plugs, Wi-Fi
lights, Thread commissioning through a border router, broader vendor/device coverage, and private
Core UI evidence.

Physical support evidence is governed by the machine-validated
[`docs/hardware-qualification.json`](docs/hardware-qualification.json) ledger and its
[`operator protocol`](docs/hardware-qualification.md). Simulated evidence cannot qualify a
physical profile.

`npm run test:coverage` enforces at least 95% aggregate line coverage over production `src` files.
The opt-in virtual-device qualification is separate and is not included in that ordinary
unit/integration coverage figure.
