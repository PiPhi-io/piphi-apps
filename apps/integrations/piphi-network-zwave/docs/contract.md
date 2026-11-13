# Runtime contract

The managed sidecar owns one serial controller, Z-Wave JS driver lifecycle,
bounded replay, and secret redaction. This parent owns normalized entities,
state, events, and homeowner-facing controls.

## Sidecar transport

The parent reads a complete `piphi.zwave.snapshot.v1` document from
`GET /v1/zwave/snapshot`, then polls
`GET /v1/zwave/events?after=<sequence>&limit=<1..500>`. A changed stream ID,
replay gap, or reset dropped-event counter triggers snapshot resynchronization.
Both routes and `POST /command` use the bearer token from
`PIPHI_ZWAVE_SIDECAR_TOKEN`, falling back to the runtime internal token.

## Entity identity

Each entity has the stable ID `zwave-node-<node>-endpoint-<endpoint>`. State and
controls derive from command-class value metadata in the sidecar snapshot.
Unknown values may remain visible in redacted metadata but never receive an
unrestricted write action.

## Automation command payload

```json
{
  "contract_version": "automation.runtime.command.v1",
  "command": "set_switch",
  "target": {
    "config_id": "home-network",
    "device_id": "zwave-node-2-endpoint-0",
    "entity_id": null
  },
  "params": {"value": true},
  "capability": "action.set_switch",
  "capability_requirements": ["action.set_switch"]
}
```

The parent resolves the command to the exact writable value ID advertised by
the current snapshot. Unsupported entities, types, ranges, or enumerated states
fail closed before reaching the sidecar.

## Required parent routes

- `GET /health`
- `GET /entities`
- `POST /command`
- `POST /config`
- `GET /ui-config`

Diagnostics, discovery, configuration sync/removal, state, contract, events,
and telemetry use the standard PiPhi runtime routes.
