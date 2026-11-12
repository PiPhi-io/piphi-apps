# Piphi Network Android Tv

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_android_tv.main:app --reload --port 4220
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4220` by default and exposes the common PiPhi runtime route contract:

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

`capability-catalog.json` inventories Android TV, Google TV, and Fire TV
identity, power, audio, applications, playback, navigation, inputs, privacy,
and managed-ADB-sidecar operations. Each candidate is classified as
implemented, planned, or excluded, and contract tests prevent unimplemented
features from being advertised.

Device controls remain planned until platform detection, ADB authorization,
sidecar queue and reconnect behavior, allow-listed keys and applications,
privacy controls, and representative device fixtures exist. Arbitrary shell,
intent, package, and filesystem access is explicitly excluded.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-android-tv:0.1.0 .
docker run --rm -p 4220:4220 docker.io/piphinetwork/piphi-network-android-tv:0.1.0
```
