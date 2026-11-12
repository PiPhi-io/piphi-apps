# Piphi Network Midea Ac Lan

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_midea_ac_lan.main:app --reload --port 4208
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4208` by default and exposes the common PiPhi runtime route contract:

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

`capability-catalog.json` inventories the reviewed climate state, optional
features, energy and diagnostic telemetry, compatible appliance profiles,
events, conditions, actions, and protocol variants. Every entry is classified
as implemented, planned, or excluded. Contract tests enforce that only
implemented entries are advertised.

The common 0xAC climate profile now includes local power, HVAC mode, target
temperature, device-reported fan and swing modes, and comfort presets. Fan and
swing commands fail closed when the appliance does not advertise the selected
option. The dashboard's HVAC action is an estimate derived from power, mode,
room temperature, target temperature, and a 0.5 °C deadband; it is not direct
compressor telemetry. Tokens, keys, arbitrary attributes, and raw protocol
commands are never exposed through the runtime contract.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-midea-ac-lan:0.3.0 .
docker run --rm -p 4208:4208 docker.io/piphinetwork/piphi-network-midea-ac-lan:0.3.0
```
