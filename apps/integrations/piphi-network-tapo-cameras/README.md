# Piphi Network Tapo Cameras

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_tapo_cameras.main:app --reload --port 4207
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4207` by default and exposes the common PiPhi runtime route contract:

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

`capability-catalog.json` inventories the reviewed camera state, detections,
events, conditions, controls, media-broker responsibilities, and model gates.
Every entry is classified as implemented, planned, or excluded. Contract tests
enforce that only implemented entries are advertised.

Camera features remain planned until local discovery, authentication, ONVIF or
RTSP negotiation, brokered WebRTC sessions, and representative model fixtures
exist. Raw authenticated stream URLs never enter PiPhi state; the shared media
sidecar owns transcoding and WebRTC lifecycle.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-tapo-cameras:0.1.0 .
docker run --rm -p 4207:4207 docker.io/piphinetwork/piphi-network-tapo-cameras:0.1.0
```
