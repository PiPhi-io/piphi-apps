# piphi-network-aqara

PiPhi runtime integration for Aqara cloud devices through the Aqara Open API.

## Current scope

- Discovers devices from an Aqara account using the Open API
- Configures one PiPhi runtime entity per Aqara `did`
- Queries device resources dynamically from the device model
- Polls current resource values on a configurable interval
- Accepts Aqara HTTP push updates at `/push/aqara`
- Subscribes mapped Aqara resources automatically with `config.resource.subscribe`
- Maps common Aqara resources into PiPhi capabilities such as temperature, humidity, battery, motion, contact, leak, smoke, gas, switch state, cover position, and lock state
- Supports refresh plus safe first-pass control commands for switches, dimmers, and covers when Aqara exposes writable resources
- Supports config sync, diagnostics, health, and event delivery through the PiPhi Python runtime SDK

## Authentication

This first pass supports Aqara Open API access in two ways:

- supply an existing `access_token` and `open_id`
- supply `account` plus `auth_code` so the runtime can exchange it for tokens

If a `refresh_token` is provided, the runtime will attempt one token refresh when Aqara rejects an expired token.

## Aqara Console HTTP Push

The runtime supports Aqara HTTP Push for near-real-time updates.

1. Start the runtime and configure at least one device successfully.
2. Open `GET /ui-config` or `GET /diagnostics` on the runtime.
3. Copy the reported webhook URL, which points to `/push/aqara`.
4. In Aqara Developer Console, enable `HTTP Push` and set the push address to that webhook URL.
5. Aqara will send the authorized account `accessToken` in the `token` request header.

Notes:

- PiPhi subscribes the mapped device resources automatically after a config succeeds.
- The webhook currently handles `resource_report`, online/offline, name-change, and `control_fail` messages.
- Repeated push messages with the same `msgId` are ignored to avoid replaying state and events.
- Older `resource_report` updates are ignored when Aqara delivers them out of order for a resource that already has a newer timestamp.

## Diagnostics

`GET /diagnostics` includes:

- active subscription count and subscribed config ids
- last push received, processed, duplicate, and error information
- tracked push `msgId` count for dedupe visibility

`GET /ui-config` includes the same webhook path/header details in a setup-friendly format.

## Local development

```bash
pdm install -G dev
pdm run uvicorn piphi_network_aqara.app:app --reload --port 3671
```

## Container build

```bash
docker build -t piphinetwork/aqara-open-api .
docker run --rm -p 3671:3671 piphinetwork/aqara-open-api
```

## Testing

```bash
pdm run pytest
```
