# Portfolio gap matrix

**Baseline:** source and registry revisions recorded in `inventory.json`.

This queue consolidates existing package audits. It is updated as the remaining
package audits finish and as remediations are merged. Severity describes user
risk, not implementation effort.

## P0 — publication and security blockers

| Batch | Packages | Evidence-backed gap | Required outcome | State |
|---|---|---|---|---|
| Truthful scaffold state | Daikin Onecta, Dyson, Eufy Security, Kia/Hyundai, Xiaomi Home | Configuration currently represents synthetic/demo state as connected even though no vendor vertical slice exists. | Report unsupported/not implemented honestly; remove synthetic discovery/control claims; then implement auth/discovery → read state → outage recovery → one bounded action where product authorization exists. | Audited; remediation pending |
| Vehicle credential boundary | Tesla EV | Bearer/config/VIN/location can cross discovery/state/diagnostic surfaces; user-controlled endpoint can receive authorization; OAuth, request budgets, and safe wake lifecycle are absent. | Contain/redact secrets and PII, enforce endpoint allowlist, disable unsafe wake path, add OAuth/reauth and request-budget semantics before real-account use. | Audited; remediation pending |
| Operational route authentication | BACnet, Android TV, 433MHz, Huawei Solar, I2C, SPI, MikroTik, pfSense, Plex, Steam, TP-Link, Midea, Zigbee parent, Passive BLE and other legacy runtimes | Management/state/diagnostic/action routes can be reachable without fail-closed app-level authorization. | Leave only `/health` public; constant-time token check every operational route; test missing/wrong/conflicting credentials and route enumeration. | BACnet remediation implemented; portfolio batch pending |
| Cloud secret and tenant boundary | Airthings, Kaiterra, WeatherXM | Plain secrets/raw payloads and silent first-account/station selection undermine privacy and stable identity. | Secret types and recursive redaction, explicit tenant/device selection, identity-preserving reauth/reconfigure, failure-injection tests. | Audited; partial Airthings remediation released |
| Unsafe generic writes | Tuya | Broad `set_dp` and heuristic cover/HVAC writes can mutate the wrong datapoint without model certification. | Remove from normal command surfaces or require advanced opt-in plus strict allowlists; gate consequential writes by certified profiles and post-write verification. | Audited; remediation pending |
| Provider/legal contract | Nord Pool, WeatherXM, Kia/Hyundai | Current endpoint or owner-service use lacks a clear supported/redistribution contract. | Product/legal decision or supported API migration; no technical change may imply authorization. | Blocked on governance decision |
| Stable registry integrity | Sense, Atmotube, Plex, Awair, GPS, TP-Link, ThinQ, Tesla, Kaiterra, WeatherXM, Tuya, SolarEdge | Stable/100% listings lack immutable evidence; Sense version/ref/image/source disagree and Atmotube lacks ref/artifact integrity. | Preserve governance state, correct only through reviewed source release and exact-digest registry PR; strengthen registry validation before any promotion. | Audited; remediation pending |

## P1 — reliability and lifecycle

| Batch | Packages | Gap | Required outcome | State |
|---|---|---|---|---|
| Cloud lifecycle | Airthings, Sense, SolarEdge, Kaiterra, WeatherXM, Aqara, ThinQ | Reauth, quota/backoff, stable identity, stale state, pagination, and removal behavior are uneven. | Typed auth/outage/rate-limit states; bounded jittered retry; last-good stale semantics; complete cleanup; behavior-focused tests. | In progress |
| Public data semantics | Octopus Energy, Nord Pool | Validity intervals, stale age, pagination proof, licensing/endpoint support, and long-term statistic semantics are incomplete. | Preserve source intervals and last-good stale data, prove bounded pagination, document exact product scope, resolve terms. | Audited; remediation pending |
| Scaffold-to-functionality | Bambu Lab, Daikin, Dyson, Eufy, Huawei Solar, Midea, OpenEPaperLink, Sonoff LAN, Tapo Cameras, WashData, Waste Collection, Xiaomi | Several packages have contracts/capability catalogs but little or no upstream behavior. | Implement one useful, architecture-correct vertical slice per package before release claims: onboarding, identity, state, recovery, and bounded action when safe. | Audit completion pending |
| Sidecar failure behavior | ADB, BLE, Matter, Modbus RTU, MQTT, Zigbee2MQTT, rtl_433, Z-Wave JS | Parent loss, reconnect, queue pressure, restart recovery, degraded health, and cleanup must be uniformly evidenced. | Synthetic dependency-loss/backpressure/restart tests and useful redacted diagnostics, without fabricating entities in infrastructure-only sidecars. | Partial; package review pending |

## P2 — meaningful breadth and delivery maturity

| Batch | Gap | Required outcome |
|---|---|---|
| Capability depth | Supported protocol/device slices remain narrower than credible user needs in several packages. | Expand only from authoritative protocol/vendor surfaces; keep machine-readable implemented/planned/excluded catalogs and negotiate per-device capabilities. |
| Entity and statistics semantics | Timestamp, reset, rate/counter, units, device grouping, event dedupe, and action availability vary. | Canonical units/types, stable IDs, explicit freshness/reset semantics, and representative contract fixtures. |
| Release discipline | Legacy-static packages lack central full CI and many registry entries still reference old Docker Hub releases or have source/registry drift. | Full package CI, locked tests/builds, immutable multi-arch GHCR release, verified labels/SBOM/provenance/attestations/non-root execution, then exact-digest registry PR. |
| Documentation and supportability | Setup/removal, privacy, limitations, troubleshooting, and diagnostics are uneven. | Homeowner-facing setup/removal/reauth docs, explicit privacy inventory, failure runbooks, accessible language, and redacted diagnostics schemas. |

## Testing policy

Use pytest-style behavior and contract tests with shared fixtures, synthetic
data, controlled clocks, failure injection, and mocked protocol boundaries.
Prioritize setup/unload, discovery, config/reauth, entity/device/state semantics,
actions, migrations, redaction, and important recovery paths. Coverage is a
signal only; do not duplicate framework behavior or exhaustively enumerate
low-risk permutations.
