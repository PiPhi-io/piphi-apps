# Runtime contract

The sidecar owns one local serial controller and emits redacted, schema-versioned
Z-Wave JS events. The parent `piphi-network-zwave` integration owns normalized
devices, capabilities, state, telemetry, widgets, and homeowner-facing commands.

## Configuration

`POST /config` requires `controller_path`. Stable paths under
`/dev/serial/by-id/` or `/dev/serial/by-path/` are accepted. Unstable tty paths
are rejected unless `PIPHI_ZWAVE_ALLOW_UNSTABLE_TTY=true`; other paths require an
exact entry in `PIPHI_ZWAVE_ALLOWED_CONTROLLER_PATHS`.

Security keys are read only from the `PIPHI_ZWAVE_*_KEY` environment variables.
They are never accepted in configuration payloads or returned by diagnostics.

## Event transport

`GET /v1/zwave/events?after=<sequence>&limit=<1..500>` replays the bounded
`piphi.zwave.event.v1` stream. Each record includes an increasing sequence,
timestamp, event type, node/endpoint/command-class identity when available, and
sanitized Z-Wave JS payload data. Buffer overflow drops the oldest record and
increments `dropped_event_count`.

## Commands

`POST /command` accepts only:

- `refresh_controller_information`
- `reconnect_driver`
- `ping_node` with `params.node_id`
- `request_node_interview` with `params.node_id`
- `refresh_node_values` with `params.node_id`

Commands are serialized through a bounded queue. Arbitrary API calls, raw serial
frames, factory reset, inclusion, NVM operations, and network-key access fail
closed.

## Health and shutdown

`GET /health` and `GET /diagnostics` expose redacted driver and queue state. The
Fastify close hook destroys the driver and drains tracked Core deliveries.
