# Piphi Network Openepaperlink

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_openepaperlink.main:app --reload --port 4219
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4219` by default and exposes the common PiPhi runtime route contract:

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

The first live widget shows configured-tag and pending-transfer counts from a
local OpenEPaperLink access point. Configure a private IP address or a `.local`
or `.lan` hostname. The runtime reads the paginated `GET /get_db` endpoint,
polls at a bounded interval, and reports disconnected when that read fails.
No tag MAC addresses or content are sent to Core. The AP uses local HTTP, so
this read-only integration should run on a trusted home network. The source
for that endpoint is the upstream [tag database implementation](https://github.com/OpenEPaperLink/OpenEPaperLink/blob/master/ESP32_AP-Flasher/src/tag_db.cpp).

`capability-catalog.json` inventories OpenEPaperLink access-point health,
per-tag radio and battery state, display transfers, rendering, optional LEDs,
buzzers, NFC and GPIO, scheduling, maintenance, and safety boundaries. Each
candidate is classified as implemented, planned, or excluded, and contract
tests prevent unimplemented features from being advertised.

Tag features remain planned until AP transport, firmware and tag-type
negotiation, rendering fixtures, bounded transfer queues, and representative
hardware tests exist. Tag-specific controls are not advertised by this AP
summary widget.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-openepaperlink:0.1.0 .
docker run --rm -p 4219:4219 docker.io/piphinetwork/piphi-network-openepaperlink:0.1.0
```
