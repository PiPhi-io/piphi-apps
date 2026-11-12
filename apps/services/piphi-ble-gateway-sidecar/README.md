# PiPhi BLE Gateway Sidecar

Managed Linux BlueZ transport for PiPhi integrations that consume Bluetooth Low
Energy observations or explicitly authorized GATT operations.

## Ownership boundary

The sidecar owns adapter discovery, scan arbitration, privacy-preserving
observation delivery, bounded queues, backpressure, GATT connection
serialization, dependency health, and restart recovery. Parent integrations own
device identity, normalized entities, state, telemetry, and behaviors. The
sidecar never advertises discovered Bluetooth peripherals as PiPhi entities.

The machine-readable `capability-catalog.json` accounts for adapter lifecycle,
advertisements, identity rotation, GATT, pairing, fanout, failure recovery, and
unsafe operations. Only `connected` and `refresh` are implemented in this
starter; every BlueZ-dependent capability remains planned until its adapter and
failure-path fixtures exist.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_ble_gateway_sidecar.main:app --reload --port 4210
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4210` by default and exposes the common PiPhi runtime route contract:

- `GET /health`
- `GET /diagnostics`
- `POST /discover`
- `POST /config`
- `POST /config/sync`
- `POST /deconfigure`
- `POST /deconfigure/{config_id}`
- `GET /state`
- `GET /contract`
- `GET /entities`
- `GET /events`
- `POST /events/device/{config_id}/example`
- `POST /telemetry/example`
- `POST /telemetry/device/{config_id}/example`
- `POST /command`

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-ble-gateway-sidecar:0.1.1 .
docker run --rm -p 4210:4210 docker.io/piphinetwork/piphi-ble-gateway-sidecar:0.1.1
```
