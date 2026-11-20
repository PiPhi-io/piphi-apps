# Runtime Contract

The runtime consumes only Core-authorized source telemetry through
`SourceTelemetryClient`.

- Integration ID: `piphi-network-washdata`
- Kind: `integration`
- Preset: `sensor-device`
- Domain: `sensor`
- Port: `4211`

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

`refresh` reads exactly one bounded source page. Any other command returns a 4xx
monitoring-only error. In particular, no command can switch or start an
appliance.

## Source replay

Core owns canonical identity, binding authorization, source isolation, durable
ordering, pagination, and stale decisions. WashData atomically commits derived
cycle state, processed source `event_id` values, and the opaque `next_cursor`.
The prior cursor is reused after an interrupted transaction.

## Recommended Endpoints

- `GET /diagnostics`
- `POST /discover`
- `POST /config/sync`
- `POST /deconfigure`
- `GET /state`
- `GET /contract`
- `GET /events`
Keep `manifest.json`, the capability catalog, the contract source, and route
handlers in sync.
