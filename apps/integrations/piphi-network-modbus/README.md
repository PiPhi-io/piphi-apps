# Piphi Network Modbus

PiPhi Modbus TCP runtime. The implemented slice is intentionally narrow: it
reads one configured, zero-based holding-register address (function code 03)
from one local endpoint and exposes the raw unsigned 16-bit value. It never
sends Modbus write commands, probes arbitrary addresses, or guesses a device's
scale, unit, or meaning.

Set `host` to a private/local IP (optionally `:port`) or `.local`/`.lan` name,
`register_address` to the device's documented zero-based register address,
and optionally `unit_id` (default 1). The integration polls at least every 60
seconds. An unsuccessful read reports disconnected; it does not fabricate a
reading. Modbus TCP is unencrypted, so use only a trusted local network.

The bundled declarative Widget SDK card displays the raw register value and
offers details/history. A Modbus TCP simulator can serve a documented register
at the configured address for end-to-end testing; the same configuration and
read path work with a real device.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_modbus.main:app --reload --port 4222
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4222` by default and exposes the common PiPhi runtime route contract:

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

`capability-catalog.json` inventories Modbus transports, units, profiles,
coils, discrete inputs, registers, types, diagnostics, polling quality, and a
managed RTU gateway boundary. Each candidate is implemented, planned, or
excluded, and contract tests prevent unsupported register operations from
being advertised.

The single configured register read is implemented. Semantic profiles,
derived units/types, batching, retry policy, and safe writes remain planned.
Arbitrary addresses, PDUs, broadcasts, and serial devices are explicitly
excluded.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-modbus:0.1.0 .
docker run --rm -p 4222:4222 docker.io/piphinetwork/piphi-network-modbus:0.1.0
```
