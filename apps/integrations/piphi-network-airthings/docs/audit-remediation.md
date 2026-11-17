# Airthings quality-audit remediation

This package uses the official Airthings Consumer API and remains independent
from BACnet. The release bar is automated provider-contract testing plus
qualification of the exact container image. Physical-device testing is optional
follow-up evidence.

| Audit requirement | v0.1.8 and later contract |
| --- | --- |
| Explicit account/device selection | `account_id` is required. Discovery returns a stable opaque `device_ref`; the runtime never selects the first account or device. Duplicate account/device configurations are rejected. |
| Secret and household-data containment | Credentials use `SecretStr`. Account IDs, serial numbers, device names, homes, segments, raw payloads, and upstream bodies are excluded from state, telemetry, events, diagnostics, discovery, and errors. |
| Provider pagination | The documented sensor `pageNumber`/`hasNext`/`totalPages` contract is followed with 20-page and 1,000-record hard limits. Device discovery is capped at 500 records. |
| Rate limits and cadence | `X-RateLimit-Retry-After` is honored with a one-hour cap. Polling has a six-minute minimum and one shared client/token cache. |
| Source freshness | Source observation and fetch times are separate. Timezone-naive/malformed and materially future samples are rejected; samples older than one hour are marked stale. |
| Outage and reauthentication | Last good values are retained with `available=false` and `stale=true`. Authentication, quota, transient provider, and runtime failures have distinct redacted classes. Recovery/failure events emit only on transitions. |
| Diagnostics | Authenticated, aggregate, and allowlisted: counts plus freshness timestamps only. |
| Release evidence | Unit/provider-contract tests and `scripts/qualify_release_image.py` cover the exact image, restart replay, runtime auth, provider calls, telemetry state, and privacy surfaces. |

Registry publication must remain `draft`, `unverified`, and rollout `0` until a
separate promotion decision is made.
