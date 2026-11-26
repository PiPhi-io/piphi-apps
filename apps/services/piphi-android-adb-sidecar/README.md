# PiPhi Android ADB Sidecar

Bounded Android Debug Bridge transport for PiPhi parent integrations. The
sidecar owns a private Android Platform Tools server and one explicitly
configured network target. Parent integrations retain
ownership of Android entities, normalized device state, behaviors, and widgets.

## Implemented boundary

- Manual `host` and `port` configuration for ADB-over-network.
- Private `0600` ADB credentials generated and retained only in the mounted data
  directory, plus bounded Android 11+ mDNS and one-shot pairing-code support.
- Opaque target leases; parent requests never contain a host or raw serial.
- Allow-listed short key events and allow-listed `getprop` reads.
- Per-target serialization, bounded queues, deadlines, output limits, and
  reconnect handling.
- Private bearer authentication on every route except `GET /health`.
- Sanitized state and diagnostics with no endpoint, serial, key, credential
  path, raw command output, or shell content.

`POST /command` remains unsupported because these are private transport
operations, not user-facing automation actions. Arbitrary shell, files,
packages, intents, forwarding, privilege escalation, and all-device execution
are explicitly excluded.

USB passthrough remains excluded. Wireless pairing/mDNS works only where the
target firmware and the pinned Platform Tools build advertise that support.
Classic ADB-over-TCP is not encrypted; use it only on a trusted local network
and never expose the device port to the internet.

## Device preparation

The target must expose an ADB TCP endpoint or Android 11+ wireless debugging.
Use the authenticated `POST /v1/adb/pair` flow for a six-digit pairing code, or
pre-provision a trusted key under `/app/data/.android`. No ADB
server port is published by the container. The mounted data directory must be
readable and writable by container UID/GID `10001:10001`.

## Private parent API

- `GET /v1/adb/snapshot?config_id=...`
- `POST /v1/adb/reconnect`
- `POST /v1/adb/execute`
- `GET /v1/adb/mdns`
- `POST /v1/adb/pair`

Set `PIPHI_ANDROID_ADB_SIDECAR_TOKEN` or
`PIPHI_INTEGRATION_INTERNAL_TOKEN`. Production mode fails closed when neither is
configured. See `docs/contract.md` for the versioned request and response
formats.

The container pins Debian's multi-architecture Platform Tools package to
`1:34.0.5-12`, runs as UID/GID 10001, and writes only to `/app/data`. The
sidecar never fabricates device entities; `/entities` is intentionally empty.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_android_adb_sidecar.main:app --reload --port 4213
pdm run ruff check src tests
pdm run mypy src
pdm run pytest
pdm run python scripts/validate.py
```

## Docker

```bash
docker build -t ghcr.io/piphi-io/piphi-android-adb-sidecar:0.3.0-rc.2 .
docker run --rm \
  -p 4213:4213 \
  -e PIPHI_ANDROID_ADB_SIDECAR_TOKEN=replace-me \
  -v piphi-android-adb:/app/data \
  ghcr.io/piphi-io/piphi-android-adb-sidecar:0.3.0-rc.2
```

This release candidate remains `draft`, `unverified`, and rollout zero until
physical-device qualification is completed.
