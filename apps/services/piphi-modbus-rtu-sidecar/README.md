# PiPhi Modbus RTU Sidecar

Managed serial transport for PiPhi Modbus integrations using RTU or ASCII.

This package is a managed transport helper, not a device integration. It never
creates PiPhi entities and exposes no behavior actions. The parent owns profile
semantics, entities, polling policy, and user-facing repair guidance.

## Production contract

- `/health` is the sole public route; every other route requires the dedicated `PIPHI_MODBUS_SIDECAR_TOKEN` (or Core internal-token fallback) as a Bearer token.
- Core grants exactly one selected stable `/dev/serial/by-id/...` adapter path per install. The manifest requests no directory-wide `/dev` grant and no host privilege.
- The sidecar independently verifies the canonical serial profile digest/signature with `PIPHI_MODBUS_PROFILE_TRUST_ANCHOR` before opening a bus.
- Writes remain disabled unless the parent passes `writes_enabled=true`; profile point IDs, ranges, confirmation, and read-back still apply.
- Readiness means every configured bus is open and at least one allow-listed unit has answered. Liveness exposes no adapter path or profile details.
- Configuration replacement is probe-before-swap, removal closes the descriptor, Core snapshots restore buses after restart, and bounded queues reject saturation without replaying writes.
- Deterministic fakes and PTYs cover RTU/ASCII framing, CRC/LRC failures, malformed frames, timeouts, reconnects, backpressure, and cleanup. No physical qualification is claimed.

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

`docs/testing.md` maps the Home Assistant-inspired test architecture onto the
sidecar's HTTP, PTY, lifecycle, and backpressure boundaries.

The authenticated parent may issue FC15 only as an ordered list of stable
profile point IDs and boolean values. The sidecar re-resolves every point,
requires one unit and a contiguous writable coil range, confirms the protocol
response, and reads every coil back. Addresses, units, function overrides, raw
frames, broadcasts, and sidecar-owned pulse timing are not exposed.

Managed deployment is internal-only and Core grants one exact stable
`/dev/serial/by-id/...` device path to the container.
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

`/command` is retained for runtime-contract compatibility but returns `404`:
the sidecar advertises and accepts no entity commands.

## Manifest

`manifest.json` declares the transport helper contract, an empty entity and
command surface, hardened container settings, persistent state, and no static
serial-device mapping. Core must grant one exact stable
`/dev/serial/by-id/...` device path for each install.

## Docker

```bash
docker build -t ghcr.io/piphi-io/piphi-modbus-rtu-sidecar:0.8.1 .
docker run --rm --read-only --tmpfs /tmp --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --device /dev/serial/by-id/DEVICE:/dev/serial/by-id/DEVICE \
  -e PIPHI_ENV=production \
  -e PIPHI_MODBUS_SIDECAR_TOKEN=replace-with-a-local-test-token \
  -e PIPHI_MODBUS_PROFILE_TRUST_ANCHOR=replace-with-a-local-test-anchor \
  ghcr.io/piphi-io/piphi-modbus-rtu-sidecar:0.8.1
```
