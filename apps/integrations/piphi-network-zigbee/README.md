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

## MQTT Runtime

Configured devices publish commands through Zigbee2MQTT topics:

- `POST /command` with `set_state`, `set_brightness`, or `set_color_temperature` publishes to `<base_topic>/<friendly_name>/set`
- `POST /command` with `refresh` publishes a read request to `<base_topic>/<friendly_name>/get`
- `GET /state?refresh=true` reads the retained `<base_topic>/<friendly_name>` state topic and maps Zigbee2MQTT properties into PiPhi capabilities
- the runtime also keeps a background MQTT subscriber for configured devices and their `<base_topic>/<friendly_name>/availability` topics

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
docker build -t piphinetwork/zigbee-integration:0.1.0 .
docker run --rm -p 8730:8730 piphinetwork/zigbee-integration:0.1.0
```
