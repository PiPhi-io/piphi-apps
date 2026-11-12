# PiPhi Z-Wave JS Sidecar

Managed Node-native Z-Wave JS driver and controller transport for the PiPhi
Z-Wave integration.

## Ownership boundary

The sidecar owns the controller serial adapter, Z-Wave JS driver lifecycle,
server schema negotiation, node/value event transport, controller management
prompts, bounded command queues, backpressure, and restart reconciliation. The
parent integration owns normalized device entities, command-class capability
negotiation, state, telemetry, widgets, and behaviors.

The machine-readable `capability-catalog.json` inventories driver, controller,
radio, node event, inclusion/security, NVM, queue, and recovery behavior. Only
`connected` and `refresh` are implemented in this starter; network keys, raw
frames, unrestricted controller calls, and factory reset are excluded.

## Run locally

```bash
npm install
npm run dev
npm run build
npm run test
npm run validate
```

The runtime listens on port `4211` by default and exposes the common PiPhi runtime route contract:

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

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-zwave-js-sidecar:0.1.1 .
docker run --rm -p 4211:4211 docker.io/piphinetwork/piphi-zwave-js-sidecar:0.1.1
```
