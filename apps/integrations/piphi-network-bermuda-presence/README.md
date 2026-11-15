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

Configuration is transactional: initial gateway registration and snapshot
recovery must succeed before the entry replaces an existing configuration.
Already configured entries degrade to `unknown` during later outages and recover
without emitting a false departure.

## Installation and removal

Install the OCI package through PiPhi after the managed BLE gateway is healthy.
Use `/ui-config` to select opaque device handles, map receivers to areas, and set
the bounded presence, smoothing, calibration, radius, and hysteresis options.
Setup validates the gateway before committing the entry.

Remove the configuration through PiPhi before uninstalling the image. Removal
cancels polling, unregisters the gateway consumer, closes the client, and removes
the selected-device entities and runtime state.

## Automation

The integration exposes the idempotent `refresh` action and `state_matches`
condition. It emits `presence.arrived`, `presence.left`, and
`runtime.config.applied`; transition events are deduplicated by the inference
state machine. No adapter-control or observation-injection action exists.

## Troubleshooting and limitations

- `presence=unknown` with `coverage_degraded=true` indicates unhealthy or stale
  receiver coverage; it is intentionally not converted to `away`.
- Ensure each selected handle is explicitly authorized and every receiver has a
  stable area mapping. Equal or older receiver timestamps are ignored.
- Distance is an RSSI-derived estimate. Walls, body occlusion, radio orientation,
  and calibration affect it; precise coordinates are not supported.
- Private-address/IRK resolution and remote receiver provisioning remain gateway
  roadmap items. This integration never accepts identity keys.

## Run and validate

```bash
pdm install -G dev
pdm run uvicorn piphi_network_bermuda_presence.main:app --reload --port 4206
pdm run pytest
pdm run ruff check src tests
pdm run mypy
pdm run pip-audit
pdm run python scripts/validate.py
docker build -t ghcr.io/piphi-io/piphi-network-bermuda-presence:0.2.1 .
```

## Portability

The gateway HTTP client and inference engine are platform-neutral Python and
have no Linux-only imports. The current manifest advertises Linux only because
this package's release artifact is an OCI Linux image; no package-local Windows
installer or Windows runtime artifact exists. Running the Python entry point on
Windows should be technically possible but is not a qualified/distributed
platform and is therefore intentionally not advertised.

## Quality and release status

Version 0.2.1 is a Bronze quality candidate. `quality-scale.yaml` records the
Home Assistant IQS mapping and evidence. Package metadata requests full CI
(tests, lint, typing, validation, dependency audit, and OCI build); marketplace
rollout remains independently governed and starts at zero.
