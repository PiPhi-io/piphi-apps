# piphi-network-atmotube

PiPhi runtime integration for the Atmotube Pro using Go, Gin, the local
`piphi-runtime-kit-go`, and `tinygo.org/x/bluetooth`.

## What it does

- scans nearby BLE devices and filters discovery down to Atmotube candidates
- discovers Atmotube Pro devices over Bluetooth Low Energy
- connects to a configured Atmotube Pro by Bluetooth MAC address
- performs a short pre-connect scan before opening the BLE session so BlueZ has a current device object to connect to
- reads the Atmotube GATT characteristics for:
  - VOC
  - humidity / temperature / pressure
  - battery and status
  - PM1 / PM2.5 / PM4 / PM10
- keeps the latest state in the runtime registry
- queues telemetry back to PiPhi Core through the Go runtime kit
- logs BLE connect/discovery/read progress and telemetry delivery outcomes for easier troubleshooting

## Runtime routes

- `GET /health`
- `GET /diagnostics`
- `GET /ui`
- `GET /discover`
- `POST /discover`
- `POST /config`
- `POST /config/sync`
- `POST /configs/sync`
- `POST /deconfigure`
- `GET /state`
- `GET /events`
- `GET /entities`

## Configuration payload

`POST /config`

```json
{
  "id": "bedroom-atmotube",
  "device_id": "bedroom-atmotube",
  "container_id": "runtime-123",
  "integration_id": "piphi-network-atmotube-pro",
  "address": "11:22:33:AA:BB:CC",
  "alias": "Bedroom Atmotube",
  "poll_interval_seconds": 30
}
```

## Local development

This project expects:

- a working BLE stack on the host
- BlueZ on Linux for scanning / connecting
- the local Go runtime kit at `../piphi-runtime-kit-go`

When you have the Go toolchain available, run:

```bash
go mod tidy
gofmt -w .
go test ./...
```

The runtime listens on `http://127.0.0.1:2026`.

## Logging and troubleshooting

Recent runtime updates added more explicit operational logging so it is easier to
see where a BLE session fails or succeeds.

Important log families include:

- `runtime_internal_auth`
- `bluetooth_preconnect_scan_*`
- `bluetooth_connect_*`
- `bluetooth_service_discovery_*`
- `bluetooth_characteristic_discovery_*`
- `bluetooth_snapshot_read_*`
- `bluetooth_disconnect_*`
- `telemetry_queue`
- `telemetry_delivery_succeeded`
- `telemetry_delivery_failed`

That logging is especially useful when the host BLE stack is healthy but the
runtime still needs a discovery pass before a connection can succeed.

## Notes

- The integration accepts both `/config/sync` and `/configs/sync` for snapshot rehydrate compatibility.
- Discovery now intentionally filters out unrelated BLE devices.
- Example IDs, MAC addresses, and tokens in tests or logs should be treated as placeholders.

## Device contract references

- Atmotube Bluetooth API: https://support.atmotube.com/en/articles/10364981-bluetooth-api
- Atmotube Bluetooth API specification: https://support.atmotube.com/en/articles/10449987-bluetooth-api-specification
- TinyGo Bluetooth package: https://pkg.go.dev/tinygo.org/x/bluetooth
