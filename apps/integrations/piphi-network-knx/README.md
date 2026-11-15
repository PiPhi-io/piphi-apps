# PiPhi Network KNX

A monitoring-first KNX/IP integration built on the pinned `xknx==4.1.1` protocol stack.

Version 0.2.0 deliberately supports a smaller surface than Home Assistant KNX, but applies production safety and lifecycle rules to that surface. It owns one exclusive KNX/IP tunnel per configuration, exposes only explicitly reviewed group addresses, and never accepts a caller-supplied address or raw telegram.

## Supported

- KNXnet/IP automatic selection, UDP tunnelling, and TCP tunnelling
- Active KNX/IP interface discovery
- DPT `1.001` switch/binary state, `5.001` scaling, and `9.001` temperature
- Binary sensor, numeric sensor, switch, and light datapoint entities
- Separate command and feedback group addresses
- Initialization reads, push feedback, connection-derived availability, and stale/uninitialized quality
- Typed reads and opt-in writes with explicit per-datapoint allowlisting
- Bounded xknx rate, bounded outgoing queue, write timeout with unknown-outcome reporting, and no automatic write retry
- Atomic reconfiguration, duplicate endpoint rejection, orderly shutdown, and durable configuration replay
- Runtime-token authentication for every operational endpoint; only `/health` is public

## Intentionally unsupported in 0.2.0

- KNX IP Secure, KNX Data Secure, routing, or secure routing
- ETS `.knxproj` or `.knxkeys` import
- Arbitrary telegram send, unknown-DPT decode/write, group-address scanning, commissioning, or topology mutation
- Entity families or DPTs not listed above

These are unavailable rather than silently downgraded or guessed.

## Configuration

```json
{
  "id": "main-building",
  "host": "192.168.1.50",
  "port": 3671,
  "alias": "Main building",
  "transport": "tunneling_udp",
  "rate_limit": 10,
  "queue_size": 64,
  "allow_writes": true,
  "datapoints": [
    {
      "id": "office_light",
      "name": "Office light",
      "entity_type": "light",
      "dpt": "1.001",
      "state_address": "1/2/3",
      "command_address": "1/2/4",
      "writable": true,
      "read_on_init": true
    },
    {
      "id": "office_temperature",
      "name": "Office temperature",
      "entity_type": "sensor",
      "dpt": "9.001",
      "state_address": "1/3/1"
    }
  ]
}
```

Use a dedicated tunnel endpoint. Verify every group address, DPT, and read/write flag against the ETS project before enabling writes. Project metadata is evidence, not authorization.

## Safety and availability semantics

- `connected` reflects the xknx session, not configuration presence.
- `uninitialized` means no feedback has been observed; `stale` means feedback exceeded the configured age.
- A successful write response means xknx accepted the telegram for transmission. It does **not** claim actuator feedback. The entity remains feedback-driven.
- A write timeout is reported as an unknown outcome and is never retried automatically.
- `allow_writes` and each datapoint's `writable` field must both be true.
- A physical `host:port` endpoint can belong to only one active configuration.

## Operations

PiPhi Core must inject `PIPHI_INTEGRATION_INTERNAL_TOKEN`. Without it, operational routes fail closed with 503. `PIPHI_ALLOW_UNAUTHENTICATED=true` exists only for isolated tests and local development.

Persistent state is stored under `/app/data`, mounted from `/var/lib/piphi/knx`. Back up this directory before replacement. Removal stops the tunnel and removes the persisted config.

Troubleshooting:

1. Confirm the interface has a free tunnel slot and no other client shares it.
2. Confirm UDP/TCP port 3671 is reachable from the runtime network.
3. Confirm ETS filter tables permit each mapped group address.
4. Check `/diagnostics` with the runtime token; host and group-address topology are not returned.
5. If a write outcome is unknown, inspect bus/actuator feedback before manually retrying.

## Development and release gates

```bash
pdm lock --check
pdm run ruff check src tests
pdm run mypy src
pdm run pytest
pdm run python scripts/validate.py
docker build -t piphi-network-knx:test .
```

The test suite covers strict config validation, DPT codecs and bounds, adapter lifecycle, discovery normalization, initialization reads, feedback, allowlisted writes, unknown outcomes, authentication, persistence, and contract/catalog synchronization. Physical gateway qualification remains separately tracked; this package does not claim KNX product certification.
