# PiPhi Matter integration

This package is the Core-facing parent for the managed Matter sidecar. The parent owns stable PiPhi entity/device projection, aliases, capability normalization, command policy, telemetry delivery, and restart reconciliation. The existing sidecar remains the sole owner of the Matter fabric, subscriptions, commissioning, protocol state, and command transport.

## Initial supported slice

- One or more commissioned endpoints exposing `switch_on` and negotiated `turn_on`, `turn_off`, and `toggle` commands.
- Stable entity IDs in the form `matter:<controller-identity-hash>:<encoded-node-id>:<endpoint-id>` so replacing a fabric cannot collide with the previous controller.
- `GET/POST /config`, `GET /entities`, `GET /state`, `POST /telemetry`, and `POST /command`.
- Redacted `GET /diagnostics` and typed `GET /repairs` contracts for future PiPhi Core support workflows.
- Authenticated `GET /preflight` proxies controller, selected-interface, and IPv6 readiness without exposing addresses or credentials.
- Network-only commissioning plus an experimental, preflight-gated BLE/Wi-Fi provisioning API.
- Confirmed node-scoped decommissioning removes parent endpoint configuration only after the sidecar removes fabric membership.
- Confirmed backup quiesce/resume APIs let Core snapshot the sidecar volume while its exclusive fabric lease remains held.
- Authenticated sidecar snapshot and event polling.
- Cursor-expiry recovery by fetching a complete snapshot before resuming at the sidecar's latest cursor.
- Optional Core REST telemetry delivery using the Runtime/TestKit-compatible headers and payload.
- New and changed normalized entity state is pushed to Core automatically after snapshot reconciliation; delivery failures are reported separately from sidecar availability.
- Actual state transitions also emit the advertised `device.state_changed` Runtime SDK event; initial discovery emits telemetry but not a false transition.
- A two-process regression harness proves authenticated parent-to-sidecar commands, Core telemetry delivery, explicit event-gap recovery, sidecar stream restart detection, and stable entity identity.

## Runtime configuration

| Variable | Purpose |
|---|---|
| `PIPHI_MATTER_SIDECAR_URL` | Required sidecar base URL (for example `http://127.0.0.1:8710`). |
| `PIPHI_MATTER_SIDECAR_TOKEN` | Required in production; sent only as a sidecar Bearer token. |
| `PIPHI_MATTER_CONFIG_PATH` | Alias/config persistence path. |
| `PIPHI_MATTER_RECONCILE_INTERVAL_MS` | Event poll interval (minimum 250 ms). |
| `PIPHI_TELEMETRY_ENDPOINT` | Optional PiPhi Core telemetry endpoint. |
| `PIPHI_EVENTS_ENDPOINT` | Optional PiPhi Core event-ingest endpoint. |
| `PIPHI_CONTAINER_ID` | Container identity header for Core delivery. |
| `PIPHI_CONFIG_ID` | Core routing identity used in transition events. |
| `PIPHI_INTEGRATION_INTERNAL_TOKEN` | Optional Core delivery token; sidecar fallback only when its dedicated token is absent. |

Tokens and the sidecar URL are intentionally absent from public API responses. `/config` reports only whether authenticated sidecar access is configured.
Aliases and endpoint enablement are persisted against the hashed controller identity as well as
the node and endpoint IDs, preventing stale configuration from attaching to a replacement fabric.

## Commissioning and removal

The supported release accepts devices already reachable on Ethernet or Wi-Fi. Core first checks
`GET /preflight`, optionally lists `GET /commissioning/commissionables`, and then submits the
write-only setup payload to `POST /commissioning/code` with `network_only: true`. BLE and Thread
commissioning remain experimental. Factory-reset Wi-Fi devices may use experimental
`POST /commissioning/wifi` only when preflight reports `ready_for_ble_wifi: true`; setup payload,
SSID, and password are write-only and discarded after the request.

Experimental Thread commissioning uses `POST /commissioning/thread` with write-only setup payload
and operational dataset fields plus `experimental_acknowledgement: "thread"`. The dataset exists in
the sidecar only for that operation and is cleared after success or failure; Core must clear both
secret fields locally as well.

Removing fabric membership is intentionally node-scoped. `POST /nodes/:nodeId/decommission`
requires `confirm_node_id` to exactly match the URL. Successful removal also deletes the parent
aliases for that node. It is not equivalent to disabling one endpoint.

Disabling or uninstalling the parent integration must not delete the sidecar volume or silently
decommission devices. To retire the controller, decommission reachable nodes first, take a final
backup if retention is required, stop the sidecar, and only then explicitly remove its persistent
volume. Reinstalling the parent against a retained sidecar preserves the controller fabric and
stable entity identities.

Before copying controller storage, Core must call `POST /backup/quiesce` with the explicit
confirmation, snapshot the complete sidecar volume, and call `POST /backup/resume` in a finally
path. A restore targets an empty volume and must never run concurrently with its source.

## Automation

- **Condition:** `switch_on == true|false`, using reconciled state no older than 60 seconds.
- **Trigger:** `device.state_changed`, emitted only for an actual post-discovery state transition.
- **Actions:** `turn_on`, `turn_off`, and `toggle`; the parent rejects commands not negotiated for
  the selected endpoint and callers cannot override its Matter node, endpoint, or cluster target.

Example command body:

```json
{"entity_id":"matter:<controller>:<node>:1","command":"turn_on"}
```

State changes automatically send normalized telemetry and the transition event to Core. A Core
delivery outage appears as `matter_core_delivery_failed` in `/repairs` without falsely marking the
Matter controller or device unavailable.

## Known limitations

The supported product slice is On/Off lights and plugs reachable on-network. Brightness, color,
bridges, BLE, Thread, multi-admin sharing, physical-device qualification, and Core-native UI are
not release-qualified yet. The marketplace quality tier therefore remains `unrated`.

The required private-Core onboarding, repair, backup, and removal orchestration is specified in
[`docs/core-workflows.md`](docs/core-workflows.md), including acceptance cases and secret-handling
rules. That document is an implementation contract, not evidence that the private Core UI exists.

## Development

```bash
npm ci
npm run check
npm test
npm run test:coverage
npm run build
```

To qualify the exact OCI image before publishing it, build or pull the image and run:

```bash
docker build -t piphi-network-matter:candidate .
npm run qualify:release-image -- piphi-network-matter:candidate
```

The qualification runs the production parent image as its declared non-root user with host
networking and a named `/app/data` volume. It uses an authenticated sidecar fixture, verifies
production Core and sidecar authentication, then removes and recreates the parent container and
proves health, entity identity, alias projection, and persisted configuration still hold. The
harness removes its container and volume on success, failure, or termination. See
[`docs/release.md`](docs/release.md) for the release gate and troubleshooting details.

This package does not import the Matter service's source and does not replace, rename, or supervise it.
The standard test command includes a real two-process parent/sidecar/Core harness. The coverage
command scopes measurement to parent production modules, enforces a 95% line threshold, and
currently reports 100% lines overall and per module.

Sidecar HTTP failures are reduced to stable parent error codes rather than forwarding upstream
response bodies. This gives Core actionable commissioning/recovery categories without risking
setup-payload or credential disclosure.
