# Piphi Network Waste Collection

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_waste_collection.main:app --reload --port 4205
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4205` by default and exposes the common PiPhi runtime route contract:

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

The first live widget is a manual next-pickup countdown. Configure a collection
type, ISO date (`YYYY-MM-DD`), and optional IANA time zone. The runtime
recalculates days remaining, shows today's pickup as zero, and stops reporting
the schedule as live after that date passes. This is user-maintained data:
no municipal provider is queried or implied to have confirmed the date.

`capability-catalog.json` inventories the reviewed upstream state, events,
conditions, and actions. Every entry is classified as implemented, planned, or
excluded with its source, scope, and rationale. Contract tests enforce that
only implemented entries appear in the manifest, entities, commands, and
behavior contract.

Provider-specific schedule syncing remains planned until source adapters,
normalization, polling behavior, and executable tests exist. Provider-side
schedule mutation and unsafe arbitrary fetch or template execution are outside
this integration's boundary.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-waste-collection:0.1.0 .
docker run --rm -p 4205:4205 docker.io/piphinetwork/piphi-network-waste-collection:0.1.0
```
