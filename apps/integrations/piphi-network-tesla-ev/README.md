# piphi_network_tesla_ev

`piphi_network_tesla_ev` is a Python PiPhi runtime integration for Tesla vehicles using FastAPI, the Tesla Fleet API, and `piphi-runtime-kit-python`.

This first version focuses on:

- Tesla vehicle discovery from `GET /api/1/vehicles`
- vehicle summary lookup from `GET /api/1/vehicles/{vin}`
- live refresh from `GET /api/1/vehicles/{vin}/vehicle_data`
- opt-in, explicitly confirmed wake-up support from `POST /api/1/vehicles/{vin}/wake_up`
- telemetry delivery back into PiPhi Core through `piphi-runtime-kit-node`

## Important scope note

The Tesla documentation link for `energy` endpoints is for Powerwall and Tesla Energy sites, not Tesla EVs.

This repo is intentionally modeled as a Tesla vehicle integration instead, using the Fleet API vehicle-side endpoints.

## Current command scope

This runtime currently exposes:

- `refresh`
- `wake_up` (disabled while the default read-only mode is active)

It does **not** expose signed vehicle commands like lock, unlock, climate start, or charge start yet.

That is deliberate: Tesla’s current Fleet API docs note that vehicle commands require the Vehicle Command Protocol / virtual key flow, and unsigned commands may be rejected by the vehicle. The next step for this integration would be adding virtual-key-aware command support or a vehicle-command proxy path.

## Configuration

The runtime expects:

- `vin`
- `access_token`
- `region`

Optional safety fields:

- `vehicle_name`
- `include_location` (defaults to `false`)
- `read_only` (defaults to `true`)
- `enable_wake` (defaults to `false` and has no effect while read-only)
- daily request/live-data/wake budgets and a wake cooldown

Production endpoints are fixed to Tesla's regional Fleet API allowlist. Runtime configuration cannot redirect a bearer token to a custom URL. Mock HTTP transports remain available only to in-process tests.

Access tokens are held as `SecretStr` values and are removed from discovery, state, events, diagnostics, and error responses. VINs are replaced on those surfaces with opaque identifiers. Discovery configuration uses bounded, expiring, single-use references tied to the creating credential and region. Exact location, speed, and heading are opt-in and omitted from general state, diagnostics, and events; opted-in values are sent only as current telemetry and this integration does not maintain a location history. Removing the config deletes its in-memory vehicle snapshot.

The pasted access-token input is a temporary onboarding limitation, not a complete account lifecycle. Production use remains blocked until PiPhi provides Tesla authorization-code OAuth, rotating refresh-token storage, scope/account-subject checks, reauthentication, and revocation handling.

## Tesla Fleet API prerequisites

For a usable end-to-end Tesla setup, you will typically need:

- a Tesla developer application
- an OAuth access token for the Tesla account
- the `vehicle_device_data` scope
- the `vehicle_location` scope if you want latitude/longitude in PiPhi

Tesla’s Fleet API is regional. Current regional base URLs are:

- `na`: `https://fleet-api.prd.na.vn.cloud.tesla.com`
- `eu`: `https://fleet-api.prd.eu.vn.cloud.tesla.com`
- `cn`: `https://fleet-api.prd.cn.vn.cloud.tesla.cn`

## Local development

Install dependencies:

```bash
pdm install -G dev
```

Run tests:

```bash
pdm run pytest
```

Start the runtime:

```bash
pdm run piphi-network-tesla-ev
```

Default port:

- `3090`

## Runtime routes

Useful routes:

- `GET /health`
- `GET /ui-config`
- `POST /discover`
- `POST /config`
- `POST /configs/sync`
- `POST /deconfigure`
- `GET /entities`
- `GET /state`
- `POST /command`
- `GET /events`
- `GET /diagnostics`

## Notes for PiPhi

The runtime uses `piphi-runtime-kit-python` for:

- runtime authentication and Core telemetry delivery
- config, health, diagnostics, entity, and event contracts
- durable SQLite-backed automation action idempotency
- FastAPI command dispatch adapters

Refresh and wake-up commands persist their idempotency results under `/.piphinetwork` by default, so worker retries or restarts do not repeat a completed vehicle action.

Requests sharing an access token are serialized and counted against conservative daily limits. Sleeping/offline summaries do not wake the vehicle and preserve prior detailed values as stale/last-known data. Wake has no blind retry, requires explicit confirmation, observes a per-vehicle cooldown and daily budget, and polls readiness for at most 60 seconds.
