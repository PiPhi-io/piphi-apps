# piphi-network-aqara

PiPhi runtime integration for Aqara cloud devices through the Aqara Open API.

## Current scope

- Discovers devices from an Aqara account using the Open API
- Configures one PiPhi runtime entity per Aqara `did`
- Queries device resources dynamically from the device model
- Polls current resource values on a configurable interval
- Accepts Aqara HTTP push updates at `/push/aqara`
- Subscribes mapped Aqara resources and negotiated reportable traits automatically
- Maps common Aqara resources into PiPhi capabilities such as temperature, humidity, battery, motion, contact, leak, smoke, gas, carbon monoxide, particulate matter, switch state, lighting, thermostat setpoints, fan speed, filter life, cover position, and lock state
- Supports refresh plus negotiated controls for switches, dimmers, tunable/RGB lights, thermostat setpoints and modes, fan speed/modes/swing, airflow direction, covers, and vendor-discovered scenes
- Emits metadata-decoded button, rotation, cube, and vibration events from real-time trait reports
- Supports config sync, diagnostics, health, and event delivery through the PiPhi Python runtime SDK

## Authentication

This first pass supports Aqara Open API access in two ways:

- supply an existing `access_token` and `open_id`
- supply `account` plus `auth_code` so the runtime can exchange it for tokens

If a `refresh_token` is provided, the runtime will attempt one token refresh when Aqara rejects an expired token. Rotated refresh tokens replace the previous token atomically in the active config. A rejected refresh token, changed account identity, or credentials rejected immediately after refresh moves the device to `auth_state: reauth_required`; replacing the credentials on the existing config restores the same device identity without delete/re-add.

The configured region is part of the account identity boundary. An existing config cannot be moved to another region or `did` in place, and duplicate account/region/device tuples are rejected. Runtime configuration cannot override the API domain: each region is pinned to Aqara's official endpoint allowlist.

## Capability negotiation

The runtime queries Aqara resource and trait metadata for each model and advertises only capabilities and commands backed by that device. Numeric controls require vendor-provided bounds where the trait does not define a universal range. HVAC, fan, swing, airflow, button, rotation, cube, and vibration enums require unambiguous `supportedValues` metadata. Cover stop is exposed only when Aqara resource metadata explicitly advertises a stop, pause, or hold value. Scene execution accepts only opaque selectors mapped to scene IDs returned by `query.scene.listBySubjectId`; arbitrary scene IDs are rejected. Unsupported, ambiguous, or unbounded controls fail closed. Locks remain read-only, and camera streaming/control is outside this slice. See `capability-catalog.json` for implemented, planned, and excluded families.

## Aqara Console HTTP Push

The runtime supports Aqara HTTP Push for near-real-time updates.

1. Start the runtime and configure at least one device successfully.
2. Open `GET /ui-config` or `GET /diagnostics` on the runtime.
3. Copy the reported webhook URL, which points to `/push/aqara`.
4. In Aqara Developer Console, enable `HTTP Push` and set the push address to that webhook URL.
5. Aqara will send the authorized account `accessToken` in the `token` request header.

Notes:

- PiPhi subscribes mapped resources with `config.resource.subscribe` and negotiated reportable traits with `spec.config.trait.subscribe` after a config succeeds.
- The webhook handles `resource_report`, `spec_report`, online/offline, name-change, and `control_fail` messages.
- Repeated push messages with the same `msgId` are ignored to avoid replaying state and events.
- Older resource and trait reports are ignored when Aqara delivers them out of order for a path that already has a newer timestamp.
- Push authentication is possession-based: Aqara's `token` header must match a configured access token. PiPhi compares it in constant time and, when `openId` is present, also requires the configured account identity to match.
- Replay keys are scoped to the token/account and reserved atomically before processing. They are retained in a bounded in-memory window, so polling remains the authoritative recovery path across process restarts. TLS termination and request-size/rate limits must be enforced by the deployment ingress; Aqara does not provide a separate request signature in this HTTP Push flow.

## Diagnostics

`GET /diagnostics` includes:

- active configuration, poll-task, subscription, connectivity, error, and reauthentication counts
- last push received, processed, duplicate, and error information
- tracked push `msgId` count for dedupe visibility

Diagnostics and public state are recursively scrubbed for configured credentials. Diagnostics additionally redact account/device PII and raw error text is scrubbed before it is exposed or emitted as an event.

`GET /ui-config` includes the same webhook path/header details in a setup-friendly format.

## Local development

```bash
pdm install -G dev
pdm run uvicorn piphi_network_aqara.app:app --reload --port 3671
```

## Container build

```bash
docker build -t ghcr.io/piphi-io/aqara-open-api:0.1.4 .
docker run --rm -p 3671:3671 ghcr.io/piphi-io/aqara-open-api:0.1.4
```

## Testing

```bash
pdm run pytest
```
