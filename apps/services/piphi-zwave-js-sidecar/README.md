# PiPhi Z-Wave JS sidecar

Managed Node-native Z-Wave JS controller transport for PiPhi Network.

The sidecar owns the driver lifecycle, serial controller, bounded event replay,
serialized maintenance commands, recovery, and schema `piphi.zwave.event.v1`.
It also exposes the complete resynchronization schema
`piphi.zwave.snapshot.v1` and constrained metadata-validated value writes.
The parent `piphi-network-zwave` integration owns homeowner-facing device and
capability normalization.

## Safety boundary

- Accepts stable `/dev/serial/by-id/` and `/dev/serial/by-path/` paths by default.
- Reads network keys only from `PIPHI_ZWAVE_*_KEY` environment variables.
- Recursively redacts keys, DSKs, credentials, raw frames, binary data, and NVM.
- Does not expose arbitrary Z-Wave JS calls, factory reset, raw serial, or NVM.
- Requires bearer authentication for Z-Wave replay, snapshots, and commands in production.
- Keeps inclusion, RF, and secure-device support unverified without hardware.

## Development

Requires Node 20 or newer; CI and the container use Node 22.

```bash
npm ci
npm run check
npm test
npm run validate
npm run build
```

Representative tests use Z-Wave JS command-class value definitions and bundled
device metadata for switch, lock, thermostat, multilevel sensor, electric meter,
and battery events. `MockCoreServer` verifies actual Core event delivery.

## Runtime

The API listens on `PORT` (default `4211`). Important routes:

- `GET /health` and `GET /diagnostics`
- `POST /config`, `POST /config/sync`, and `POST /deconfigure`
- `GET /state`, `GET /entities`, and `GET /contract`
- `GET /v1/zwave/events?after=0&limit=100`
- `GET /v1/zwave/snapshot`
- `POST /command`

See [`docs/contract.md`](docs/contract.md) for the command and event boundary.

## Container

The image target is `ghcr.io/piphi-io/piphi-zwave-js-sidecar:0.3.0`. Mount
`/var/lib/piphi/zwave-js` read-write and provide the configured serial controller
under `/dev/serial`. The image runs as the unprivileged `node` user.
