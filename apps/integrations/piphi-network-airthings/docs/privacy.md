# Airthings Consumer Cloud privacy

This integration connects to the official Airthings Consumer API with credentials
supplied by the user. It accesses only the explicitly selected account and device.

## Data accessed

- Airthings account membership, solely to verify the selected account.
- Device identifiers and supported sensor capabilities, solely to resolve the
  selected device to a stable privacy-safe reference.
- Latest air-quality measurements and their source observation timestamps.

## Data handling

Credentials, account IDs, serial numbers, device names, homes, segments, raw
provider payloads, access tokens, and upstream response bodies are kept inside
the configuration/provider boundary. Credential and provider-selection values
are held as secret types in a dedicated in-memory store, and cached provider
tokens are purged on credential rotation and removal. They are not emitted through state,
telemetry, events, diagnostics, discovery output, logs, or errors.

PiPhi exposes a deterministic opaque `device_ref` instead of the provider serial
number. The runtime retains the last successful normalized measurements during
an outage with explicit unavailable and stale state. It does not retain raw
provider responses.

## Network access and deletion

The integration makes outbound HTTPS requests to Airthings OAuth and Consumer
API endpoints. Removing the PiPhi configuration stops polling and removes the
runtime's in-memory credentials and provider identifiers. Airthings account and
device data remain governed by the user's Airthings account and Airthings privacy
terms.

The runtime keeps one normalized last-good state per configured device, a bounded
48-hour derived mold-risk window for supported Wave Mini devices, aggregate poll
timestamps, and the Runtime SDK's bounded recent-event history. It does not retain
raw provider payloads or provider history. Core's mounted configuration snapshot
is the restart source of truth and remains on the runtime's dedicated writable
volume; the container root filesystem is read-only.

Security or privacy reports can be sent to `support@piphi.io`.
