# Zigbee2MQTT Sidecar

PiPhi sidecar service for Zigbee2MQTT bridge setup.

This repo is the bridge helper foundation, not the final user-facing Zigbee
integration. Its job is to give PiPhi a stable local API for:

- detecting Zigbee coordinator adapters
- rendering and writing Zigbee2MQTT `configuration.yaml`
- reporting bridge-side setup state
- supporting Linux container use and Windows/macOS proxy use

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_zigbee2mqtt.main:app --reload --port 8720
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `8720` by default and exposes the common PiPhi runtime route contract:

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

Bridge-specific routes:

- `GET /v1/snapshot`
- `GET /v1/adapters`
- `POST /v1/config/render`
- `POST /v1/config/write`
- `POST /v1/apply`
- `POST /v1/prerequisites`
- `POST /v1/supervisor/status`
- `POST /v1/supervisor/start`
- `POST /v1/supervisor/stop`
- `POST /v1/supervisor/restart`
- `POST /v1/supervisor/logs`
- `POST /v1/mqtt/check`
- `POST /v1/devices`
- `GET /v1/devices`
- `POST /v1/network-map`
- `GET /v1/network-map`
- `POST /v1/permit-join`

## Render a Zigbee2MQTT Config

```bash
curl -s http://127.0.0.1:8720/v1/config/render \
  -H 'content-type: application/json' \
  -d '{
    "config": {
      "mqtt": {
        "server": "mqtt://127.0.0.1:1883",
        "base_topic": "zigbee2mqtt"
      },
      "serial": {
        "port": "/dev/ttyZigbee",
        "adapter": "ember"
      },
      "runtime": "docker",
      "data_path": "/app/data"
    }
  }'
```

For Windows/macOS proxy mode, use the native coordinator path:

```json
{
  "serial": {
    "port": "COM4",
    "adapter": "zstack"
  },
  "runtime": "native"
}
```

## Supervise Zigbee2MQTT

Linux Docker mode:

```bash
curl -s http://127.0.0.1:8720/v1/supervisor/start \
  -H 'content-type: application/json' \
  -d '{
    "mode": "docker",
    "docker": {
      "image": "ghcr.io/koenkk/zigbee2mqtt:latest",
      "container_name": "piphi-zigbee2mqtt",
      "host_data_path": "/var/lib/piphi/zigbee2mqtt",
      "container_data_path": "/app/data",
      "device_path": "/dev/serial/by-id/usb-coordinator",
      "frontend_port": 8080
    }
  }'
```

Windows/macOS PM2 mode:

```bash
curl -s http://127.0.0.1:8720/v1/supervisor/start \
  -H 'content-type: application/json' \
  -d '{
    "mode": "pm2",
    "pm2": {
      "process_name": "piphi-zigbee2mqtt",
      "working_dir": "/opt/zigbee2mqtt",
      "script": "index.js"
    }
  }'
```

Set `"dry_run": true` on any supervisor request to see the planned commands
without executing Docker or PM2.

Collect recent logs:

```bash
curl -s http://127.0.0.1:8720/v1/supervisor/logs \
  -H 'content-type: application/json' \
  -d '{
    "mode": "docker",
    "tail": 100,
    "docker": {
      "host_data_path": "/var/lib/piphi/zigbee2mqtt",
      "container_name": "piphi-zigbee2mqtt"
    }
  }'
```

Check MQTT broker reachability:

```bash
curl -s http://127.0.0.1:8720/v1/mqtt/check \
  -H 'content-type: application/json' \
  -d '{"server": "mqtt://127.0.0.1:1883"}'
```

Read the retained Zigbee2MQTT device inventory:

```bash
curl -s http://127.0.0.1:8720/v1/devices \
  -H 'content-type: application/json' \
  -d '{
    "server": "mqtt://127.0.0.1:1883",
    "base_topic": "zigbee2mqtt"
  }'
```

Scan the Zigbee mesh manually (the scan can make the network less responsive
for up to two minutes, so it is never scheduled automatically):

```bash
curl -s http://127.0.0.1:8720/v1/network-map \
  -H 'content-type: application/json' \
  -d '{"routes": false}'
```

Open pairing for 60 seconds:

```bash
curl -s http://127.0.0.1:8720/v1/permit-join \
  -H 'content-type: application/json' \
  -d '{
    "server": "mqtt://127.0.0.1:1883",
    "base_topic": "zigbee2mqtt",
    "time": 60
  }'
```

## Production Apply Flow

Use `/v1/apply` once PiPhi has selected the coordinator and MQTT settings. It
renders config, writes `configuration.yaml` atomically, compares hashes, and
restarts Zigbee2MQTT only when the restart policy says to.

```bash
curl -s http://127.0.0.1:8720/v1/apply \
  -H 'content-type: application/json' \
  -d '{
    "config_path": "/var/lib/piphi/zigbee2mqtt/configuration.yaml",
    "restart_policy": "changed",
    "config": {
      "mqtt": {
        "server": "mqtt://127.0.0.1:1883",
        "base_topic": "zigbee2mqtt"
      },
      "serial": {
        "port": "/dev/serial/by-id/usb-coordinator",
        "adapter": "ember"
      },
      "runtime": "docker",
      "data_path": "/app/data"
    },
    "supervisor": {
      "mode": "docker",
      "docker": {
        "host_data_path": "/var/lib/piphi/zigbee2mqtt",
        "device_path": "/dev/serial/by-id/usb-coordinator"
      }
    },
    "mqtt_check": {
      "server": "mqtt://127.0.0.1:1883",
      "timeout_seconds": 3
    }
  }'
```

Restart policies:

- `changed`: restart only when `configuration.yaml` changed
- `always`: restart after every apply
- `never`: write config but leave process state alone

Before applying, check host prerequisites:

```bash
curl -s http://127.0.0.1:8720/v1/prerequisites \
  -H 'content-type: application/json' \
  -d '{
    "mode": "docker",
    "docker": {
      "host_data_path": "/var/lib/piphi/zigbee2mqtt",
      "device_path": "/dev/serial/by-id/usb-coordinator"
    }
  }'
```

## Runtime Model

Linux:

- sidecar runs as a container
- `/dev/bus/usb` is mapped for coordinator access
- `/var/lib/piphi/zigbee2mqtt` is mounted as Zigbee2MQTT data

Windows/macOS:

- sidecar runs as a PiPhi proxy process
- Zigbee2MQTT itself should be supervised natively, for example by PM2
- serial ports are native paths like `COM4` or `/dev/cu.usbmodem1101`

## Docker Build

```bash
docker build -t piphinetwork/zigbee2mqtt-sidecar:0.1.0 .
docker run --rm -p 8720:8720 piphinetwork/zigbee2mqtt-sidecar:0.1.0
```

For live Linux adapter detection/config writes, run with the PiPhi-managed
volume and device mappings declared in `manifest.json`.
