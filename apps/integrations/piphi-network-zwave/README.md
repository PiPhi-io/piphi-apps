# Piphi Network Zwave

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_zwave.main:app --reload --port 4221
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4221` by default and exposes the common PiPhi runtime route contract:

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

`capability-catalog.json` inventories the Z-Wave JS driver, controller,
network, node interviews, value metadata, command classes, specialized device
controls, network administration, and managed-sidecar behavior. Each candidate
is classified as implemented, planned, or excluded, and contract tests prevent
unimplemented features from being advertised.

Node capabilities remain planned until the managed Z-Wave JS connection,
command-class and endpoint negotiation, value bounds, supervision, security,
sleeping-node behavior, transition fixtures, and administrative confirmations
exist. Network keys, raw serial traffic, and arbitrary API/value writes are
explicitly excluded.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-zwave:0.1.0 .
docker run --rm -p 4221:4221 docker.io/piphinetwork/piphi-network-zwave:0.1.0
```
