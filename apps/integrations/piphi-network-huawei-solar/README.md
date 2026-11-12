# Piphi Network Huawei Solar

This runtime currently supports a narrow, read-only SUN2000 Modbus TCP view:
inverter active power (register 32080, signed I32 W) and daily generated
electricity (register 32114, unsigned U32 / 100 kWh). These addresses and
types come from Huawei's Solar Inverter Modbus Interface Definitions V3.0.
Only models exposing both registers are supported by this slice. Configure a
local `host` (optionally `:port`) and `unit_id` (default 1). The runtime never
assumes that configured means connected; unsuccessful reads report unavailable.
Modbus TCP is unencrypted, so use a trusted local network. The bundled
declarative widget shows only those two values and offers details/history, not
write controls.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_huawei_solar.main:app --reload --port 4213
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

## Capability coverage

`capability-catalog.json` inventories inverter, PV string, meter, grid,
battery, optimizer, elevated control, and Modbus transport capabilities. Each
entry is implemented, planned, or excluded, and tests prevent planned register
features from leaking into the advertised runtime contract. Active inverter
power and daily generated energy are implemented; meter, battery, optimizer,
control, and model-specific diagnostics remain planned.

Capabilities will be negotiated by inverter model, firmware, unit ID,
installed subdevices, transport, and write permission. Raw register access and
unsafe protection changes are excluded.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-huawei-solar:0.1.0 .
docker run --rm -p 4213:4213 docker.io/piphinetwork/piphi-network-huawei-solar:0.1.0
```
