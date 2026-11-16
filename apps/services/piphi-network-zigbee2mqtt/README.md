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
- `POST /v1/network-backup`
- `POST /v1/network-backup/export`
- `POST /v1/network-backup/import`
- `POST /v1/network-restore`
- `POST /v1/coordinator-migration/plan`
- `POST /v1/coordinator-migration/apply`

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

Linux Docker mode is delegated to Core's authenticated managed-runtime helper.
The sidecar does not run Docker commands and receives neither the Docker socket
nor coordinator devices:

```bash
curl -s http://127.0.0.1:8720/v1/supervisor/start \
  -H 'content-type: application/json' \
  -d '{
    "mode": "docker"
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

Set `"dry_run": true` on a PM2 supervisor request to see planned commands.
Docker requests only report Core ownership; Core performs the signed action.

Collect recent logs:

```bash
curl -s http://127.0.0.1:8720/v1/supervisor/logs \
  -H 'content-type: application/json' \
  -d '{
    "mode": "docker",
    "tail": 100
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
    "config_path": "/app/data/configuration.yaml",
    "restart_policy": "changed",
    "coordinator_identity": "usb-coordinator-serial-1234",
    "network_formation": "reuse_existing",
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
      "mode": "docker"
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

PiPhi persists an exclusive claim for `coordinator_identity`. Forming a new
network requires `network_formation: "form_new"` and
`confirm_form_new: true`. Changing an existing PAN, extended PAN, or network
key also requires `backup_path` and `backup_sha256` returned by
`POST /v1/network-backup`; the sidecar verifies the archive and checksum before
writing the change. Backups include the bounded Zigbee2MQTT data tree and
adapter/version compatibility metadata. `POST /v1/network-restore` requires a
stopped coordinator, a matching adapter family, explicit confirmation, and
creates a rollback backup before replacing data.

Encrypted export uses passphrase-derived AES-256-GCM with authenticated format
metadata. Export a verified backup with `POST /v1/network-backup/export`, retain
the returned checksum, and import it with `POST /v1/network-backup/import`.
Passphrases are never returned in responses.

Guided coordinator migration is a two-step flow. First call
`POST /v1/coordinator-migration/plan`; the sidecar verifies backup metadata,
adapter-family compatibility, and exclusive target availability. Then submit
the unchanged request, returned `plan_id`, and `confirm_migration: true` to
`POST /v1/coordinator-migration/apply`. The apply creates rollback evidence,
restores, rewrites the selected target, and automatically restores the rollback
backup if a post-restore step fails. Cross-family migration fails closed unless
the caller records a specific compatibility evidence reference.

Before applying, check host prerequisites:

```bash
curl -s http://127.0.0.1:8720/v1/prerequisites \
  -H 'content-type: application/json' \
  -d '{
    "mode": "docker"
  }'
```

## Runtime Model

Linux:

- sidecar runs non-root as UID/GID `1000:1000`
- sidecar has no Docker socket, broad USB mapping, privileged mode, or devices
- sidecar and Zigbee2MQTT share `piphi-helper-zigbee2mqtt-data`
- Core discovers stable `/dev/serial` links and maps only the selected device
  into the digest-pinned Zigbee2MQTT helper as `/dev/ttyZigbee`

Windows/macOS:

- sidecar runs as a PiPhi proxy process
- Zigbee2MQTT itself should be supervised natively, for example by PM2
- serial ports are native paths like `COM4` or `/dev/cu.usbmodem1101`

## Docker Build

```bash
docker build -t ghcr.io/piphi-io/zigbee2mqtt-sidecar:0.1.25 .
docker run --rm -p 8720:8720 ghcr.io/piphi-io/zigbee2mqtt-sidecar:0.1.25
```

For Linux, deploy through Core's managed-runtime helper contract. Running the
sidecar image alone does not grant coordinator or Docker authority.
