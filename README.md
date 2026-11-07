# PiPhi LG ThinQ Connect Integration

PiPhi integration for LG ThinQ appliances using the official ThinQ Connect
Python SDK.

## What this integration does

- discovers devices from a user's LG ThinQ account using a PAT, country code,
  and optional client id
- supports configuration, rehydration, and config sync through the PiPhi Python
  runtime kit
- normalizes status from many ThinQ device families into a common PiPhi entity
  model
- exposes entities, state, events, commands, and UI config endpoints
- delivers telemetry and runtime events back to PiPhi Core
- keeps unsupported appliances visible as read-only entities instead of dropping
  them

## Runtime SDK and testkit

- runtime SDK: `piphi-runtime-kit-python==0.8.1`
- ThinQ SDK: `thinqconnect`
- local test helper: `piphi-runtime-testkit-python`

The ThinQ SDK is imported lazily so tests can run with mocked client calls even
before the external dependency is installed locally.

## Local development

Install dependencies:

```bash
pdm install -G dev
```

Run the runtime:

```bash
pdm run python -m piphi_network_thinqconnect.app
```

Run tests:

```bash
pdm run pytest -q
```

The integration API defaults to `http://127.0.0.1:3667`.

## Important routes

- `GET /health`
- `POST /discover`
- `GET /entities`
- `GET /state`
- `POST /command`
- `POST /config`
- `POST /configs/sync`
- `POST /config/sync`
- `POST /deconfigure`
- `GET /ui-config`
- `GET /events`
- `GET /manifest.json`

## Discovery and onboarding

ThinQ onboarding is account-based. Discovery requires:

- `access_token`
- `country_code`
- optional `client_id`

Users discover devices from their ThinQ account first, then save one PiPhi
runtime config per selected device.

For local development, enable `simulation_mode` instead of supplying an LG
token. Discovery then returns representative washer, refrigerator, and air
conditioner fixtures. The fixtures pass through the same normalization,
entity, telemetry, command, and dashboard paths used by live ThinQ devices.

## Dashboard experience scope

The first dashboard phase intentionally ships one reusable **LG ThinQ
overview** experience instead of separate cards for every appliance model. It
adapts to negotiated entity capabilities and relies on Core's semantic theme
surface for light and dark appearance. A dedicated experience should only be
added when an appliance workflow cannot be expressed cleanly by the overview
or Core's canonical controls.

## Refrigerator capability model

Standard refrigerators are negotiated from each appliance's current ThinQ profile and
state rather than from a global model superset. The runtime preserves distinct
fridge, freezer, and convertible target temperatures; main-door state; power
save, eco, Sabbath, rapid-freeze, express-mode, and express-fridge state; and
fresh-air plus multiple water-filter instances when the appliance reports them.

Only controls present in the device's negotiated control surface are exposed.
Known commands retain the provider's exact parameter names and validate
profile-provided enum/range constraints. Unknown readable scalar properties are
available in the bounded `refrigerator.additional_capabilities` detail surface;
unknown writes are denied. See `src/refrigerator-capability-catalog.json` for
implemented, planned, and deliberately excluded upstream capabilities.
Kimchi refrigerators and wine cellars retain their separate device-family
contracts; their model-specific compartment/program semantics are not flattened
into this standard refrigerator representation.

## Polling behavior

Configured devices are polled on a background loop. The default polling
interval is 60 seconds and can be overridden per config.

## Compatibility notes

This runtime aims for broad device compatibility for discovery and status. Some
devices will be fully controllable, while others will remain read-only until
their ThinQ profile exposes a control surface the runtime can map safely.
