# Runtime Contract

Based on the `piphi-network-create` cloud API starter; the runtime now reads
published market intervals for a configured `market_area` and `currency`.

- Integration ID: `piphi-network-nord-pool`
- Kind: `integration`
- Preset: `cloud-polling-api`
- Domain: `cloud-api`
- Port: `4214`

## Required Endpoints

- `GET /health`
- `GET /entities`
- `POST /command`
- `POST /config`
- `GET /ui-config`

## Automation Command Payload

`POST /command` accepts the Core automation runtime contract:

```json
{
  "contract_version": "automation.runtime.command.v1",
  "command": "refresh",
  "target": {
    "config_id": "demo-device",
    "device_id": "demo-device",
    "entity_id": null
  },
  "params": {},
  "capability": "device.refresh",
  "capability_requirements": ["device.refresh"]
}
```

Return `{"ok": true, ...}` for accepted commands. For validation failures, return `{"ok": false, "error": "unsupported_capability", "message": "..."}` with an appropriate 4xx status.

## Recommended Endpoints

- `GET /diagnostics`
- `POST /discover`
- `POST /config/sync`
- `POST /deconfigure`
- `GET /state`
- `GET /contract`
- `GET /events`
- `POST /telemetry/example` (compatibility route; fetches live prices)

Keep `manifest.json`, the contract source file, and route handlers in sync.
