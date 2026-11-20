# WashData

WashData is a monitoring-only PiPhi integration that derives appliance cycle
state from a power telemetry source explicitly bound by PiPhi Core. It never
reads another integration's files or database and cannot switch appliance power.

## Bounded monitoring slice

Version `0.2.0` implements:

- binding discovery through Runtime Kit `SourceTelemetryClient`
- one bounded telemetry page per read with no hidden cursor state
- configurable start/stop thresholds and sample debounce
- cycle start/finish, duration, peak power, and per-cycle energy
- durable SQLite state, migrations, source-event deduplication, and restart replay
- Core-owned stale/unavailable-source handling and recovery events
- read-only `refresh`; all appliance-control commands fail closed

Program matching, phase estimation, profile learning, maintenance, community
sharing, and historical cost management remain planned and unadvertised.

## Durable replay contract

For every source page, WashData commits the derived cycle state, every processed
`event_id`, and `next_cursor` in one SQLite transaction. A crash before commit
reuses the previous cursor and intentionally replays the page; committed event
IDs suppress duplicate transitions. State is stored at
`PIPHI_WASHDATA_STATE_PATH` (default `./data/washdata-state.sqlite3`).

## Run locally

```bash
pdm install -G dev
pdm run pytest
pdm run python scripts/validate.py
pdm run uvicorn piphi_network_washdata.main:app --reload --port 4211
```

Local configuration requires a Core runtime auth context and an
`IntegrationSourceBinding` whose key matches `binding_key` (default
`appliance_power`). The source metric defaults to `power_w`.

## Safety boundary

WashData exposes cycle monitoring and a read-only refresh action. It does not
expose `set_power`, mains switching, physical appliance start, arbitrary
detector code, or direct notification credentials.
