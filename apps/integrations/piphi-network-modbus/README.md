# Piphi Network Modbus

PiPhi Modbus runtime for reviewed semantic profiles over local Modbus TCP and
the authenticated RTU sidecar. Profiles declare exact units, areas, addresses,
types, byte/word order, scaling, bounds, and writability. The runtime reads
coils, discrete inputs, input registers, and holding registers; exposes typed
entities; and permits only named, bounded writes with protocol confirmation and
read-back.

For TCP, set `host` to a private/local IP (optionally `:port`) or
`.local`/`.lan` name and provide `points`. Compatible adjacent points are read
in one bounded request without crossing unit or data-area boundaries. The
connection is reused, serialized, and re-established once after a failed read.
An unsuccessful block marks only its points unavailable. Modbus TCP is
unencrypted, so use only a trusted local network.

The original `register_address` plus optional `unit_id` configuration remains
supported for compatibility as a read-only unsigned holding-register entity.

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

Semantic profiles, typed FC01/02/03/04 reads, contiguous TCP batching,
persistent serialized TCP sessions, bounded reconnect, and constrained
FC05/06/16 writes are implemented. Arbitrary addresses, raw PDUs, broadcasts,
and untrusted profiles remain excluded.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t ghcr.io/piphi-io/piphi-network-modbus:0.3.0 .
docker run --rm -p 4222:4222 ghcr.io/piphi-io/piphi-network-modbus:0.3.0
```
