# Piphi Network Knx

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_knx.main:app --reload --port 4223
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4223` by default and exposes the common PiPhi runtime route contract:

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

`capability-catalog.json` inventories KNX/IP transport, project imports, group
objects, datapoint types and flags, lighting, shading, climate, metering,
security signals, and managed transport behavior. Each candidate is
implemented, planned, or excluded, and contract tests prevent unsupported
group writes from being advertised.

Protocol features remain planned until project and DPT metadata, paired state
and command addresses, KNX Secure handling, telegram deduplication, and
representative installation fixtures exist. Arbitrary telegrams and ETS-style
device programming are explicitly excluded.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-knx:0.1.0 .
docker run --rm -p 4223:4223 docker.io/piphinetwork/piphi-network-knx:0.1.0
```
