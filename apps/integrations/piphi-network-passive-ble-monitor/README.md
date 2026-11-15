# PiPhi Network Passive BLE Monitor

Read-only BTHome v2 integration for the authenticated PiPhi BLE gateway v1 API. The integration never owns an adapter, imports Bleak/BlueZ, receives a raw address or name, or exposes an ambient device inventory. A user must explicitly configure an opaque gateway `device_handle`.

## Supported slice

- Unencrypted BTHome v2 battery, temperature, and humidity objects
- RSSI supplied by `piphi.ble.observation.v1`
- Packet-ID deduplication and malformed-packet isolation
- Ordered cursors, bounded pages/backoff, snapshot resync, and replay-safe restart behavior
- Separate `receiver_healthy`, `observation_fresh`, and `sensor_available` state
- Last good measurements retained with `last_measurement_at` and `measurement_age_seconds`

Encrypted advertisements, arbitrary vendor formats, active BLE sessions, GATT, and raw payload diagnostics are deliberately excluded.

## Configuration

```json
{
  "id": "living-room-bthome",
  "gateway_url": "https://ble-gateway.local:4210",
  "gateway_token": "secret bearer token",
  "device_handle": "ble_c7f2a1b9000000000000000000000000",
  "alias": "Living room sensor",
  "poll_interval_seconds": 10,
  "stale_after_seconds": 180
}
```

The configured token is a per-consumer capability credential used for registration,
reads, snapshots, and deletion; it grants no gateway-wide administration. It is
never returned in entities, telemetry, events, health, or diagnostics. Registration
requests only the configured handle and BTHome service UUID.

## Runtime and portability

The HTTP consumer is pure async Python/httpx and has no OS-specific imports, so source execution is platform-neutral. The manifest remains Linux-only because this repository currently publishes only Linux OCI images (`linux/amd64` and `linux/arm64`); it has no native Windows runtime artifact. Windows can be declared once root release metadata can build and qualify one. The gateway may run elsewhere on the network.

## Validation

```bash
PDM_IGNORE_ACTIVE_VENV=1 pdm install -G dev
PDM_IGNORE_ACTIVE_VENV=1 pdm run pytest
PDM_IGNORE_ACTIVE_VENV=1 pdm run python scripts/validate.py
docker build -t ghcr.io/piphi-io/piphi-network-passive-ble-monitor:0.3.0 .
```

`piphi-app.json` opts this package into full CI, dependency audit, tests, package validation, and portable Linux image builds. `capability-catalog.json` is the machine-readable capability inventory.

## Gateway v1 assumptions

- Bearer authentication is required for every request; the same per-consumer capability token authorizes registration and reads without granting gateway administration.
- Pages use `{observations, cursor, gap, receiver_healthy}`; snapshots additionally report receiver topology/health metadata.
- Sequence numbers are monotonic. HTTP 409 or `gap: true` triggers snapshot resync; numeric jumps alone do not, because sequences may be gateway-global.
- Snapshot observations are marked `replayed`; this consumer also treats the entire snapshot as non-live.
- Hex maps are bounded to 32 entries and 255 bytes per value.
- Matcher categories must be conjunctive: the device-handle and BTHome UUID scopes together define the authorized stream. The consumer still drops any non-matching handle and non-BTHome service data defensively.
- Poll and snapshot pages must report `receiver_healthy`; absence is treated as unhealthy rather than guessed healthy.
