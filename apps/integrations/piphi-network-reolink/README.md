# PiPhi Network Reolink

Local, monitoring-first Reolink camera and NVR integration for PiPhi Network. The runtime uses
[`reolink_aio`](https://github.com/starkillerOG/reolink_aio) for authenticated
device access and represents NVR channels as child camera entities.

This repository is an **integration runtime**, not a sidecar. It owns Reolink
configuration, discovery, entities, state, events, and commands. Authenticated
media URLs are deliberately excluded; live video, snapshots, and recording will
be brokered through PiPhi's shared camera gateway in a later milestone.

## Supported scope

Implemented:

- setup-time connection and credential verification with secret redaction
- transactional reauthentication and reconfiguration
- camera and NVR channel discovery
- stable, privacy-preserving hardware identity and duplicate prevention
- host and channel availability with retained stale inventory
- bounded concurrent polling, retry backoff, and wake-safe battery handling
- read-only explicit refresh
- capability coverage ledger and contract tests

Planned capabilities and deliberate exclusions are recorded in
`capability-catalog.json`.

Supported devices must expose the local API and stable MAC or UID identity. Powered standalone
cameras, powered video doorbells, and NVRs are the qualified software scope. Battery cameras,
dual-lens variants, Home Hub devices, media, detection events, and camera controls remain
unqualified and are not advertised as complete.

## Install and configure

1. Update the Reolink device to current firmware and enable its local HTTP or HTTPS API.
2. Create a dedicated Reolink account. Read-only access is preferred for this monitoring slice.
3. Ensure PiPhi can reach the device on its configured API port (normally 80 or 443). Internet
   access is not required.
4. Install **Reolink cameras** from the PiPhi registry, then enter the local address, account,
   optional port/HTTPS setting, display name, and polling interval.
5. Setup succeeds only after credentials, connectivity, and stable hardware identity are verified.

The minimum polling interval is 60 seconds. Devices reporting battery or sleeping capability use
at least 15 minutes between refreshes. PiPhi preserves last-known inventory and marks it stale
during an outage. An authentication failure reports that reauthentication is required.

The container must receive `PIPHI_INTEGRATION_INTERNAL_TOKEN`; every route except `/health`
fails closed without it. `PIPHI_ALLOW_UNAUTHENTICATED=true` is for isolated development only.

## Automations

- **Trigger — Reolink connection configured:** fires after a verified configuration is committed.
- **Condition — Connection state is:** checks the non-stale `connected` state.
- **Action — Refresh cameras:** performs one read-only refresh for exactly one configured host.

Refresh does not change camera settings. Availability events establish a baseline, deduplicate
outages, and report a single restored transition after recovery.

## Remove

Remove the integration from PiPhi's **Settings → Integrations** page. PiPhi deconfigures every
host, logs out active Reolink sessions, and removes the runtime container. If uninstalling
manually, stop the container and remove the `piphi-network-reolink-data` volume after confirming
you no longer need its local action ledger. Removing the integration does not change the Reolink
account or device settings.

## Troubleshooting

- **Invalid authentication:** verify the dedicated account and re-enter credentials.
- **Privacy mode / firmware required:** disable privacy mode or update firmware, then retry.
- **Cannot connect:** confirm local routing, API enablement, port, and HTTP/HTTPS selection.
- **Already configured / identity mismatch:** update the existing entry rather than adding the
  same hardware again; replacement hardware must be configured as a new device.

Share `/diagnostics` output when requesting support. It omits host addresses, usernames, config
IDs, hardware identifiers, and credentials.

## Development

```bash
pdm install -G dev
pdm run pytest
pdm run ruff check src tests
pdm run python scripts/validate.py
pdm run uvicorn piphi_network_reolink.main:app --reload --port 4225
```

The runtime exposes the common PiPhi endpoints including `/health`, `/config`,
`/config/sync`, `/entities`, `/state`, `/events`, and `/command`.

Credentials remain only in the runtime's private configuration object and are excluded from
entity state, telemetry, events, logs, and diagnostics.

## Container

```bash
docker build -t ghcr.io/piphi-io/piphi-network-reolink:0.2.0 .
docker run --rm -p 4225:4225 \
  -e PIPHI_INTEGRATION_INTERNAL_TOKEN=replace-me \
  ghcr.io/piphi-io/piphi-network-reolink:0.2.0
```

Version 0.2.0 meets the adapted Home Assistant Bronze software rules. Registry qualification
remains unverified until the published hardware matrix is completed; rollout therefore remains
limited beta.
