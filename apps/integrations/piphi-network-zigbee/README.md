# PiPhi Network Zigbee

Generic Zigbee integration runtime for PiPhi Network. It uses the shared
Zigbee2MQTT sidecar for coordinator setup and bridge supervision, then exposes
Zigbee devices as PiPhi entities.

## Run locally

```bash
pdm install -G dev
ZIGBEE2MQTT_SIDECAR_URL=http://127.0.0.1:8720 pdm run uvicorn piphi_network_zigbee.main:app --reload --port 8730
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `8730` by default and exposes the common PiPhi runtime route contract:

- `GET /health`
- `GET /diagnostics`
- `POST /discover`
- `POST /config`
- `POST /config/sync`
- `POST /deconfigure`
- `POST /deconfigure/{config_id}`
- `GET /state`
- `GET /contract`
- `GET /entities`
- `GET /events`
- `POST /events/device/{config_id}/example`
- `POST /telemetry/example`
- `POST /telemetry/device/{config_id}/example`
- `POST /command`

## Sidecar Dependency

This integration declares a required shared service:

- `piphi.service.zigbee2mqtt-sidecar`
- `piphi.service.mqtt-broker`

PiPhi Core should install/reuse those services before installing this runtime. The
integration discovers Zigbee2MQTT device definitions when the sidecar exposes
them, and it also accepts Zigbee2MQTT device objects through `/discover` inputs
for setup flows.

The compatible managed contract is parent `0.1.13` with sidecar `>=0.1.27,<1.0.0`.
Core supplies one private service network, a per-install internal token, the
sidecar URL, MQTT binding, and persistent volumes. Only `/health` is public in
production; all other parent and sidecar calls require the negotiated token.

## MQTT Runtime

Configured devices publish commands through Zigbee2MQTT topics:

- `POST /command` with `set_state`, `set_brightness`, or `set_color_temperature` publishes to `<base_topic>/<friendly_name>/set`
- `POST /command` with `refresh` publishes a read request to `<base_topic>/<friendly_name>/get`
- `GET /state?refresh=true` reads the retained `<base_topic>/<friendly_name>` state topic and maps Zigbee2MQTT properties into PiPhi capabilities
- the runtime also keeps a background MQTT subscriber for configured devices and their `<base_topic>/<friendly_name>/availability` topics

IEEE address is the physical identity. Endpoint IDs are appended to it for
stable endpoint entities; friendly names remain routing metadata and may change.
Composite exposes are retained in metadata, but only mapped capabilities are
advertised. Controls are disabled by default and require a per-device command
allowlist, an explicitly writable expose, single-target dispatch, confirmation,
the runtime idempotency ledger, and observed state convergence. Broker publish
acceptance alone is not reported as device success.

Parent configuration and subscription intent are atomically persisted in the
private `/var/lib/piphi` volume and restored before polling resumes. Last-good
device state remains visible during dependency loss but is marked unavailable;
repeated transitions are deduplicated.

For HTTPS sidecar transport, mount a CA and optional client certificate/key and
set `PIPHI_ZIGBEE2MQTT_SIDECAR_CA_FILE`,
`PIPHI_ZIGBEE2MQTT_SIDECAR_CERT_FILE`, and
`PIPHI_ZIGBEE2MQTT_SIDECAR_KEY_FILE`. Certificate verification cannot be
disabled.

Set `MQTT_SERVER` and `MQTT_BASE_TOPIC` through Core service bindings or local
environment variables. Individual device configs may override `mqtt_server` and
`mqtt_base_topic`.

## Smoke Checks

With the integration running on `8730`, run:

```bash
pdm run python scripts/smoke.py --skip-sidecar
```

With the Zigbee2MQTT sidecar also running on `8720`, run:

```bash
pdm run python scripts/smoke.py
```

The smoke script configures a synthetic Zigbee2MQTT light, verifies discovery,
configuration, dry-run command publishing, state route shape, and optional
sidecar health/device endpoint compatibility. Pass `--live-mqtt` only when a
real broker is available and you want the command publish check to hit MQTT.

## Docker

```bash
docker build -t ghcr.io/piphi-io/zigbee-integration:0.1.13 .
docker run --rm --read-only -p 8730:8730 ghcr.io/piphi-io/zigbee-integration:0.1.13
```
