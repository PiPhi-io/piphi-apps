# PiPhi Core Matter workflows

This is the Core adapter contract for the initial Ethernet/Wi-Fi On/Off release. The parent API
exists in this repository; presentation and orchestration in the private Core repository remain
unimplemented and must not be represented as complete.

All parent calls use the Runtime SDK headers `X-Container-Id` and
`X-PiPhi-Integration-Token`. Setup payloads and network credentials are write-only and must never
be copied into logs, events, diagnostics, task state, or browser history.

## Install and readiness

1. Start the sidecar with host networking, its dedicated persistent volume, and a generated
   sidecar token.
2. Start the parent with the loopback sidecar URL/token and Core runtime identity/token.
3. Wait for `GET /health` to return `200`.
4. Call `GET /preflight`; require `ready_for_on_network: true` for the qualified flow and
   `ready_for_ble_wifi: true` before showing experimental factory-reset Wi-Fi provisioning.
5. If preflight fails, present each failed check. Do not offer Thread as a workaround.

The sidecar and parent are one managed installation. Stopping or upgrading the parent must not
delete or recreate the sidecar volume.

## Commission an on-network device

1. Explain that the device must already be joined to Ethernet or Wi-Fi and be in commissioning
   mode.
2. Optionally call `GET /commissioning/commissionables?timeout_seconds=5` to aid identification.
3. Accept the QR/manual setup payload in a secret input and immediately send:

   ```json
   {"setup_payload":"<write-only>","network_only":true}
   ```

   to `POST /commissioning/code`.
4. Discard the payload after the request finishes.
5. Refresh `GET /entities`; show only endpoints negotiated by the sidecar.
6. Let the user set endpoint aliases through `POST /config`. Never infer unsupported controls from
   the device name or type.

## Experimentally provision a factory-reset Wi-Fi device

1. Require `ready_for_ble_wifi: true`; IP-only commissionable discovery may remain empty.
2. Accept setup payload, SSID, and password only in secret fields that disable persistence,
   analytics, browser history, and crash capture.
3. Send them once to `POST /commissioning/wifi`, then clear all three fields in `finally`.
4. Treat `409` as another provisioning attempt in progress and `503` as BLE/BlueZ unavailable.
5. Reconcile entities after every result because commissioning may have completed before a lost
   response. Never retry automatically with retained secrets.

The UI must state that BLE/Wi-Fi and Thread commissioning are experimental. A commissioning
failure does not authorize automatic node removal; refresh entities and
repairs first because upstream commissioning may have completed before response delivery failed.

Thread commissioning accepts the setup payload and active operational dataset only through the
one-shot `POST /commissioning/thread` Core flow, which maps to sidecar
`POST /v1/commission/thread`. The sidecar clears the dataset in a `finally` path after success or
failure and also clears any orphaned dataset during startup. Persistent Thread credential writes
are rejected. Core must clear both secret fields locally in its own `finally` path and must never
retry automatically with a retained dataset. The Core request must include
`experimental_acknowledgement: "thread"` after presenting its experimental-status warning.

Parent failures use stable safe codes: `matter_operation_rejected`, `matter_resource_not_found`,
`matter_operation_conflict`, `matter_sidecar_unavailable`,
`matter_sidecar_authentication_failed`, or `matter_sidecar_request_failed`. Core should localize
those codes and must not expect or display a raw upstream error body.

## Repairs and diagnostics

- Poll `GET /repairs` when health is degraded and display each stable issue ID once.
- `matter_sidecar_unavailable` blocks commands and commissioning.
- `matter_event_stream_not_initialized` indicates startup reconciliation is incomplete.
- `matter_core_delivery_failed` does not mean the Matter device is unavailable; local control may
  still work.
- Attach redacted `GET /diagnostics` and `/preflight` responses to support exports. Never include
  sidecar URLs, tokens, setup payloads, fabric keys, network credentials, or raw unrestricted
  Matter attributes.

## Backup and restore

1. Call `POST /backup/quiesce` with:

   ```json
   {"confirmation":"quiesce-matter-controller"}
   ```

2. Snapshot the complete sidecar volume while the controller remains quiesced and its lease held.
3. Always call `POST /backup/resume` in a `finally` path, even when snapshotting fails.
4. Restore only into an empty target volume while the source controller is stopped.
5. Start one restored sidecar, verify its hashed controller identity and health, then start the
   parent and wait for reconciliation.

Core must reject clone-style restore workflows that can run source and restored controllers at
the same time.

## Remove a device or integration

Removing one endpoint configuration is not Matter decommissioning. To remove fabric membership:

1. Show the whole node and every affected endpoint.
2. Require explicit confirmation.
3. Send `POST /nodes/:nodeId/decommission` with the exact same node ID in `confirm_node_id`.
4. Refresh entities and confirm the node disappeared before reporting success.

Uninstalling the parent must retain the sidecar volume by default. A full controller retirement is
a separate destructive flow: decommission reachable nodes, optionally take a final backup, stop
the sidecar, then explicitly delete its volume. If a node is offline, warn that local controller
deletion can leave stale fabric credentials on the device and may require a device factory reset.

## Core acceptance tests still required

- onboarding blocks when preflight fails and never exposes setup payloads;
- commissioning success, typed failure, uncertain-result reconciliation, and retry;
- repair deduplication and recovery dismissal;
- backup resume runs after both successful and failed snapshots;
- uninstall retains fabric storage by default;
- node removal shows blast radius and requires exact confirmation;
- parent/sidecar restart preserves entities, aliases, and controller-aware IDs; and
- mobile and desktop layouts remain usable for long device names and multiple endpoints.
