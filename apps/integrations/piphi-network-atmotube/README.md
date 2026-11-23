# piphi-network-atmotube

PiPhi runtime integration for monitoring an Atmotube Pro using Go, Gin,
`piphi-runtime-kit-go`, and `tinygo.org/x/bluetooth`.

This package reads the documented current-value GATT characteristics. It does
not control the device, backfill history, infer additional entities, or claim
physical model/firmware qualification from its simulated CI evidence.

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
- restores permission-restricted runtime configuration after restart
- marks repeated read failures stale and emits one stale/recovery transition per outage

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
- `POST /command` (`refresh` only)

Only `GET /health` is public. Every other route requires the exact
`X-PiPhi-Integration-Token` value supplied through
`PIPHI_INTEGRATION_INTERNAL_TOKEN`; when that environment variable is absent,
operational routes return `503` rather than running unauthenticated.

## Configuration payload

`POST /config`

```json
{
  "id": "bedroom-atmotube",
  "container_id": "runtime-123",
  "integration_id": "piphi-network-atmotube-pro",
  "address": "11:22:33:AA:BB:CC",
  "alias": "Bedroom Atmotube",
  "poll_interval_seconds": 30
}
```

The Bluetooth address is treated as private configuration. Runtime responses,
events, diagnostics, and logs use an opaque HMAC identity and recursively redact
addresses and secret-shaped fields. The HMAC key and configs are atomically
stored in `PIPHI_ATMOTUBE_STATE_PATH` (default
`/var/lib/piphi-atmotube/state.json`) with mode `0600` so identity remains stable
across restart. Protect the containing volume with the host's storage controls.

## Shared Bluetooth gateway strategy

This integration currently owns one direct TinyGo/BlueZ adapter session and
serializes scans and connections inside the process. Run **one replica per
physical Bluetooth adapter**. It does not coordinate adapter access with other
containers or implement a remote BLE gateway protocol. For a shared host, use a
single PiPhi BLE gateway/sidecar that explicitly supports multiplexing instead
of starting competing Atmotube replicas. That gateway migration is not part of
this monitoring-only package.

On Linux, D-Bus `EXTERNAL` authentication uses the process UID reported by the
host kernel. Run the image as a dedicated, host-resolvable unprivileged account;
the image's default UID `65532` only works when that UID also resolves on the
host. Grant that identity narrowly scoped BlueZ D-Bus permission and mount the
system bus socket read-only. Do not use `--privileged` or
`apparmor=unconfined` as a substitute.

## Container operation

The release artifact is a digest-pinned, multi-stage, static, non-root OCI image.
Its root filesystem can be read-only; only the state directory is writable.
Create a dedicated host account and state directory, then load the reviewed
AppArmor profile (the exact account-management command is distribution-specific):

```bash
PIPHI_ATMOTUBE_UID="$(id -u piphi-atmotube)"
PIPHI_ATMOTUBE_GID="$(id -g piphi-atmotube)"
sudo install -d -o "$PIPHI_ATMOTUBE_UID" -g "$PIPHI_ATMOTUBE_GID" \
  -m 0700 /var/lib/piphi-atmotube
sudo install -m 0644 deploy/apparmor/piphi-atmotube-ble \
  /etc/apparmor.d/piphi-atmotube-ble
sudo apparmor_parser -r -W /etc/apparmor.d/piphi-atmotube-ble
```

Run the container with that same UID and GID:

```bash
docker run --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --security-opt apparmor=piphi-atmotube-ble \
  --user "$PIPHI_ATMOTUBE_UID:$PIPHI_ATMOTUBE_GID" \
  --tmpfs /tmp:rw,nosuid,nodev,noexec \
  --mount type=bind,src=/var/lib/piphi-atmotube,dst=/var/lib/piphi-atmotube \
  --mount type=bind,src=/run/dbus/system_bus_socket,dst=/var/run/dbus/system_bus_socket,readonly \
  -e PIPHI_INTEGRATION_INTERNAL_TOKEN \
  -p 2026:2026 ghcr.io/piphi-io/piphi-network-atmotube:0.1.7
```

TinyGo's Linux backend opens `/var/run/dbus/system_bus_socket`, even when the
host exposes the same socket at `/run/dbus/system_bus_socket`. Docker's default
AppArmor profile blocks D-Bus messages, so select the supplied profile rather
than disabling AppArmor. Installing the profile under `/etc/apparmor.d` lets the
host AppArmor service reload it after reboot. The host's D-Bus authorization
remains deployment-specific; the image does not request privileged mode, host
networking, or a writable root filesystem.

## Local development

This project expects:

- a working BLE stack on the host
- BlueZ on Linux for scanning / connecting
- Go 1.25

When you have the Go toolchain available, run:

```bash
gofmt -w .
go mod verify
go test -race ./...
go vet ./...
CGO_ENABLED=0 go build -trimpath -o dist/piphi-network-atmotube .
```

The runtime listens on `http://127.0.0.1:2026`.

For deterministic hardware-free development, set
`PIPHI_ATMOTUBE_SIMULATION=1` and configure address `02:00:00:00:00:01`.
Simulation uses fixed fixtures and scripted failures; it is not discovery or
physical-device evidence and must not be enabled in production.

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
- Example IDs, MAC addresses, and tokens in tests are placeholders.
- A production-shaped Linux container was physically qualified with one
  Atmotube Pro and one BlueZ adapter on 2026-11-23. With simulation disabled,
  the run verified filtered discovery, current-value GATT reads, repeated
  ten-metric polling, bounded recovery from a transient connection abort,
  private-address redaction, persisted configuration restoration, and polling
  after a confined container restart. The container ran non-root with a
  read-only root filesystem, all capabilities dropped, `no-new-privileges`, and
  the supplied AppArmor profile.
- Qualification remains outstanding for additional device firmware and host
  adapter variants, a forced stale-to-recovered physical outage, extended
  reconnect/radio-contention soak behavior, delivery to a live PiPhi Core, and
  physical measurement accuracy. The single tested setup is not evidence for
  those variants or gaps.

## Device contract references

- Atmotube Bluetooth API: https://support.atmotube.com/en/articles/10364981-bluetooth-api
- Atmotube Bluetooth API specification: https://support.atmotube.com/en/articles/10449987-bluetooth-api-specification
- TinyGo Bluetooth package: https://pkg.go.dev/tinygo.org/x/bluetooth
