# Runtime Contract

Read-only public Octopus tariff-price runtime. Configuration accepts product and
tariff codes only; account credentials and endpoint overrides are rejected.
Prices do not represent account consumption, bills, taxes, or network charges.

- Integration ID: `piphi-network-octopus-energy`
- Kind: `integration`
- Preset: `cloud-polling-api`
- Domain: `cloud-api`
- Port: `4212`

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
- `POST /telemetry/example`

Keep `manifest.json`, the contract source file, and route handlers in sync.
