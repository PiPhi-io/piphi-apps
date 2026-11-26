# PiPhi Network Z-Wave

Homeowner-facing Z-Wave runtime backed by the managed
`piphi-zwave-js-sidecar`. The sidecar owns the serial controller and Z-Wave JS
driver; this parent integration owns stable node/endpoint entities, normalized
state, safe controls, replay reconciliation, and Core delivery.

## Implemented boundary

- Authenticated `piphi.zwave.snapshot.v1` reconciliation and bounded
  `piphi.zwave.event.v1` replay.
- Automatic recovery after sidecar outages, replay gaps, or stream restarts.
- Stable entities include the full SHA-256 network/controller fingerprint plus
  node fingerprint and endpoint; each value carries its own stable hash.
- Transactional configure/reconfigure, durable restart restoration, last-good
  state during bounded dependency backoff, and explicit stale/degraded health.
- Switch, level, lock, thermostat, sensor, meter, and battery normalization.
- Controls only for metadata-declared writable, non-secret values, with type,
  range, and state validation.
- No arbitrary driver calls, raw serial/NVM access, full DSKs, network keys, or
  unrestricted value writes.

The sidecar supplies bounded secure commissioning, exclusion, failed-node
reconciliation, and NVM lifecycle APIs. Physical security-class negotiation, RF
behavior, controllers, devices, firmware, and restore interoperability remain unverified.

## Development

```bash
pdm install --check
pdm run pytest
pdm run python scripts/validate.py
```

Run the sidecar on port `4211`, set the same long random token in
`PIPHI_ZWAVE_SIDECAR_TOKEN` for both processes, then start the parent:

```bash
pdm run uvicorn piphi_network_zwave.main:app --host 0.0.0.0 --port 4221
```

Only `GET /health` is public. Production operational reads and mutations require
the runtime identity headers supplied by PiPhi Core. The runtime fails closed if
authentication is not configured.

## Runtime routes

The parent exposes the standard PiPhi health, diagnostics, discovery,
configuration, entities, state, events, telemetry, command, and contract routes.
See [`docs/contract.md`](docs/contract.md) for the parent/sidecar boundary and
[`docs/privacy.md`](docs/privacy.md) for data handling and runtime requirements.

## Container

```bash
docker build -t ghcr.io/piphi-io/piphi-network-zwave:0.4.0 .
docker run --rm -p 4221:4221 \
  -e PIPHI_ZWAVE_SIDECAR_URL=http://host.docker.internal:4211 \
  -e PIPHI_ZWAVE_SIDECAR_TOKEN=replace-with-a-long-random-token \
  ghcr.io/piphi-io/piphi-network-zwave:0.4.0
```
