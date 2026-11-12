# Piphi Network Washdata

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_washdata.main:app --reload --port 4211
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4211` by default and exposes the common PiPhi runtime route contract:

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

`capability-catalog.json` inventories appliance cycles, phases, program
matching, estimates, energy and cost, profiles, maintenance, learning, events,
conditions, and administrative operations. Contract tests enforce that only
implemented entries are advertised.

WashData is monitoring-first. Physical appliance power control is excluded.
Cycle events will require baseline-aware transitions, debounce, persistent
ghost-cycle suppression, restart recovery, and deduplication before being
promoted from planned status.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-washdata:0.1.0 .
docker run --rm -p 4211:4211 docker.io/piphinetwork/piphi-network-washdata:0.1.0
```
