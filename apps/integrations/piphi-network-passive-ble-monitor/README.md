# PiPhi Network Passive BLE Monitor

Read-only BTHome v2 integration for the authenticated PiPhi BLE gateway v1 API. The integration never owns an adapter, imports Bleak/BlueZ, receives a raw address or name, or exposes an ambient device inventory. A user must explicitly configure an opaque gateway `device_handle`.

## Supported slice

- Authenticated BTHome v2 battery, temperature, and humidity objects, including optional encrypted advertisements mediated by the gateway
- RSSI supplied by `piphi.ble.observation.v1`
- Packet-ID deduplication and malformed-packet isolation
- Ordered cursors, bounded pages/backoff, snapshot resync, and replay-safe restart behavior
- Separate `receiver_healthy`, `observation_fresh`, and `sensor_available` state
- Last good measurements retained with `last_measurement_at` and `measurement_age_seconds`

Arbitrary vendor formats, active BLE sessions, GATT, and raw payload diagnostics are deliberately excluded. An encrypted BTHome bind key is accepted only as a secret; the sidecar decrypts the scoped advertisement while it still has the nonce identity, and neither runtime persists or diagnoses the plaintext key.

## Configuration

```json
{
  "id": "living-room-bthome",
  "gateway_url": "https://ble-gateway.local:4210",
  "gateway_token": "secret bearer token",
  "device_handle": "ble_c7f2a1b9000000000000000000000000",
  "bind_key": "00112233445566778899aabbccddeeff",
  "alias": "Living room sensor",
  "poll_interval_seconds": 10,
  "stale_after_seconds": 180
}
```

The configured token is a per-consumer capability credential used for registration,
reads, snapshots, and deletion; it grants no gateway-wide administration. It is
never returned in entities, telemetry, events, health, or diagnostics. Registration
requests only the configured handle and BTHome service UUID.
`bind_key` is optional, must be exactly 16 bytes encoded as hexadecimal, and is recursively redacted with the gateway token.

Configuration is committed only after gateway registration and a bounded
snapshot succeed. Reusing the same stable configuration ID updates that entry
rather than creating a duplicate.

## Installation and removal

Installing version `0.4.0` auto-installs the compatible
`piphi-ble-gateway-sidecar >=0.4.0,<0.5.0`. Core places both services on one
private application network, resolves the sidecar as
`http://piphi-ble-gateway-sidecar:4210`, and provisions a distinct high-entropy
consumer bearer token. The sidecar is shared; this parent never receives host
Bluetooth or D-Bus access.

Install the OCI package through PiPhi, ensure the managed BLE gateway is healthy,
then use `/ui-config` to enter the gateway URL, per-consumer token, opaque device
handle, polling interval, and stale timeout. Setup verifies registration before
the entry is stored.

Remove the configuration through PiPhi before uninstalling the image. Removal
unregisters the gateway consumer, stops polling, closes the HTTP client, and
removes runtime state. If the gateway is temporarily unavailable, local cleanup
still completes and the failed remote deletion is logged without exposing the
token.

Core mounts `/var/lib/piphi/passive-ble-monitor` at
`/var/lib/piphi/passive-ble` for the owner-only last-good checkpoint and
automation ledger. The image runs as UID/GID `65532`, with a read-only root
filesystem; the host directory must be owned by that identity and mode `0700`.
On Core restart, configurations are rehydrated transactionally and the persisted
last-good state is restored as stale until a live advertisement arrives.

## Automation

The integration exposes the idempotent `refresh` action and the `state_matches`
condition. `runtime.config.applied` is the only public behavior event in the
current slice; no measurement-change trigger is advertised. Refresh failures are
reported as action failures rather than fabricated sensor updates.

## Troubleshooting and limitations

- `receiver_healthy=false` means the gateway path is degraded;
  `sensor_available=false` means no fresh usable measurement is available.
- Cursor gaps trigger a bounded snapshot resync. Replay warms state but never
  counts as a live observation.
- Verify that the configured handle is opaque, the token is scoped to this
  consumer, and the advertiser includes authenticated BTHome v2 service data.
- Only battery, temperature, humidity, and RSSI are currently supported. Other
  BTHome measurements remain unadvertised until authoritative fixtures and
  capability negotiation cover them.
- A shared adapter has one effective scan plan. Other host BLE software can
  change BlueZ discovery state or consume radio time, reducing observation
  reliability; no room, device model, radio, antenna, or adapter has been
  physically qualified by this software-only workstream.
- `/health` is the sole public route. Every other runtime route requires Core's
  internal token; gateway calls independently require the scoped bearer token.

## Runtime and portability

The HTTP consumer is pure async Python/httpx and has no OS-specific imports, so source execution is platform-neutral. The manifest remains Linux-only because this repository currently publishes only Linux OCI images (`linux/amd64` and `linux/arm64`); it has no native Windows runtime artifact. Windows can be declared once root release metadata can build and qualify one. The gateway may run elsewhere on the network.

## Validation

```bash
PDM_IGNORE_ACTIVE_VENV=1 pdm install -G dev
PDM_IGNORE_ACTIVE_VENV=1 pdm run pytest
PDM_IGNORE_ACTIVE_VENV=1 pdm run python scripts/validate.py
docker build -t ghcr.io/piphi-io/piphi-network-passive-ble-monitor:0.4.0 .
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
