# Piphi Network Passive Ble Monitor

Draft PiPhi integration runtime. It contains a read-only BTHome v2 decoder and
Bleak scan pipeline for configured BLE addresses. An actual advertisement is
required before the sensor becomes connected; configuration alone never
fabricates measurements. Encrypted advertisements and unrecognized object IDs
are not decoded.

The runtime advertises the BTHome v2 fields it already decodes and validates:
temperature, humidity, battery level, and RSSI. Its bundled dashboard experience
renders those readings in one compact overview; connection remains available to
Core for runtime health and error handling.

The Core container does not yet have an approved BlueZ access path. Mounting
the host system D-Bus socket would expose more host IPC than BLE alone, so the
manifest intentionally does not request it. Run this code on a trusted Linux
host with BlueZ for development, or use deterministic scan fixtures in tests;
do not promote this draft as a Core-deployable BLE receiver until the host
access decision and live-device checks are complete.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_passive_ble_monitor.main:app --reload --port 4204
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4204` by default and exposes the common PiPhi runtime route contract:

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

Additional device-specific capabilities remain planned until advertisement
decoding, normalization, and executable tests exist. This integration does not
take ownership of the host adapter.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-passive-ble-monitor:0.2.0 .
docker run --rm -p 4204:4204 docker.io/piphinetwork/piphi-network-passive-ble-monitor:0.2.0
```
