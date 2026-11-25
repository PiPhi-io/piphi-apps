# PiPhi BLE Gateway Sidecar

Cross-platform BLE observation transport for PiPhi integrations. Production scanning uses continuous
`BleakScanner` detection callbacks: BlueZ through Bleak on Linux and WinRT through Bleak on Windows.
Linux-specific D-Bus diagnostics and recovery are optional capability adapters and are never imported
or required by the Windows path.

## Implemented boundary

- Versioned `piphi.ble.observation.v1` envelopes with opaque, persisted-secret-keyed device handles.
- No raw MAC address or device name in observations, checkpoints, health, diagnostics, or errors.
- Bounded matcher registration and deterministic `active > auto > passive` scan arbitration.
- Isolated bounded consumer queues with coalescing/drop counters, snapshots, and bounded replay.
- Deduplication, out-of-order rejection, clean scanner restart, and age-checked marked restart replay.
- Linux-only BlueZ Adapter1/rfkill diagnostics and supervised recovery behind an optional capability adapter; WinRT never imports D-Bus.
- Scoped in-memory BTHome bind-key mediation. Authenticated plaintext is delivered only to the matching consumer and keys never enter checkpoints or diagnostics.
- Deterministic fake scanner and fake D-Bus transports for lifecycle, recovery, malformed-input, queue-pressure, and encryption simulation.

Remote receivers, private/rotating identity resolution, GATT, pairing, and destructive host controls are
not implemented. The capability catalog records those as planned or excluded rather than advertising them.

## Consumer API

Configure `PIPHI_BLE_HANDLE_KEY_PATH` and `PIPHI_BLE_CHECKPOINT_PATH` on a
persistent, access-controlled path. Provision each integration with a distinct,
high-entropy bearer token and only the opaque handles it is allowed to select.

- `PUT /v1/ble/consumers/{consumer_id}` — consumer-token registration with a
  bounded manufacturer/service/device-handle matcher, scan mode, and queue capacity.
- `DELETE /v1/ble/consumers/{consumer_id}` — consumer-authorized removal.
- `GET /v1/ble/observations/{consumer_id}?after=&limit=` — consumer-authorized bounded replay.
- `GET /v1/ble/snapshot/{consumer_id}` — latest matching observations.
- `GET /health` — the sole public route, including dependency-aware readiness.
- `GET /diagnostics` — Core-authenticated scanner/backend/receiver/queue health and counters.

An empty catch-all matcher is rejected. Matcher categories are conjunctive, so a
service UUID cannot broaden an explicit device-handle scope. Consumer tokens are
stored only as SHA-256 digests in memory.

## Platforms and packaging

Linux remains the OCI release target. The same namespaced release also publishes a
platform-neutral Python wheel, qualified on `windows-latest`, for the manifest's
Windows proxy runtime. Installing that wheel provides the supervised
`piphi_ble_gateway_sidecar` executable and lets Bleak select WinRT without D-Bus.

## Installation and removal

PiPhi installs the Linux OCI image as a singleton platform service on a private
application network shared with compatible parents. Select the approved adapter
(or `default`), mount `/var/lib/piphi/ble-gateway`, the system bus socket
read-only, and `/sys/class/rfkill` read-only. The image runs as UID/GID `65532`
with a read-only root filesystem; the persistent directory must be owned by that
identity and mode `0700`. No privileged container, host network, blanket `/dev`,
or broad capability grant is required. Windows installs the wheel from the matching
GitHub release and supervises the `piphi_ble_gateway_sidecar` entry point.

BlueZ mediation is intentionally narrow: `GetManagedObjects` reads Adapter1
health and `org.freedesktop.DBus.Properties.Set` may set `Powered=true` only on
the configured adapter. The host D-Bus policy must grant only those calls to UID
`65532`, plus the ordinary discovery calls Bleak requires. Core provisions a
high-entropy consumer token to the parent and does not expose the sidecar port
outside the private network.

Before removal, deconfigure parent consumers so their registrations are deleted.
Then stop the supervised process and remove the container or wheel. The handle
key and checkpoint may be deleted when stable handles and restart replay are no
longer needed; neither file contains raw Bluetooth addresses.

## Automation

The service exposes the idempotent `refresh` action. Runtime configuration and
command audit events are `runtime.config.applied`, `runtime.config.removed`, and
`runtime.command.received`. It defines no user automation conditions or BLE
device triggers; parent integrations own device semantics.

## Troubleshooting and limitations

- `adapter_powered=false` or an rfkill flag identifies host radio state; the
  gateway may only power the configured adapter and never performs a broad reset.
- A failed scanner start remains retryable and the supervisor retries after the
  configured adapter or BlueZ daemon returns.
- Remote receivers, rotating/private identity resolution, pairing, connection
  slots, and GATT are not part of this release.
- Diagnostics intentionally omit addresses, names, keys, raw advertisements,
  and the D-Bus object tree.
- BlueZ discovery is host-global. Multiple consumers are arbitrated to one
  effective scan mode (`active > auto > passive`), but unrelated host BLE
  software can contend for discovery and radio airtime. This can delay or drop
  advertisements. The tests simulate transport behavior; they do not qualify a
  physical adapter, antenna, device model, room, range, or RF environment.

## Validate

```bash
pdm install -G dev --check
pdm run pytest
pdm run python scripts/validate.py
pdm export --prod --output /tmp/piphi-ble-gateway-sidecar-requirements.txt
pdm run pip-audit --disable-pip -r /tmp/piphi-ble-gateway-sidecar-requirements.txt
docker build -t ghcr.io/piphi-io/piphi-ble-gateway-sidecar:0.4.0 .
```

Deterministic fake-D-Bus evidence covers configured-adapter power loss,
disappearance, reappearance, retryable scanner startup, and least-privilege
recovery. Physical hardware evidence remains useful compatibility input, not a
release or quality-tier gate.
