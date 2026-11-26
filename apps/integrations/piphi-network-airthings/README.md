# piphi-network-airthings

PiPhi runtime integration for the Airthings Consumer Cloud API.

This integration targets consumer Airthings accounts and polls the latest cloud sample for configured devices using an Airthings API client id and client secret created from the Airthings dashboard integrations page.

Automated tests and release qualification use only a deterministic local transport
that implements the documented Airthings OAuth, account, device, and sensor
contracts. They never use live credentials or contact an Airthings account. Live
account/device qualification remains unverified.

## Current scope

- Discovers devices only within an explicitly selected Airthings consumer account
- Uses a stable privacy-safe device reference outside the adapter; account IDs, serial numbers, names, homes, and segments stay inside the configuration/provider boundary
- Polls latest samples no faster than every six minutes, matching Home Assistant's quota-conscious cadence
- Reports a fresh Core health heartbeat on every successful poll while preserving
  the Airthings device timestamp on measurement telemetry. Repeated cloud samples
  therefore prove the connection is healthy without making old readings look new.
- Emits telemetry and runtime events on success and failure
- Supports refresh commands, config sync, diagnostics, and health endpoints through the PiPhi Python runtime SDK

The declared Consumer Cloud scope is implementation-complete and enforced by
`docs/capability-catalog.json`. Automated provider-contract tests and exact-image
qualification are release gates. Physical-device testing is optional follow-up
evidence, not a publication blocker.

Successful state keeps source observation time (`source_observed_at`) separate
from fetch time (`fetched_at`). Samples older than one hour are explicitly stale,
future or timezone-naive timestamps are rejected, and outages retain the last
good values with `available=false`, `stale=true`, and a redacted error class.

Diagnostics are authenticated and allowlisted. They contain aggregate counts and
freshness timestamps only—not credentials, account IDs, serial numbers, device
names, raw provider payloads, or upstream response bodies.

The manifest includes Marketplace Metadata v2 with explicit cloud-account,
credential, network-access, compatibility, privacy, and draft-governance
declarations. New registry publication remains `draft`, `unverified`, and at
zero rollout until a separate review promotes it.

## API assumptions

The implementation is based on Airthings’ published consumer API onboarding plus the shared Airthings OAuth/device endpoint patterns:

- Consumer API access is created from the Airthings dashboard integrations page
- OAuth tokens are issued by `https://accounts-api.airthings.com/v1/token`
- Device data is requested from the documented Consumer API `devices` and paginated `sensors` endpoints

Sensor pagination follows `pageNumber`, `hasNext`, and `totalPages` with hard page and record limits. Rate limiting honors `X-RateLimit-Retry-After` and avoids immediate retry loops.

## Local development

```bash
pdm install -G dev
pdm run uvicorn piphi_network_airthings.app:app --reload --port 3669
```

## Testing

```bash
pdm run pytest
```
