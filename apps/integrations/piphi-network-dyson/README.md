# Piphi Network Dyson

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_dyson.main:app --reload --port 4216
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4216` by default and exposes the common PiPhi runtime route contract:

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

`capability-catalog.json` inventories the reviewed Dyson identity, local MQTT
transport, air-quality sensing, fan and oscillation controls, heating,
humidification, filters, faults, and safety boundaries. Every entry is
classified as implemented, planned, or excluded, and contract tests ensure
that only implemented entries are advertised.

Appliance features remain planned until product-type discovery, local
credential bootstrap, sanitized MQTT transport, model fixtures, and bounded
command tests exist. The starter runtime currently exposes only connectivity
and refresh.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-dyson:0.1.0 .
docker run --rm -p 4216:4216 docker.io/piphinetwork/piphi-network-dyson:0.1.0
```
