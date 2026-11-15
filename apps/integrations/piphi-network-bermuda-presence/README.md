# PiPhi Network Bermuda Presence

Selected-device BLE presence and deterministic room inference using PiPhi's
shared BLE gateway. This runtime **does not** import Bleak/BlueZ, open an
adapter, expose ambient devices as entities, or claim precise coordinates.

## Gateway contract

The runtime authenticates with `Authorization: Bearer <api_token>` and consumes:

- `PUT/DELETE /v1/ble/consumers/{consumer_id}`
- `GET /v1/ble/observations/{consumer_id}?after=<sequence>&limit=<n>`
- `GET /v1/ble/snapshot/{consumer_id}` for cursor-gap/restart recovery

Registration sends `piphi.ble.consumer.v1`, an explicit device-handle matcher,
scan mode, and bounded queue capacity. Observation pages contain `observations`,
`cursor`, `gap`, and `receiver_healthy`; HTTP 409 also means a cursor gap.
Snapshots add `topology_revision` and receiver health. Receiver-to-area topology
and calibration remain integration configuration rather than gateway authority.

Only `piphi.ble.observation.v1` data is accepted. Manufacturer and service data
must be bounded hex maps. Raw addresses, identity keys, tokens and advertisement
payloads are never emitted in diagnostics or telemetry.

## Presence semantics

- Only `selected_device_handles` become entities.
- Presence is `home`, `away`, or `unknown`; consider-home is bounded to 30–3600s.
- Gateway/receiver outage produces `unknown` with `coverage_degraded=true`, not
  a false `away` transition.
- Equal/older timestamps for a device/receiver pair are ignored. Stale replay
  cannot restore presence or an area.
- Area inference excludes stale, unhealthy, out-of-radius receivers. Switching
  requires a materially closer candidate for a configured number of samples;
  the state reports `area_switch_reason`.
- Raw and smoothed distances are RSSI-based **estimates**, not coordinates or
  measurements of physical path length. Reference power, attenuation, RSSI
  offset, radius, smoothing, and velocity guard are configurable.

## Configuration

Required production fields are `gateway_url`, `api_token`, `consumer_id`, at
least one `selected_device_handle`, and receiver-to-area topology. HTTPS is
required except for loopback development. See `GET /ui-config` for bounds.

## Run and validate

```bash
pdm install -G dev
pdm run uvicorn piphi_network_bermuda_presence.main:app --reload --port 4206
pdm run pytest
pdm run ruff check src tests
pdm run mypy
pdm run pip-audit
pdm run python scripts/validate.py
docker build -t ghcr.io/piphi-io/piphi-network-bermuda-presence:0.2.0 .
```

## Portability

The gateway HTTP client and inference engine are platform-neutral Python and
have no Linux-only imports. The current manifest advertises Linux only because
this package's release artifact is an OCI Linux image; no package-local Windows
installer or Windows runtime artifact exists. Running the Python entry point on
Windows should be technically possible but is not a qualified/distributed
platform and is therefore intentionally not advertised.

## Release status

Version 0.2.0 remains draft/unverified pending gateway envelope confirmation,
end-to-end gateway qualification, and root workflow/registry updates. Package
metadata requests full CI (tests, lint, typing, validation, and OCI build).
