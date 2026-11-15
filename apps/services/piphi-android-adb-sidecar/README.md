# PiPhi Android ADB Sidecar

Draft Android Debug Bridge sidecar for PiPhi Android integrations. No ADB
binary, authenticated device transport, USB path, or command execution exists
yet.

## Ownership boundary

The sidecar is intended to own the local ADB server, Platform Tools
compatibility, USB and wireless transport, pairing handoff, target selection,
bounded command queues, backpressure, and restart recovery. Parent integrations own Android device
entities, normalized state, telemetry, behaviors, and widgets. Arbitrary shell,
file, package, forwarding, privilege, and multi-device commands are excluded.

The machine-readable `capability-catalog.json` covers ADB server and device
lifecycle, wireless pairing, safe parent operations, queues, recovery, and
explicit unsafe boundaries. The starter currently reports only an explicitly
unavailable `connected` state and configuration lifecycle events.

`parent_contract_v1.py` defines the implemented transport-independent message
boundary. It requires one opaque target ID, bounds payloads/timeouts/repeats,
allows only conservative key events and property queries, rejects extra or
duplicate fields, and exposes only `unauthorized`, `offline`, `timeout`,
`queue_full`, and `unsupported` errors. The contract does not execute ADB and
is not advertised as a working command endpoint yet.

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
docker build -t ghcr.io/piphi-io/piphi-android-adb-sidecar:0.2.0-rc.1 .
docker run --rm -p 4213:4213 ghcr.io/piphi-io/piphi-android-adb-sidecar:0.2.0-rc.1
```
