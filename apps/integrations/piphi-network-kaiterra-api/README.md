# PiPhi Network Kaiterra API

Privacy-hardened, read-only PiPhi integration for the official
[Kaiterra public API](https://dev.kaiterra.com/). It polls the latest reading and
minimal metadata for one explicitly selected device per configuration.

## Supported boundary

- Requires a revocable Kaiterra API key and an explicit device UDID.
- Never lists an account or silently selects a first device: the documented API
  exposes no account/device-list endpoint.
- Reads `GET /devices/{id}/top` and `GET /devices/{id}` only.
- Supports air-quality/comfort metrics listed in `capability-catalog.json`.
- Excludes motion, sound, raw metadata, history, batch calls, and all mutations.
- Preserves stale last-good state during typed auth, rate-limit, provider-contract,
  and transient-outage failures.

See [privacy and diagnostics](docs/privacy.md) for data minimization details.

## Configuration

PiPhi Core sends runtime-authenticated configuration containing:

```json
{
  "id": "office-air-monitor",
  "device_udid": "<device-uuid>",
  "api_key": "<api-key>",
  "alias": "Office air monitor",
  "poll_interval_seconds": 300
}
```

Both `device_udid` and `api_key` are secret fields. Reconfigure/reauth accepts the
masked placeholders `********`, `••••••••`, or `***` only for the same existing
configuration and device identity. A replacement is validated before the working
session is swapped.

Production requests are fixed to `https://api.kaiterra.com/v1`. Isolated tests may
set `PIPHI_ALLOW_TEST_BASE_URL=1` for loopback HTTP(S) only.

## Runtime security and recovery

Only `GET /health` is public. Every other route requires matching
`X-Container-Id` and `X-PiPhi-Integration-Token` headers. The runtime uses bounded
jittered retries, honors bounded `Retry-After`, consumes quota-remaining headers
when supplied, removes all sessions/tasks on deconfigure, and rehydrates Core's
mounted/runtime snapshot after restart.

The OCI image is pinned, dependency-locked, non-root, multi-architecture, and
declares a read-only root filesystem with `/var/lib/piphi` as its sole persistent
runtime data volume.

## Development gates

```bash
pdm install --check
pdm run pytest
pdm run python scripts/validate.py
python ../../../scripts/validate_apps.py
python ../../../scripts/run_app_ci.py apps/integrations/piphi-network-kaiterra-api
docker build -t kaiterra-api:local .
```

Tests use a deterministic in-process HTTP transport and synthetic contract fixtures.
They do not use credentials or contact Kaiterra accounts/devices. Live account and
physical-device interoperability remain separate qualification work.
