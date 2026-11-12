# PiPhi TP-Link Kasa Integration

PiPhi integration for TP-Link Kasa devices over the local network.

This runtime uses `python-kasa` for device discovery, polling, and command
execution, and now installs the published Python runtime kit directly from
PyPI.

## What this integration does

- discovers local TP-Link Kasa devices
- supports optional authenticated discovery inputs for devices that require account credentials
- applies and rehydrates PiPhi configs through `/config`, `/configs/sync`, and `/config/sync`
- polls device state on a background loop
- exposes entities, state, events, commands, and UI config endpoints
- delivers telemetry and events to PiPhi Core through `piphi-runtime-kit-python`
- pairs four integration-owned dashboard experiences: Device Control, Energy Monitor, Smart Plug, and Environment Monitor

The declared local-device scope is implementation-complete and enforced by
`capabilities/device_matrix.json`. The automated runtime, simulator, command,
and widget-package checks pass; validation across representative physical
devices remains an explicit pre-GA gate.

## Runtime SDK and testkit

- runtime SDK: `piphi-runtime-kit-python==0.8.1`
- test helper during development: `piphi-runtime-testkit-python==0.1.4`

The runtime kit and testkit are installed from PyPI, so CI and release installs
do not require sibling repository checkouts.

## Local development

Install dependencies:

```bash
pdm install -G dev
```

Run the runtime:

```bash
pdm run python -m piphi_network_tp_link.app
```

Run tests:

```bash
pdm run pytest -q
```

Validate the deterministic signed experience package without a release key:

```bash
pdm run python scripts/build_experience.py --check
```

The package source lives in `experiences/kasa-smart-home/`. Control widgets run
inside the Widget SDK sandbox and can only execute the explicitly allow-listed
Kasa commands after Core grants `host.executeCommand`. Energy and environment
widgets use Core's declarative renderer. All four keep Core-owned typography, shell,
layout, themes, source binding, and more-info/history interactions.

The integration API defaults to `http://127.0.0.1:3666`.

## Important routes

- `GET /health`
- `POST /discover`
- `GET /entities`
- `GET /state`
- `POST /command`
- `POST /config`
- `POST /configs/sync`
- `POST /config/sync`
- `POST /deconfigure`
- `GET /ui-config`
- `GET /events`
- `GET /manifest.json`

## Discovery notes

Discovery can run without account credentials for many local-network devices.
For models or firmware that require authenticated discovery, the manifest now
supports these optional inputs:

- `username`
- `password`

Those values are meant to be provided by the PiPhi UI, not hardcoded in source
control.

Automatic discovery scans each physical private IPv4 network independently.
This keeps a VPN or another default route from swallowing the UDP discovery
broadcast. For unusual VLAN or routed-network setups, operators can provide a
comma-separated list of broadcast addresses with
`PIPHI_TP_LINK_DISCOVERY_TARGETS` (for example,
`10.0.0.255,192.168.50.255`).

## Polling behavior

Configured devices are polled on a background loop. The current steady-state
polling interval is 30 seconds, with an immediate refresh path during config
apply and some command flows.

That makes the integration gentler on devices than the earlier 10-second loop
while still keeping state reasonably fresh.

## Contract and runtime details

The runtime supports:

- startup auth/config rehydrate via `PIPHI_CONTAINER_ID` and `PIPHI_INTEGRATION_INTERNAL_TOKEN`
- both snapshot sync route shapes, `/configs/sync` and `/config/sync`
- local event storage plus Core event delivery
- telemetry delivery with the published Python runtime kit

## Project layout

- `src/manifest.json` integration manifest
- `src/behaviors.json` optional behavior metadata for PiPhi UI
- `experiences/kasa-smart-home/` integration-owned widget package and themes
- `capabilities/device_matrix.json` tested device-family and capability coverage
- `scripts/build_experience.py` deterministic package builder and signer
- `src/piphi_network_tp_link/app.py` FastAPI entrypoint
- `src/piphi_network_tp_link/contract/` PiPhi contract routes
- `src/piphi_network_tp_link/lib/` device and runtime helpers
- `tests/` integration tests using the Python testkit
