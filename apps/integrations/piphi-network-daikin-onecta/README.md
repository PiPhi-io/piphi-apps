# Piphi Network Daikin Onecta

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_daikin_onecta.main:app --reload --port 4215
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4215` by default and exposes the common PiPhi runtime route contract:

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

`capability-catalog.json` inventories climate zones, Altherma heating and hot
water, air purification, energy, diagnostics, OAuth lifecycle, cloud health,
events, conditions, and safe controls. Tests enforce that only implemented
capabilities are advertised.

Device capabilities will be negotiated from management points, writable
ranges, model classes, and account permissions. OAuth secrets, arbitrary API
writes, device enrollment, and firmware administration are excluded.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-daikin-onecta:0.1.0 .
docker run --rm -p 4215:4215 docker.io/piphinetwork/piphi-network-daikin-onecta:0.1.0
```
