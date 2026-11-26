# Managed BLE gateway consumer contract

Production transport is `gateway.py`; it has no local-radio code. Version `0.4.1` requires sidecar `>=0.4.0,<0.5.0`. Registration uses a per-consumer bearer credential and is limited to one consented opaque handle, the BTHome UUID `0000fcd2-0000-1000-8000-00805f9b34fb`, passive mode, and an optional bind key scoped to that same handle. Handle and service matcher categories are conjunctive.

Accepted observations use schema `piphi.ble.observation.v1` and include sequence, opaque device handle, receiver identity/kind, receiver-monotonic observation time, ingest timestamp, replay marker, RSSI, optional Tx power, connectability, address classification, service UUIDs, and bounded hex maps. Unknown top-level fields are forward-compatible. Invalid observations are counted and isolated.

Only BTHome `service_data` is decoded. Encrypted service data is authenticated and decrypted by the sidecar because the parent never receives the raw nonce identity. No raw address, device name, bind key, advertisement dump, credential, or token is admitted to persisted state, public state, telemetry, events, diagnostics, or logs.

`/health` is the only unauthenticated runtime route. Core runtime authentication protects every other parent and sidecar operational route; the consumer API additionally requires its bearer token. Configuration generations probe before commit, roll back on failure, and are rehydrated from Core after restart. The parent retains only an owner-only last-good measurement checkpoint.

Availability has three independent values:

- `receiver_healthy`: the latest gateway page reports a usable receiver.
- `observation_fresh`: a non-replayed accepted observation arrived within `stale_after_seconds`.
- `sensor_available`: both conditions are true.

Last good measurements remain visible with timestamp and age when stale. Replay and snapshot data may warm values and packet-ID dedup state but cannot establish live freshness.
