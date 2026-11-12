# piphi_network_tesla_ev

`piphi_network_tesla_ev` is a Python PiPhi runtime integration for Tesla vehicles using FastAPI, the Tesla Fleet API, and `piphi-runtime-kit-python`.

This first version focuses on:

- Tesla vehicle discovery from `GET /api/1/vehicles`
- vehicle summary lookup from `GET /api/1/vehicles/{vin}`
- live refresh from `GET /api/1/vehicles/{vin}/vehicle_data`
- wake-up support from `POST /api/1/vehicles/{vin}/wake_up`
- telemetry delivery back into PiPhi Core through `piphi-runtime-kit-node`

## Important scope note

The Tesla documentation link for `energy` endpoints is for Powerwall and Tesla Energy sites, not Tesla EVs.

This repo is intentionally modeled as a Tesla vehicle integration instead, using the Fleet API vehicle-side endpoints.

## Current command scope

This runtime currently exposes:

- `refresh`
- `wake_up`

It does **not** expose signed vehicle commands like lock, unlock, climate start, or charge start yet.

That is deliberate: Tesla’s current Fleet API docs note that vehicle commands require the Vehicle Command Protocol / virtual key flow, and unsigned commands may be rejected by the vehicle. The next step for this integration would be adding virtual-key-aware command support or a vehicle-command proxy path.

## Configuration

The runtime expects:

- `vin`
- `access_token`
- `region`

Optional fields:

- `vehicle_name`
- `include_location`
- `base_url`

`base_url` exists mainly for tests and non-default regional proxy setups.

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
