# Managed BLE gateway consumer contract

Production transport is `gateway.py`; it has no local-radio code. Registration uses an admin bearer credential to install a random consumer credential and is limited to one consented opaque handle, the BTHome UUID `0000fcd2-0000-1000-8000-00805f9b34fb`, and passive mode. Handle and service matcher categories are required to be conjunctive.

Accepted observations use schema `piphi.ble.observation.v1` and include sequence, opaque device handle, receiver identity/kind, receiver-monotonic observation time, ingest timestamp, replay marker, RSSI, optional Tx power, connectability, address classification, service UUIDs, and bounded hex maps. Unknown top-level fields are forward-compatible. Invalid observations are counted and isolated.

Only BTHome `service_data` is decoded. No raw address, device name, advertisement dump, credential, or token is admitted to public state, telemetry, events, diagnostics, or logs.

Availability has three independent values:

- `receiver_healthy`: the latest gateway page reports a usable receiver.
- `observation_fresh`: a non-replayed accepted observation arrived within `stale_after_seconds`.
- `sensor_available`: both conditions are true.

Last good measurements remain visible with timestamp and age when stale. Replay and snapshot data may warm values and packet-ID dedup state but cannot establish live freshness.
