# PiPhi Wyze Camera Bridge

PiPhi Wyze Camera Bridge is a managed home service that turns cameras authorized through a
Wyze account into authenticated local RTSP sources for compatible PiPhi camera integrations.
It wraps the independently maintained
[`docker-wyze-bridge`](https://github.com/mrlt8/docker-wyze-bridge) v2.10.3 runtime behind a
small PiPhi lifecycle API.

This service does not create dashboard entities. A separate Wyze camera integration owns
account onboarding, saved camera entities, and the handoff to PiPhi Camera Media Service.

## Runtime contract

- `GET /health` reports adapter and bridge readiness without secrets.
- `GET /diagnostics` returns bounded operational metadata.
- `GET /contract` describes `camera.bridge.wyze.v1`.
- `PUT /v1/wyze-bridge/config` accepts encrypted configuration forwarded by Core.
- `DELETE /v1/wyze-bridge/config` stops the embedded bridge and clears in-memory secrets.
- `GET /v1/wyze-bridge/status` reports lifecycle state.
- `GET /v1/wyze-bridge/cameras` returns authorized camera descriptors to trusted PiPhi
  consumers. Stream URLs are sensitive and must never be logged or exposed to widgets.

Core allocates the primary HTTP listener through `PORT`. The container publishes MediaMTX's
internal RTSP listener on host TCP port `18554`, keeping it separate from PiPhi Camera Media
Service's WebRTC listener.

## Development

```bash
pdm install -G dev
pdm run ruff check src tests scripts
pdm run ruff format --check src tests scripts
pdm run pytest
pdm run python scripts/validate.py
```

An actual Wyze account and supported camera are required for hardware qualification. Unit and
contract tests use deterministic fakes and never contact Wyze.

## Security and privacy

Wyze credentials and API keys are accepted as secret configuration, passed only to the embedded
bridge process, retained only in memory by the adapter, and excluded from health, diagnostics,
state, and logs. Do not expose the service API or RTSP port to the public internet.

See [SECURITY.md](SECURITY.md) to report vulnerabilities.

## License and upstream source

This repository is licensed under AGPL-3.0-only to preserve the terms of the embedded upstream
bridge. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the pinned upstream source and
image digest. PiPhi is not affiliated with or endorsed by Wyze Labs.
