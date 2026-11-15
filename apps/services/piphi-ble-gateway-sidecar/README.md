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
- Optional platform-capability seam for future BlueZ diagnostics/recovery without coupling WinRT to D-Bus.

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
- `GET /health` and `GET /diagnostics` — scanner/backend/receiver/queue health and counters.

An empty catch-all matcher is rejected. Matcher categories are conjunctive, so a
service UUID cannot broaden an explicit device-handle scope. Consumer tokens are
stored only as SHA-256 digests in memory.

## Platforms and packaging

Linux remains the OCI release target. The manifest also declares the repository-supported Windows proxy
shape, supervising the installed `piphi_ble_gateway_sidecar` Python executable so Bleak selects WinRT.
This package does not contain a Windows executable/wheel publishing workflow; repository-level release
automation must install/package the Python project on Windows before that deployment can be distributed.

## Validate

```bash
pdm install -G dev --check
pdm run pytest
pdm run python scripts/validate.py
pdm export --prod --output /tmp/piphi-ble-gateway-sidecar-requirements.txt
pdm run pip-audit --disable-pip -r /tmp/piphi-ble-gateway-sidecar-requirements.txt
docker build -t ghcr.io/piphi-io/piphi-ble-gateway-sidecar:0.2.0 .
```

Deterministic fake-D-Bus or virtual-radio soak evidence for BlueZ daemon restart,
adapter loss/reappearance, rfkill, and least-privilege recovery remains required
before production promotion. Physical hardware evidence is useful but not a gate.
