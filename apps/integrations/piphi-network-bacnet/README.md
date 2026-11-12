# Piphi Network Bacnet

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_bacnet.main:app --reload --port 4224
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4224` by default and exposes the common PiPhi runtime route contract:

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

## Capability coverage

`capability-catalog.json` inventories BACnet discovery, transports, devices,
objects, properties, command priorities, specialized building systems, COV,
alarms, schedules, trend logs, and managed transport behavior. Each candidate
is implemented, planned, or excluded, and contract tests prevent unsupported
property writes from being advertised.

Protocol features remain planned until object/property discovery, writability
and priority handling, COV renewal, alarm deduplication, segmentation, and
representative device fixtures exist. Arbitrary APDUs, broad writes, device
reinitialization, and safety bypasses are explicitly excluded.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-bacnet:0.1.0 .
docker run --rm -p 4224:4224 docker.io/piphinetwork/piphi-network-bacnet:0.1.0
```
