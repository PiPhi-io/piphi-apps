# Matter hardware qualification

The machine-readable status is in [`hardware-qualification.json`](hardware-qualification.json).
Physical support is not inferred from the passing virtual-device test.

For the Wi-Fi On/Off plug profile, run the guided physical workflow from an interactive terminal:

```bash
MATTER_IMAGE=piphi-matter-js-sidecar:qualification npm run qualify:physical-hardware
```

The wizard never persists the setup payload. It uses isolated named volumes, stops the source
controller before starting its restored clone, requires human confirmation of physical On/Off and
decommissioned states, validates the final report, and updates the ledger only after every stage
passes. Do not run it without physical access to the plug.

## Required evidence

Each required Ethernet/Wi-Fi profile stays `pending_hardware` until one record contains:

- vendor, model, hardware revision, firmware version, and transport;
- qualification date, operator, sidecar image digest, and host/network description;
- the redacted `/v1/preflight` result;
- commissioning and negotiated On/Off endpoint evidence;
- `turn_on` and `turn_off` results confirmed by subscription-backed state;
- sidecar restart and empty-volume controller-restore recovery;
- confirmed node-scoped decommissioning and cleanup; and
- a durable log or report path committed with the result.

Never commit setup payloads, Wi-Fi credentials, Thread datasets, fabric credentials, IP addresses,
or unredacted diagnostics. Hash controller identity before recording it, as the sidecar already does.

Validate each completed JSON report before adding it to a profile's evidence:

```bash
npm run validate:hardware-report -- path/to/redacted-report.json
```

The validator requires exact release/profile matching, immutable image digest, device and firmware
metadata, timestamps, hashed controller identity, every required step, and at least one durable
artifact. It rejects credential-like keys and Matter setup payloads. A `qualified` result is valid
only when every required step passed.

## Status meanings

- `pending_hardware`: no qualifying physical device evidence exists.
- `qualified`: every required step passed on the named device and release image.
- `failed`: the run completed but at least one required step failed; retain the failure evidence.
- `blocked`: the device exists, but an external prerequisite prevented a complete run.

BLE and Thread evidence must not change an Ethernet/Wi-Fi profile to qualified. They remain
experimental until separate adapter, border-router, deployment, and representative-device gates
are defined and passed.

Reports may include the optional `ble_wifi_provisioning` step when a factory-reset device was
discovered over BLE and provisioned onto Wi-Fi before completing the ordinary Wi-Fi lifecycle.
Optional transport steps are not requirements for unrelated Ethernet or already-on-network runs.
