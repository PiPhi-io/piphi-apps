# Piphi Network Sonoff Lan

This runtime currently supports a narrow, read-only Sonoff DIY Mode view:
one single-channel switch's on/off state from the vendor-documented local
`POST /zeroconf/info` endpoint. Configure a local `host` (the endpoint's port
defaults to 8081) and the DIY `deviceid`. The device must be in plaintext DIY
Mode; encrypted and multi-channel variants are not advertised as compatible.
The bundled widget shows actual reported state and offers details/history,
without implying that PiPhi can control the relay yet. An unreachable or
unsupported device reports unavailable rather than a fabricated state.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_sonoff_lan.main:app --reload --port 4202
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4202` by default and exposes the common PiPhi runtime route contract:

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

The single DIY switch state is implemented. Broader eWeLink models, channel
negotiation, metering, and controls remain planned until they have executable
protocol and safety tests.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-sonoff-lan:0.1.0 .
docker run --rm -p 4202:4202 docker.io/piphinetwork/piphi-network-sonoff-lan:0.1.0
```
