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
- Does not expose arbitrary Z-Wave JS calls, factory reset, raw serial, or raw NVM bytes.
- Leaves only `GET /health` public; every operational read and mutation requires
  bearer authentication; a missing token fails closed outside an explicit test-only mode.
- Secure inclusion/exclusion, failed-node reconciliation, and NVM backup/restore
  require exact confirmation strings, serialize administration, enforce timeouts,
  and verify controller identity and backup digest. Hardware behavior remains unverified.

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
- `POST /v1/admin/inclusion/{start,stop}` and `/v1/admin/exclusion/{start,stop}`
- `POST /v1/admin/nodes/:nodeId/{remove-failed,replace-failed}`
- `POST /v1/admin/nvm/backups` and `/v1/admin/nvm/backups/:backupId/restore`

See [`docs/contract.md`](docs/contract.md) for the command and event boundary and
[`docs/privacy.md`](docs/privacy.md) for data handling and disclosure limits.

## Container

The image target is `ghcr.io/piphi-io/piphi-zwave-js-sidecar:0.4.0`. Mount
`/var/lib/piphi/zwave-js` read-write and provide the configured serial controller
as the single `/dev/zwave-controller` device. The root filesystem is read-only,
with `/tmp` as tmpfs, and the image runs as the unprivileged `node` user.
