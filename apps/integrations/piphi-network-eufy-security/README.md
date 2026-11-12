# Piphi Network Eufy Security

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_eufy_security.main:app --reload --port 4210
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4210` by default and exposes the common PiPhi runtime route contract:

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

## Capability coverage and sidecar boundary

`capability-catalog.json` inventories stations, security modes, cameras,
doorbells, locks, sensors, diagnostics, commands, and model gates. Entries are
classified as implemented, planned, or excluded, and contract tests prevent
planned or unsafe features from being advertised.

This integration owns Eufy entities and normalized state. A managed
`eufy-security-ws` sidecar owns account/P2P transport, while the shared media
broker owns WebRTC delivery. Raw credentials, messages, and stream URLs never
enter PiPhi state.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-eufy-security:0.1.0 .
docker run --rm -p 4210:4210 docker.io/piphinetwork/piphi-network-eufy-security:0.1.0
```
