# Piphi Network Android Tv

PiPhi integration runtime for Android TV Remote Protocol v2. The initial
vertical slice supports authenticated pairing, mDNS candidates, stable opaque
identity, availability, power, foreground application, volume/mute state,
refresh, and a conservative allow-list of short remote keys.

Android TV and Google TV devices require Android TV Remote Service. Fire TV is
not supported by this protocol and remains reserved for the isolated ADB
sidecar.

## Pair and configure

Pairing is an interactive, expiring flow. The six-character PIN is used once
and is never persisted or returned in state, events, logs, or diagnostics.

```bash
# 1. Display a PIN on the television.
curl -X POST http://127.0.0.1:4220/pairing/start \
  -H 'content-type: application/json' \
  -d '{"config_id":"living-room","host":"192.168.1.50"}'

# 2. Submit the displayed PIN using the returned session_id.
curl -X POST http://127.0.0.1:4220/pairing/SESSION_ID/finish \
  -H 'content-type: application/json' \
  -d '{"pin":"A1B2C3"}'

# 3. Save only after authenticated connectivity and identity are verified.
curl -X POST http://127.0.0.1:4220/config \
  -H 'content-type: application/json' \
  -d '{"id":"living-room","host":"192.168.1.50","alias":"Living Room"}'
```

Credentials are stored under `PIPHI_ANDROID_TV_CREDENTIAL_DIR` with `0700`
directories and `0600` files. Deconfiguration keeps authorization available
for a later reconfiguration. To revoke local credentials explicitly after
deconfiguring, call `DELETE /pairing/credentials/{config_id}` and also forget
the remote from the television when appropriate.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_android_tv.main:app --reload --port 4220
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4220` by default and exposes the common PiPhi runtime route contract:

- `GET /health`
- `GET /diagnostics`
- `POST /discover`
- `POST /pairing/start`
- `POST /pairing/{session_id}/finish`
- `DELETE /pairing/{session_id}`
- `DELETE /pairing/credentials/{config_id}`
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

`capability-catalog.json` inventories Android TV, Google TV, and Fire TV
identity, power, audio, applications, playback, navigation, inputs, privacy,
and managed-ADB-sidecar operations. Each candidate is classified as
implemented, planned, or excluded, and contract tests prevent unimplemented
features from being advertised.

Remote v2 pairing, authenticated connectivity, stable identity, push state,
reconnect behavior, allow-listed short keys, and privacy-safe diagnostics are
implemented. Long presses, text input, application/deep-link launch, channel
entry, broad protocol keys, and hardware qualification remain planned. Fire TV
compatibility will use a separate, isolated ADB sidecar. Arbitrary shell,
intent, package, and filesystem access is explicitly excluded.

## Limitations

- Some televisions become unavailable when powered off and cannot be woken by
  Remote v2.
- Playback status is not supplied by this protocol; PiPhi does not guess it.
- mDNS results are unverified endpoint candidates, never stable identity.
- A reset television or revoked certificate requires pairing again.
- App IDs, text, long presses, deep links, and voice are not exposed yet.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t ghcr.io/piphi-io/piphi-network-android-tv:0.2.0-rc.1 .
docker run --rm -p 4220:4220 ghcr.io/piphi-io/piphi-network-android-tv:0.2.0-rc.1
```
