# PiPhi Android ADB Sidecar

Managed Android Debug Bridge transport for PiPhi Android integrations.

## Ownership boundary

The sidecar owns the local ADB server, Platform Tools compatibility, USB and
wireless transport, pairing handoff, target selection, bounded command queues,
backpressure, and restart recovery. Parent integrations own Android device
entities, normalized state, telemetry, behaviors, and widgets. Arbitrary shell,
file, package, forwarding, privilege, and multi-device commands are excluded.

The machine-readable `capability-catalog.json` covers ADB server and device
lifecycle, wireless pairing, safe parent operations, queues, recovery, and
explicit unsafe boundaries. Only `connected` and `refresh` are implemented in
this starter.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_android_adb_sidecar.main:app --reload --port 4213
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4213` by default and exposes the common PiPhi runtime route contract:

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

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-android-adb-sidecar:0.1.1 .
docker run --rm -p 4213:4213 docker.io/piphinetwork/piphi-android-adb-sidecar:0.1.1
```
