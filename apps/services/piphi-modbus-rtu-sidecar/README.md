# PiPhi Modbus RTU Sidecar

Managed serial transport for PiPhi Modbus integrations using RTU or ASCII.

## Ownership boundary

The sidecar owns allow-listed serial ports, exclusive bus access, RTU/ASCII
framing, CRC/LRC and response validation, one-in-flight request arbitration,
bounded queues, backpressure, reconnect, and restart reconciliation. Parent
integrations own register profiles, decoded device state, entities, telemetry,
and behaviors. The sidecar does not interpret arbitrary registers.

The machine-readable `capability-catalog.json` covers line settings, framing,
timing, request routing, queueing, recovery, and deliberately excluded raw or
unrestricted operations. Profile-declared reads and writes, confirmed read-back,
sanitized event replay, and bounded recovery are implemented. Snapshots include
queue depth/capacity/high-water mark, poll duration, reconnect, timeout, CRC,
LRC and transport-error counters, plus per-unit last-success and consecutive-error
health; serial paths, credentials, and raw frames remain redacted.

The authenticated parent may issue FC15 only as an ordered list of stable
profile point IDs and boolean values. The sidecar re-resolves every point,
requires one unit and a contiguous writable coil range, confirms the protocol
response, and reads every coil back. Addresses, units, function overrides, raw
frames, broadcasts, and sidecar-owned pulse timing are not exposed.

Managed deployment is internal-only and maps `/dev/serial` into the container.
The service runs with production authentication enabled and accepts only the
shared internal token injected by PiPhi Core. The parent Modbus integration
auto-installs the compatible sidecar release and never stores this token in a
device profile.

Profile values support booleans, signed and unsigned 16-, 32-, and 64-bit
integers, `float16`, `float32`, `float64`, bounded fixed strings, reviewed enum labels, and
read-only bitfields. Multi-register values use explicit `ABCD`, `BADC`, `CDAB`,
or `DCBA` byte/word policies; no executable unpack format is accepted.
Exact invalid raw vectors, bounded read clamping, and decimal precision are
profile-owned. Invalid/non-finite reads become unavailable, and writes cannot
encode an invalid sentinel or bypass range and precision constraints.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_modbus_rtu_sidecar.main:app --reload --port 4212
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4212` by default and exposes the common PiPhi runtime route contract:

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
docker build -t ghcr.io/piphi-io/piphi-modbus-rtu-sidecar:0.7.0 .
docker run --rm --device /dev/serial:/dev/serial \
  -e PIPHI_ENV=production \
  -e PIPHI_MODBUS_SIDECAR_TOKEN=replace-with-a-local-test-token \
  -p 4212:4212 ghcr.io/piphi-io/piphi-modbus-rtu-sidecar:0.7.0
```
