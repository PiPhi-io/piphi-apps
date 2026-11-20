# PiPhi Network Tapo Cameras

Authenticated, read-only local monitoring for directly reachable, powered Tapo
cameras and doorbells supported by `python-kasa` 0.10.x.

## Functional scope

The `0.2.0` slice publishes connectivity, availability, stale-last-good state,
privacy mode when the camera exposes a lens-mask module, camera-enabled state,
signal strength, and sanitized model/firmware metadata. Its only command is the
non-mutating `refresh` action.

Configuration requires a camera address and camera-account username/password.
Discovery is targeted and authenticated; this runtime never performs a broad LAN
scan. Runtime endpoints other than `/health` require the PiPhi integration token.

Not supported: streams, snapshots, RTSP/ONVIF URLs, detections, PTZ, alarms,
lights, pairing, firmware updates, privacy setters, arbitrary commands, hubs,
child cameras, battery cameras, or devices without stable identity.

## State and recovery

Each successful poll replaces the current observation. A failed poll preserves
the last known privacy and signal values while setting `connected=false`,
`available=false`, and `stale=true`. Authentication failures require
reauthorization. Outage and recovery events are emitted once per transition.

Configurations are rehydrated through the Core runtime snapshot after restart.
Masked passwords are accepted only when replacing an existing in-memory config
for the same host and username; a new or restarted config must contain a resolved
secret from Core.

## Routes

- `GET /health` (public container health check)
- `GET /diagnostics`, `/state`, `/contract`, `/entities`, `/events`
- `POST /discover`, `/config`, `/config/sync`, `/deconfigure`
- `POST /deconfigure/{config_id}`, `/command`
- `GET /ui-config`

## Development

```bash
pdm install -G dev
pdm run pytest
pdm run python scripts/validate.py
pdm run python scripts/check_release.py apps/piphi-network-tapo-cameras/v0.2.0
```

Run locally only with explicit test bypass or a runtime token:

```bash
PIPHI_ALLOW_UNAUTHENTICATED=true \
  pdm run uvicorn piphi_network_tapo_cameras.main:app --reload --port 4207
```

## Container

```bash
docker build -t ghcr.io/piphi-io/piphi-network-tapo-cameras:0.2.0 .
docker run --rm -p 4207:4207 \
  -e PIPHI_INTEGRATION_INTERNAL_TOKEN=replace-me \
  ghcr.io/piphi-io/piphi-network-tapo-cameras:0.2.0
```

The image runs as non-root UID/GID `10001`. Marketplace governance remains
`draft`, rollout `0`, and qualification `unverified` until representative powered
camera and doorbell hardware is certified.
