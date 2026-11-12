# PiPhi Matter Sidecar

PiPhi's local Matter controller service, powered by [matter.js](https://github.com/matter-js/matter.js) through the Open Home Foundation `matter-server` packages.

The sidecar owns the Matter fabric, commissioned-node inventory, subscriptions, discovery, and command transport. PiPhi Core consumes the stable HTTP facade on port `8710`; the supervised Matter.js WebSocket backend remains loopback-only on port `5580`.

## Why Matter.js

The original alpha used `chip-tool` subprocesses, regex parsing, and a manually maintained registry. This version uses the typed `@matter-server/ws-client` contract and Matter.js-native persistent storage. It no longer builds or ships a separate `matter-chip-tool` image.

## Runtime model

- Node.js 24 and TypeScript
- `matter-server` 1.4.0 backed by matter.js 0.17.9
- Persistent controller data under `/var/lib/piphi/matter`
- Host networking for IPv6 and mDNS
- BLE disabled by default and enabled explicitly with `MATTER_ENABLE_BLE=true`
- PiPhi API and Matter.js backend bound to loopback by default
- Mutating device commands restricted to negotiated, allow-listed actions

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Sidecar and Matter.js connection health |
| `GET` | `/diagnostics` | Sanitized operational diagnostics |
| `GET` | `/v1/devices/discover` | Commissioned endpoints and negotiated capabilities |
| `GET` | `/v1/discovery/commissionables` | Discover devices in commissioning mode |
| `POST` | `/v1/commission/code` | Commission using a QR/manual setup payload |
| `GET` | `/v1/registry` | Matter.js-owned commissioned-node inventory |
| `DELETE` | `/v1/registry/:node/:endpoint` | Decommission a node and remove local aliases |
| `GET/POST/DELETE` | `/v1/configs` | Manage PiPhi aliases and enabled endpoints |
| `POST` | `/v1/telemetry/poll` | Return the current subscription-backed cache |
| `GET` | `/v1/events` | Read the bounded Matter event journal |
| `POST` | `/v1/commands/invoke` | Invoke an allow-listed negotiated command |
| `POST/DELETE` | `/v1/credentials/wifi` | Set or clear write-only Wi-Fi credentials |
| `POST/DELETE` | `/v1/credentials/thread` | Set or clear the write-only Thread dataset |

Credentials and setup payloads are never returned by health, discovery, telemetry, events, or diagnostics.

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
docker build -t piphinetwork/matter-sidecar:dev .
docker run --rm --network host \
  -v "$PWD/matter-state:/var/lib/piphi/matter" \
  piphinetwork/matter-sidecar:dev
```

BLE commissioning is optional and requires appropriate host Bluetooth/D-Bus access. Do not grant blanket privileged-container access; add only the host resources required by the deployment.

## Capability coverage

[`src/capability-catalog.json`](src/capability-catalog.json) is the machine-readable source of truth for implemented, planned, and deliberately excluded Matter capabilities. Capabilities are negotiated per endpoint from its Descriptor and server clusters rather than advertising a global superset.

This alpha still requires real-device verification for Wi-Fi commissioning, Thread commissioning through a border router, BLE commissioning, subscription recovery after restart, and representative vendor devices.
