# PiPhi MQTT Broker

`piphi-mqtt-broker` is a small TypeScript-managed broker project for PiPhi.

It packages a Mosquitto broker as a PiPhi `platform_service`, and uses TypeScript to:

- read broker settings from environment variables
- generate `mosquitto.conf`
- provide a clean Docker image entrypoint

## What This Project Owns

- the broker container image
- the platform-service manifest
- broker config generation
- default volume and port layout

## Why TypeScript Here?

The broker itself is still Mosquitto.

TypeScript is only handling the config/runtime glue so the project stays easy to read and easy to extend later with:

- richer validation
- generated password/auth files
- TLS settings
- WebSocket listener support
- health helpers

## Environment Variables

- `MQTT_HOST`
- `MQTT_PORT`
- `MQTT_ALLOW_ANONYMOUS`
- `MQTT_PERSISTENCE`
- `MQTT_PERSISTENCE_LOCATION`
- `MQTT_LOG_DEST`
- `MQTT_USERNAME`
- `MQTT_PASSWORD`
- `MQTT_PASSWORD_FILE`
- `MQTT_CONFIG_OUTPUT`
- `MQTT_TOPIC_PREFIX`

## Local Commands

```bash
npm install
npm run print-config
npm run build
npm test
```

## Docker Build

```bash
docker build -t piphinetwork/mqtt-broker:0.1.0 .
```

## Example Run

```bash
docker run --rm \
  -p 1883:1883 \
  -e MQTT_USERNAME=piphi \
  -e MQTT_PASSWORD=changeme \
  piphinetwork/mqtt-broker:0.1.0
```

By default, anonymous MQTT clients are disabled. If you do not want to set credentials for local testing, start the broker with:

```bash
docker run --rm \
  -p 1883:1883 \
  -e MQTT_ALLOW_ANONYMOUS=true \
  piphinetwork/mqtt-broker:0.1.0
```

## Release

Use the GitHub Actions `Release` workflow to publish `piphinetwork/mqtt-broker:<version>` to Docker Hub, tag the repo, and create a GitHub release. Choose `current` for the first `0.1.0` publish, or choose a semantic version bump for later releases.

## Platform Service Manifest

The broker manifest lives at [src/manifest.json](/home/kelvinfor3xzorin/Documents/PiPhi/piphi-mqtt-broker/src/manifest.json) and uses:

- `kind: "platform_service"`
- Linux container runtime
- persistent config/data/log volumes
- exported MQTT env values for consumers

## Next Good Improvements

- add TLS cert support
- add WebSocket MQTT listener support
- add health/status topic publishing
- add a PiPhi install flow for managed platform services
