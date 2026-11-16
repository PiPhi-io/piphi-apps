# Cloud vehicle-account integration quality comparison

**Research cutoff:** 2026-11-16

**Repository revision audited:** [`e3eb2d3`](https://github.com/PiPhi-io/piphi-apps/tree/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e)
**Scope:** `piphi-network-tesla-ev` and `piphi-network-kia-hyundai-connect`, treated as high-risk integrations because an account token can expose precise location and vehicle state and, if command scopes are added, can affect physical access or vehicle operation.

## Executive verdict

| Package | Honest maturity slice | Release verdict |
|---|---|---|
| `piphi-network-tesla-ev` | A real, small Fleet API proof of concept: account vehicle listing, one-VIN status/data retrieval, and wake. It is **not** a production account integration: users paste an expiring access token, secrets and full VINs cross response surfaces, live `vehicle_data` has no budget/backoff policy, and sleep/staleness/error semantics are incomplete. | **Do not publish or enable for real accounts.** Block on P0 secret containment, OAuth lifecycle, endpoint trust, and request-budget work. After that, run a limited read-only pilot before reconsidering wake. |
| `piphi-network-kia-hyundai-connect` | A generic generated cloud-API scaffold. It does not log in to Kia, Hyundai, or Genesis; discover account vehicles; poll a vehicle; or execute a vehicle command. Its demo device and “connected: true” state are synthetic. | **Not an integration and not releasable.** Keep at 0% rollout. Build a separately qualified brand/region adapter or withdraw the marketplace claim. |

The two packages should not share a single quality label. Tesla has useful protocol code but unsafe lifecycle boundaries; Kia/Hyundai has safer non-implementation but misleading product metadata. Neither has real-account/real-vehicle evidence in this repository.

## Method and source limits

This is a source audit, not a road test. Evidence was taken from the checked-out packages, Tesla's owning Fleet API documentation, current first-party Home Assistant Tesla Fleet code/docs at immutable revisions, and Hyundai/Kia owner documentation. Hyundai Motor Group does **not** expose a public owner-account API contract comparable to Tesla Fleet in the sources found. Consequently, endpoint/auth implementation details are discussed only as requirements; the only implementation-oriented fallback is the community-owned [`hyundai_kia_connect_api`](https://github.com/Hyundai-Kia-Connect/hyundai_kia_connect_api/tree/12c6bf670876f8d2ab0b62801ee2edd71679d21b), which reverse-engineers regional owner services and is neither an official API nor authorization from Hyundai/Kia. Its evidence must not be presented as a stable vendor contract.

“Analogical IQS” below means an analogy to Home Assistant's Integration Quality Scale, not a Home Assistant certification or score. The reference Tesla integration itself still records open quality-scale items, including config-flow coverage, reconfiguration, stale devices, and test cleanup.[^ha-iqs]

## Evidence matrix

| Area | Tesla package evidence | Kia/Hyundai package evidence | Owning/reference behavior | Finding |
|---|---|---|---|---|
| Authentication and token lifecycle | Config requires a raw `access_token`; there is no authorization-code flow, refresh token, expiry, scope inspection, revocation, or differentiated reauth.[^tesla-manifest][^tesla-app] | Config asks for generic `host` and optional `api_key`; no owner account, password/PIN/OTP, consent, token, or regional login exists.[^kh-schema] | Tesla prescribes authorization code, `offline_access`, rotating single-use refresh tokens, and `login_required` handling.[^tesla-oauth] HA implements OAuth, account uniqueness, region selection, token refresh recovery, and reauth.[^ha-flow][^ha-coordinator] | **Tesla P0; Kia/Hyundai absent.** A pasted bearer is not an account lifecycle. |
| Secret containment | Discovery echoes the bearer in each device's `inputs`; registry entries retain the entire config; `/state` returns entries; diagnostic/event surfaces include full VINs. The manifest marks only `access_token` secret, not VIN/location.[^tesla-app][^tesla-manifest] | `api_key` is not declared as a manifest secret and is stored in `config.model_dump()` in the registry; the UI does not use a password widget.[^kh-manifest][^kh-state][^kh-contract] | HA diagnostics explicitly redact IDs, VINs, tokens, and all location variants.[^ha-diagnostics] | **P0 both.** Tesla has a directly demonstrated bearer disclosure path. |
| Endpoint/region trust | Correct NA/EU/CN defaults are present, but user-editable `base_url` receives the bearer; invalid regions silently become NA; no 421 region recovery exists.[^tesla-client][^tesla-app] | `base_url` and `host` are generic but unused. No brand/region matrix exists in runtime code.[^kh-schema] | HA derives region from the OAuth token, allows confirmation, and does not support China.[^ha-flow][^ha-docs] | Remove production URL overrides; resolve and validate region explicitly. |
| Vehicle identity and account shape | Discovery lists vehicles but does not paginate; each config duplicates account bearer and VIN. Runtime `deviceId` is the full VIN. No account-level unique ID, vehicle removal, or shared-driver privacy handling.[^tesla-client][^tesla-app] | Discovery always returns `demo-device`; identity is `host`, not account plus immutable vehicle identity.[^kh-discovery][^kh-manifest] | Tesla list is paginated (default 100), and shared vehicles can hide private data.[^tesla-endpoints] HA keys the config entry to the OAuth subject and dynamically creates products, while acknowledging stale-device cleanup is unfinished.[^ha-flow][^ha-iqs] | Tesla needs an account hub with per-vehicle children and masked identifiers; Kia/Hyundai has no identity model. |
| Polling, wake, cost, and limits | Refresh checks free summary then makes live `vehicle_data` only if online, which avoids an implicit wake. However, there is no scheduler, cache endpoint, Fleet Telemetry, configurable budget, 429/`Retry-After`, billing visibility, or concurrency control. Wake is exposed with two-attempt behavior metadata and no 10–60 s readiness loop.[^tesla-app][^tesla-behaviors] | `poll_interval_seconds` is unused; refresh records a local event and performs no network request.[^kh-state][^kh-commands] | Tesla says live `vehicle_data` should not be regularly polled, cached data never wakes the car but can be hours old, and Fleet Telemetry is preferred. Limits are 60 realtime-data, 3 wake, and 30 command requests/min/device/account; sub-500 responses are billable.[^tesla-endpoints][^tesla-billing] HA polls an awake vehicle every 10 minutes, backs off on rate-limit metadata, and pauses legacy vehicles to permit sleep.[^ha-docs][^ha-coordinator] Hyundai warns frequent status/location calls may drain the 12 V battery and says third-party automated use is unauthorized.[^hyundai-drain] | **Tesla P0 request-budget gap. Kia/Hyundai must not call private APIs without an explicit support/legal decision.** |
| State freshness and asleep/offline semantics | Summary state reports `online`, `asleep`, `offline`, or unknown, but detailed values become `null` whenever not online instead of preserving last-known values with source timestamps. `lastRefreshAt` is integration receipt time only. All refresh failures are flattened to strings; all action failures are labeled retryable.[^tesla-client][^tesla-app] | Applying config immediately reports `connected: true`; there is no upstream check, data age, stale flag, unavailable state, asleep state, or last success/error.[^kh-state] | Tesla cached blocks carry timestamps and may be hours old.[^tesla-endpoints] HA preserves coordinator data on asleep/offline and rate limits and distinguishes recoverable expiry from `LoginRequired`.[^ha-coordinator] Kia says remote commands can stop after 3–5 days of vehicle inactivity; 2026 model guidance also describes a seven-day battery-conservation cutoff, showing model/service variation.[^kia-help][^kia-ev6] | Preserve last-known values, attach upstream timestamps/age, and represent reachability independently from value validity. Never translate “configured” into “connected.” |
| Commands and physical safety | Only refresh and wake exist; no signed driving/access command exists. Durable idempotency is positive. Wake is labeled medium risk but lacks per-vehicle cooldown, budget, confirmation, readiness polling, and error-specific retry policy.[^tesla-readme][^tesla-app][^tesla-tests] | Only a fake refresh event exists. Planned lock/climate/charge actions in the catalog are correctly not advertised, but are not implementation evidence.[^kh-catalog][^kh-commands] | Tesla requires Vehicle Command Protocol/virtual-key flows for relevant vehicles; HA installs a per-vehicle virtual key and signs commands.[^ha-docs] Kia documents concrete preconditions for remote start/charge and inactivity shutdown.[^kia-help] | Keep Tesla read-only until wake controls exist; design future commands deny-by-default with fresh preconditions, explicit target, status tracking, idempotency, bounded retries, and confirmation by risk. |
| Location and privacy | `include_location` defaults **true**. False suppresses emitted coordinates but still calls unrestricted `vehicle_data`; no proof shows data minimization at request time. Coordinates, speed, heading, shift state, VIN, and state can flow to telemetry/state/events; there is no retention/consent explanation.[^tesla-manifest][^tesla-client][^tesla-app] | Privacy prose promises location handling and upstream-minimal requests although no upstream implementation exists; marketplace claims credentials and account discovery despite generic config/demo discovery.[^kh-privacy][^kh-manifest] | Tesla supports location-specific scope/endpoints and shared-driver privacy; location retrieval can show an in-car sharing icon.[^tesla-endpoints] Hyundai allows disabling remote location in the vehicle and makes location features unavailable when disabled.[^hyundai-location] | Default location off; request it only after separate consent/scope; honor vehicle-side denial; redact exact location/VIN everywhere; document retention and deletion. |
| Reauth/reconfigure | Posting config can replace values, but there is no guided OAuth reauth/reconfigure or account mismatch protection; expired token is a generic API error.[^tesla-app] | Generic config sync exists; there is no authentication to reauthenticate.[^kh-config] | HA has reauth and refresh recovery; its reconfigure quality item remains open.[^ha-flow][^ha-iqs] | Add explicit reauth and safe reconfigure with account identity pinning. |
| Diagnostics and observability | `/diagnostics` emits active IDs and full configured VINs; events emit VIN and raw exception strings. No redaction tests, request/cost counters, rate-limit state, token health, or data age.[^tesla-app] | Diagnostics are generic contract metadata. No upstream health exists. The privacy promise is not enforced by tests.[^kh-health][^kh-privacy] | HA has explicit redaction lists and snapshot tests.[^ha-diagnostics][^ha-diagnostics-test] | Diagnostics must be useful without identifiers: hashed account/vehicle handles, region/adapter versions, age, categorized errors, and budget counters. |
| Tests, CI, releases, and field evidence | Mock HTTP/runtime tests cover normalization, invalid envelopes, location output filtering, command validation, and idempotency; no OAuth, 421/429/408, stale cache, secret redaction, scheduler, pagination, billing, or live tests. Runtime constant says `0.2.0` while package/manifest say `0.2.3`.[^tesla-tests][^tesla-app][^tesla-package] | Tests check scaffold routes/catalog conformance, not a vendor adapter. Manifest and release docs still point to Docker Hub while portfolio publishing points to GHCR. Marketplace qualification is `unverified`, rollout 0.[^kh-tests][^kh-manifest][^kh-release][^kh-app] | Current HA pins an owning library and has broad component/config-flow/coordinator/diagnostic tests.[^ha-manifest][^ha-flow-test][^ha-diagnostics-test] | Both portfolio entries use `legacy-static` CI and skip container builds. No release qualification or real-account evidence is present.[^tesla-appmeta][^kh-app] |

## Package-by-package assessment

### `piphi-network-tesla-ev`

**What is genuinely good**

- Calls the official Fleet API rather than the legacy owner API, uses VIN-targeted routes, and separates summary from live data.
- Does not expose lock/unlock, remote start, climate, or charging commands without Vehicle Command Protocol support.
- Avoids calling live vehicle data when summary says the vehicle is not online.
- Supports output-level location suppression and durable command idempotency, and its mock tests cover those choices.

**Why it is still unsafe for real accounts**

1. **Bearer exfiltration is possible by design.** Discovery returns the bearer in its response, `/state` embeds registry entries containing config, and a user-editable URL override determines where the Authorization header is sent. These are release blockers, independent of route-level runtime authentication.
2. **The credential expires with no recovery.** There is no refresh token or consent flow, no account subject binding, no scope check, no revocation path, and no distinction between refreshable expiry and user-required reauth.
3. **Its “refresh” contract has no operating budget.** There is no periodic coordinator, but any UI/automation can trigger a billable live request. No rate-limit headers, 429 backoff, daily/monthly budget, cooldown, or shared-account contention is modeled.
4. **The state model erases knowledge.** A sleeping/offline read replaces detailed last-known values with nulls; a successful receipt timestamp is mistaken for upstream freshness; and raw errors are mixed into state. Automations cannot reliably distinguish “known old value,” “not supported,” “permission denied,” and “temporarily unreachable.”
5. **Privacy is opt-out and incomplete.** Location defaults on, while disabling it only filters downstream output. Full VINs are identifiers and should not be diagnostics/event labels. Speed/location/heading need a clear consent and retention boundary.

**Analogical IQS:** **Below Bronze / unrated.** Basic routes, tests, docs, idempotency, and entity naming exist, but the integration fails the spirit of safe config flow, test-before-configure, appropriate polling, secrets, reauth, diagnostics redaction, unavailable/stale semantics, and release evidence. It should not inherit quality from first-party HA Tesla Fleet.

### `piphi-network-kia-hyundai-connect`

**What is genuinely good**

- The README and capability catalog admit that vehicle features remain planned.
- Dangerous capability ideas are excluded from the advertised runtime, and the package is marked draft, unverified, and 0% rollout.
- Basic runtime contract/conformance tests and a privacy intent document exist.

**Why it is not yet auditable as a vehicle integration**

1. There is no HTTP client or owning library dependency, no regional endpoints, no login/token/PIN/OTP logic, no account/vehicle discovery, and no vehicle data parser.
2. Configuration uses a LAN-style `host`; discovery fabricates `demo-device`; applying any config sets `connected: true`; refresh merely records an event. Product claims of account discovery and supported owner services are therefore not runtime facts.
3. The privacy text describes data and requests that the package never processes. The generic `api_key` is not marked secret in the manifest/UI.
4. Official Hyundai US guidance explicitly warns that high-frequency third-party automation can drain the 12 V battery and says Bluelink use is authorized only through Hyundai-provided app/portal/voice integrations.[^hyundai-drain] There is no public official owner API contract found to justify a direct PiPhi client. Kia/Hyundai support must pass product/legal review, with clear disclosure that any community library is unofficial and breakage-prone.
5. The upstream community library illustrates, but cannot guarantee, the required complexity: region/brand-specific auth, token persistence/refresh, cached versus forced refresh, asynchronous action status, and model-specific behavior.[^kh-upstream] It must be wrapped behind isolated adapters and fixture/live qualification rather than treated as one stable “Kia/Hyundai API.”

**Analogical IQS:** **Not applicable as an integration; scaffold-only, below Bronze.** Contract scaffolding cannot satisfy integration quality rules without a real upstream, truthful availability, authentication, update semantics, error handling, diagnostics, and tests.

## Cross-package safety and privacy invariants

These are release gates, not future polish:

1. **Owner consent and least privilege:** use vendor consent/OAuth where available; request read scopes before command scopes and location separately. Never ask users to surrender account passwords to PiPhi when an official delegated flow exists.
2. **Secret non-observability:** access/refresh tokens, passwords, PINs, API keys, cookies, authorization codes, and private keys must never appear in discovery, state, telemetry, entities, events, logs, diagnostics, exception strings, or idempotency records. Enforce with recursive redaction tests.
3. **Trusted destinations only:** bearer credentials may be sent only to an adapter-owned allowlist. Test/proxy URL overrides must be build- or environment-gated, never user-editable production config.
4. **Stable, private identity:** bind the config to vendor account subject plus immutable vendor vehicle ID; use an opaque internal device ID. VIN may be shown only where necessary and must be masked/redacted elsewhere. Detect account mismatch during reauth.
5. **Location is explicit opt-in:** default off; obtain separate consent and scope; minimize requested fields; honor vehicle/account privacy settings; never infer permission from prior cached data; document storage, retention, export, and deletion.
6. **Sleep and battery protection:** cached reads first; no implicit wake; per-vehicle wake/force-refresh cooldown and daily budget; never schedule wake to satisfy a freshness target. Explain cost and 12 V/traction-battery effects before enablement.
7. **Freshness is first-class:** every value carries source timestamp/age and quality. Keep last-known values while separately reporting online/asleep/offline/unavailable/auth-failed/rate-limited. “Configured” is not “connected”; receipt time is not vehicle observation time.
8. **Commands are deny-by-default:** expose only adapter- and vehicle-negotiated capabilities. Require explicit vehicle target, fresh safety preconditions, risk-appropriate confirmation, durable idempotency, serialization, bounded timeout, asynchronous status reconciliation, and no blind retry of physical mutations.
9. **Typed failure policy:** distinguish invalid credentials, refreshable expiry, consent/scope denial, wrong region, subscription/entitlement, vehicle asleep/offline, stale data, rate limit, billing suspension, command precondition, and vendor outage. Retry only proven transient/idempotent cases and obey server backoff.
10. **Account-level budgets and concurrency:** coordinate all configs sharing an account; record requests/wakes/commands and remaining/reset metadata; provide user-set limits below vendor limits; prevent simultaneous poll/command storms.
11. **Redacted supportability:** diagnostics contain adapter/region/version, capability negotiation, timestamps/age, categorized errors, and budget counters—but no precise location, routes, VIN, account IDs, tokens, or raw vendor payloads.
12. **Evidence before release:** mocked contract tests, sanitized fixtures across brands/regions/powertrains, failure-injection tests, container CI, and a documented real-account/real-vehicle qualification matrix are mandatory. Live tests must be opt-in, rate-capped, read-only by default, and never expose credentials in CI.

## Prioritized work

### P0 — block publication and real-account use

**Tesla**

- Remove bearer/token/config echo from discovery, state, events, and diagnostics; mask VIN; add recursive redaction regression tests.
- Remove user-editable `base_url` or enforce an exact Tesla regional allowlist; add a separately gated test transport.
- Replace pasted access tokens with Tesla authorization-code OAuth, rotating refresh-token persistence, scope inspection, account-subject uniqueness, expiry recovery, `LoginRequired` reauth, revocation guidance, and account-mismatch protection.
- Introduce an account coordinator and request ledger: serialize account/vehicle work; obey 429 reset/retry headers; classify 401/403/408/421/429/billing errors; never mark all failures retryable.
- Disable wake in release builds until per-vehicle cooldown/budget, explicit confirmation, 10–60 s readiness polling, and no-blind-retry behavior are tested.
- Default location off and request location-specific data only when opted in; stop sending exact location/speed/heading through general telemetry without a documented retention policy.

**Kia/Hyundai**

- Remove/disable marketplace installation and synthetic “connected” behavior, or relabel the package unambiguously as a nonfunctional developer scaffold.
- Mark every credential field secret and prevent generic config storage/output before adding any adapter.
- Make an explicit product/legal decision on unofficial owner-service access. Do not imply vendor support or API stability; do not ship Hyundai US automation contrary to the owning service guidance.

### P1 — minimum credible private pilot

**Tesla**

- Model one account with dynamic vehicle children, pagination, removal/tombstones, shared-driver privacy, region discovery/recovery, and opaque IDs.
- Prefer Fleet Telemetry for ongoing data or cached data where acceptable; otherwise implement a documented awake-only interval and cost estimate comparable to HA's 10-minute policy.
- Preserve last-known values and upstream timestamps; expose freshness/quality/reachability separately; test asleep, offline, poor connectivity, cached 404/412, scope denial, and billing suspension.
- Add redacted diagnostics and tests for every sensitive key/location nesting; align runtime/package/manifest versions.

**Kia/Hyundai, only if approved**

- Build one narrowly scoped brand+region adapter first, behind a stable internal interface. Implement the actual account lifecycle (including OTP/PIN where required), token persistence/refresh, entitlement detection, vehicle identity, cached reads, forced-refresh budget, and async command status.
- Pin the unofficial owning library by version and commit, monitor its security/breakage, and disclose that it reverse-engineers non-public services. Keep each region disabled until fixtures and a real account/vehicle validate it.
- Start read-only with location off. Do not expose lock/unlock, climate/start, charging, horn/lights, or location until model-specific preconditions and privacy controls pass separate review.

### P2 — production hardening and breadth

- Add sanitized fixture matrices (Tesla generations/shared access; Kia/Hyundai/Genesis regions and ICE/HEV/PHEV/EV), contract/property tests, chaos tests, and long-running budget/sleep tests.
- Build OCI images in CI, scan dependencies/images, verify manifests against artifacts, sign releases, generate SBOM/provenance, and reconcile GHCR versus stale Docker Hub metadata.
- Publish support runbooks for consent changes, wrong region, subscription expiry, rate/billing suspension, vehicle inactivity, vendor outage, removal, token revocation, and privacy deletion.
- Add opt-in field telemetry for request counts, latency, categorized failures, and stale age—never raw vehicle data—and require a documented pilot sign-off before changing rollout from 0%.

## Verification performed

- Both package validators were run at the audited revision and passed (`Tesla runtime contract files are valid`; `PiPhi scaffold validation passed`).
- Package tests could not be executed reliably in the supplied harness: the active PDM environment first failed on missing `piphi_runtime_testkit_python`; with plugin autoload disabled, collection failed on an inconsistent OpenTelemetry installation (`opentelemetry._logs.severity`). This is an environment failure, not evidence that tests pass or fail.
- No real Tesla/Kia/Hyundai account credentials, vehicles, live-test configuration, sanitized captures, qualification report, or field-test attestation were found. The only vehicle payloads observed are mocks/fixtures.

## Sources

[^tesla-client]: PiPhi Tesla client and normalization, immutable revision: [`tesla.py`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-tesla-ev/src/piphi_network_tesla_ev/tesla.py).
[^tesla-app]: PiPhi Tesla runtime, immutable revision: [`app.py`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-tesla-ev/src/piphi_network_tesla_ev/app.py).
[^tesla-manifest]: PiPhi Tesla manifest, immutable revision: [`src/manifest.json`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-tesla-ev/src/manifest.json).
[^tesla-readme]: PiPhi Tesla stated scope, immutable revision: [`README.md`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-tesla-ev/README.md).
[^tesla-behaviors]: PiPhi Tesla behavior retry/freshness/safety metadata, immutable revision: [`src/behaviors.json`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-tesla-ev/src/behaviors.json).
[^tesla-tests]: PiPhi Tesla mocked tests, immutable revision: [`tests_python/test_tesla.py`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-tesla-ev/tests_python/test_tesla.py).
[^tesla-package]: PiPhi Tesla package version/dependencies, immutable revision: [`pyproject.toml`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-tesla-ev/pyproject.toml).
[^tesla-appmeta]: PiPhi Tesla portfolio CI/release metadata, immutable revision: [`piphi-app.json`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-tesla-ev/piphi-app.json).
[^tesla-endpoints]: Tesla, [Vehicle Endpoints](https://developer.tesla.com/docs/fleet-api/endpoints/vehicle-endpoints) (live owning documentation, accessed by cutoff).
[^tesla-billing]: Tesla, [Billing and Limits](https://developer.tesla.com/docs/fleet-api/billing-and-limits) (live owning documentation, accessed by cutoff).
[^tesla-oauth]: Tesla, [Third-Party Tokens](https://developer.tesla.com/docs/fleet-api/authentication/third-party-tokens) (live owning documentation, accessed by cutoff).
[^ha-docs]: Home Assistant Tesla Fleet documentation at immutable revision [`b86ad88`](https://github.com/home-assistant/home-assistant.io/blob/b86ad8850f807f39580b5a6636967d96178f1214/source/_integrations/tesla_fleet.markdown).
[^ha-flow]: Home Assistant Tesla Fleet OAuth/config flow at immutable revision [`7682317`](https://github.com/home-assistant/core/blob/76823177f8d296dbbf017fe59627757b695e71d5/homeassistant/components/tesla_fleet/config_flow.py).
[^ha-coordinator]: Home Assistant Tesla Fleet polling, sleep, token, and rate-limit handling at immutable revision [`7682317`](https://github.com/home-assistant/core/blob/76823177f8d296dbbf017fe59627757b695e71d5/homeassistant/components/tesla_fleet/coordinator.py).
[^ha-diagnostics]: Home Assistant Tesla Fleet diagnostics redaction at immutable revision [`7682317`](https://github.com/home-assistant/core/blob/76823177f8d296dbbf017fe59627757b695e71d5/homeassistant/components/tesla_fleet/diagnostics.py).
[^ha-iqs]: Home Assistant Tesla Fleet quality-scale declaration at immutable revision [`7682317`](https://github.com/home-assistant/core/blob/76823177f8d296dbbf017fe59627757b695e71d5/homeassistant/components/tesla_fleet/quality_scale.yaml).
[^ha-manifest]: Home Assistant Tesla Fleet manifest/library pin at immutable revision [`7682317`](https://github.com/home-assistant/core/blob/76823177f8d296dbbf017fe59627757b695e71d5/homeassistant/components/tesla_fleet/manifest.json).
[^ha-flow-test]: Home Assistant Tesla Fleet config-flow tests at immutable revision [`7682317`](https://github.com/home-assistant/core/blob/76823177f8d296dbbf017fe59627757b695e71d5/tests/components/tesla_fleet/test_config_flow.py).
[^ha-diagnostics-test]: Home Assistant Tesla Fleet diagnostics tests/snapshot at immutable revision [`7682317`](https://github.com/home-assistant/core/blob/76823177f8d296dbbf017fe59627757b695e71d5/tests/components/tesla_fleet/test_diagnostics.py).
[^kh-schema]: PiPhi Kia/Hyundai generic schema, immutable revision: [`schemas.py`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-kia-hyundai-connect/src/piphi_network_kia_hyundai_connect/schemas.py).
[^kh-contract]: PiPhi Kia/Hyundai generic UI/contract, immutable revision: [`contract.py`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-kia-hyundai-connect/src/piphi_network_kia_hyundai_connect/contract.py).
[^kh-state]: PiPhi Kia/Hyundai synthetic state/command handling, immutable revision: [`state.py`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-kia-hyundai-connect/src/piphi_network_kia_hyundai_connect/state.py).
[^kh-discovery]: PiPhi Kia/Hyundai demo discovery, immutable revision: [`routes/discovery.py`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-kia-hyundai-connect/src/piphi_network_kia_hyundai_connect/routes/discovery.py).
[^kh-commands]: PiPhi Kia/Hyundai command route, immutable revision: [`routes/commands.py`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-kia-hyundai-connect/src/piphi_network_kia_hyundai_connect/routes/commands.py).
[^kh-config]: PiPhi Kia/Hyundai config sync, immutable revision: [`routes/config.py`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-kia-hyundai-connect/src/piphi_network_kia_hyundai_connect/routes/config.py).
[^kh-health]: PiPhi Kia/Hyundai diagnostics, immutable revision: [`routes/health.py`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-kia-hyundai-connect/src/piphi_network_kia_hyundai_connect/routes/health.py).
[^kh-manifest]: PiPhi Kia/Hyundai manifest and draft qualification, immutable revision: [`manifest.json`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-kia-hyundai-connect/manifest.json).
[^kh-catalog]: PiPhi Kia/Hyundai planned/excluded capability catalog, immutable revision: [`capability-catalog.json`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-kia-hyundai-connect/capability-catalog.json).
[^kh-privacy]: PiPhi Kia/Hyundai privacy intent, immutable revision: [`docs/privacy.md`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-kia-hyundai-connect/docs/privacy.md).
[^kh-tests]: PiPhi Kia/Hyundai scaffold tests, immutable revision: [`tests`](https://github.com/PiPhi-io/piphi-apps/tree/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-kia-hyundai-connect/tests).
[^kh-release]: PiPhi Kia/Hyundai stale release instructions, immutable revision: [`docs/release.md`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-kia-hyundai-connect/docs/release.md).
[^kh-app]: PiPhi Kia/Hyundai portfolio CI/release metadata, immutable revision: [`piphi-app.json`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-kia-hyundai-connect/piphi-app.json).
[^hyundai-drain]: Hyundai Motor America, [Avoid Battery Drain from Unauthorized Third-Party Apps](https://owners.hyundaiusa.com/us/en/resources/blue-link/avoid-battery-drainage-using-myhyundai-with-bluelink) (owning documentation, accessed by cutoff).
[^hyundai-location]: Hyundai Motor America, [Manage Remote Location Access](https://owners.hyundaiusa.com/us/en/resources/general-information/how-to-manage-location-based-features) (owning documentation, accessed by cutoff).
[^kia-help]: Kia America, [Kia Connect troubleshooting](https://owners.kia.com/us/en/uvo-troubleshooting.html) (owning documentation, accessed by cutoff).
[^kia-ev6]: Kia America, [2026 EV6 Vehicle Feature Tips](https://owners.kia.com/content/dam/kia/us/owners/pdf/2026/2026-Kia-EV6-Vehicle-Feature-Tips.pdf) (owning model documentation, accessed by cutoff).
[^kh-upstream]: Hyundai-Kia-Connect community project (unofficial), immutable revision: [`README.rst`](https://github.com/Hyundai-Kia-Connect/hyundai_kia_connect_api/blob/12c6bf670876f8d2ab0b62801ee2edd71679d21b/README.rst) and [`ApiImpl.py`](https://github.com/Hyundai-Kia-Connect/hyundai_kia_connect_api/blob/12c6bf670876f8d2ab0b62801ee2edd71679d21b/hyundai_kia_connect_api/ApiImpl.py).
