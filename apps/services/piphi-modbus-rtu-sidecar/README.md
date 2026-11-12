# PiPhi Modbus RTU Sidecar

Managed serial transport for PiPhi Modbus integrations using RTU or ASCII.

## Ownership boundary

The sidecar owns allow-listed serial ports, exclusive bus access, RTU/ASCII
framing, CRC/LRC and timing validation, one-in-flight request arbitration,
bounded queues, backpressure, reconnect, and restart reconciliation. Parent
integrations own register profiles, decoded device state, entities, telemetry,
and behaviors. The sidecar does not interpret arbitrary registers.

The machine-readable `capability-catalog.json` covers line settings, framing,
timing, request routing, queueing, recovery, and deliberately excluded raw or
unrestricted operations. Only `connected` and `refresh` are implemented in this
starter.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_modbus_rtu_sidecar.main:app --reload --port 4212
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4212` by default and exposes the common PiPhi runtime route contract:

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
docker build -t docker.io/piphinetwork/piphi-modbus-rtu-sidecar:0.1.1 .
docker run --rm -p 4212:4212 docker.io/piphinetwork/piphi-modbus-rtu-sidecar:0.1.1
```
