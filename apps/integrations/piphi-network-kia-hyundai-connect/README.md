# Piphi Network Kia Hyundai Connect

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_kia_hyundai_connect.main:app --reload --port 4217
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4217` by default and exposes the common PiPhi runtime route contract:

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

`capability-catalog.json` inventories the reviewed account, region, vehicle
body, powertrain, charging, climate, location, maintenance, remote-command,
and privacy surfaces. Every entry is classified as implemented, planned, or
excluded, and contract tests ensure that only implemented entries are
advertised.

Vehicle features remain planned until brand/region adapters, permission and
subscription negotiation, rate-limit handling, privacy controls, model
fixtures, and confirmation-protected remote commands exist. The starter
runtime currently exposes only connectivity and refresh.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-kia-hyundai-connect:0.1.0 .
docker run --rm -p 4217:4217 docker.io/piphinetwork/piphi-network-kia-hyundai-connect:0.1.0
```
