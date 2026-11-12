# Piphi Network Bermuda Presence

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_bermuda_presence.main:app --reload --port 4206
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4206` by default and exposes the common PiPhi runtime route contract:

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

`capability-catalog.json` inventories the reviewed upstream state, events,
conditions, and actions. Every entry is classified as implemented, planned, or
excluded with its source, scope, and rationale. Contract tests enforce that
only implemented entries appear in the manifest, entities, commands, and
behavior contract.

Presence and ranging capabilities remain planned until observation ingestion,
hysteresis, normalization, and executable tests exist. This integration
consumes the shared BLE gateway and does not take ownership of host adapters.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-bermuda-presence:0.1.0 .
docker run --rm -p 4206:4206 docker.io/piphinetwork/piphi-network-bermuda-presence:0.1.0
```
