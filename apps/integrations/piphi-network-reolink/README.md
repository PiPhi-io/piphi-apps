# PiPhi Network Reolink

Local Reolink camera and NVR integration for PiPhi Network. The runtime uses
[`reolink_aio`](https://github.com/starkillerOG/reolink_aio) for authenticated
device access and represents NVR channels as child camera entities.

This repository is an **integration runtime**, not a sidecar. It owns Reolink
configuration, discovery, entities, state, events, and commands. Authenticated
media URLs are deliberately excluded; live video, snapshots, and recording will
be brokered through PiPhi's shared camera gateway in a later milestone.

## Current milestone

Implemented:

- typed camera/NVR configuration with secret redaction
- lazy local connection through `reolink_aio`
- camera and NVR channel discovery
- aggregate connectivity and camera-count state
- read-only polling and explicit refresh
- deterministic child entity IDs
- capability coverage ledger and contract tests

Planned capabilities and deliberate exclusions are recorded in
`capability-catalog.json`.

## Development

```bash
pdm install -G dev
pdm run pytest
pdm run ruff check src tests
pdm run python scripts/validate.py
pdm run uvicorn piphi_network_reolink.main:app --reload --port 4225
```

The runtime exposes the common PiPhi endpoints including `/health`, `/config`,
`/config/sync`, `/entities`, `/state`, `/events`, and `/command`.

Configuration requires a local address, username, and password. Use a dedicated
least-privilege Reolink account. Credentials are retained only in the runtime's
private configuration object and are excluded from entity state, telemetry,
events, logs, and diagnostics.

## Container

```bash
docker build -t ghcr.io/piphi-io/piphi-network-reolink:0.1.0 .
docker run --rm -p 4225:4225 ghcr.io/piphi-io/piphi-network-reolink:0.1.0
```

The initial release is a Bronze beta while hardware verification expands across
representative standalone, doorbell, dual-lens, battery, and NVR models.
