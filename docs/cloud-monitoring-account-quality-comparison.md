# Cloud monitoring and market-data integration quality comparison

**Research cutoff:** 2026-11-16

**Repository revision audited:** [`e3eb2d3`](https://github.com/PiPhi-io/piphi-apps/tree/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e)
**Comparison baseline:** Home Assistant Core 2026.11.0 at [`74cf5a4`](https://github.com/home-assistant/core/tree/74cf5a49c63ed8d4d87717844bf14f79c28c9cea), first-party provider documentation, and the provider-facing libraries owned by the corresponding Home Assistant integrations.

## Executive finding

These seven packages are not one product class and should not share one release bar.

* **Account-authenticated monitoring:** Airthings, Sense, SolarEdge, Kaiterra, and WeatherXM read data tied to a person, account, site, or owned device. They must prove credential lifecycle, tenant/device selection, reauthentication, outage behavior, identity stability, privacy, and real-account interoperability.
* **Public tariff/market data:** Octopus Energy in this repository reads only caller-selected public tariff prices; Nord Pool reads published bidding-area prices. Neither package needs or should accept a household account credential. They require contract/licensing clarity, interval correctness, publication timing, and outage/cache behavior instead.
* **Official APIs:** Airthings Consumer API, SolarEdge Monitoring API V1, Kaiterra API, and Octopus REST tariff endpoints are provider-documented APIs. **Sense is explicitly unofficial.** WeatherXM's `/api/v1/me/devices` mobile-account surface is vendor-hosted but not the documented WeatherXM Pro API and must be treated as **unofficial/unsupported** until WeatherXM says otherwise. Nord Pool's `dataportal-api` is a provider-hosted public-portal backend, but not the authenticated, documented Market Data API product; it is therefore **public first-party data over an unofficial endpoint**, with non-trivial redistribution/licensing risk.

There are real network clients in all seven packages, but maturity differs sharply:

* **Substantive implementations:** Airthings, Sense, SolarEdge, Octopus Energy, Nord Pool.
* **Executable scaffold-derived adapters:** Kaiterra API and WeatherXM. Their HTTP calls are real, but they retain generic scaffold routes/state, lack an owned continuous polling and recovery lifecycle, and have shallow provider-specific tests.

No package contains a credential-gated real-account test, recorded provider contract test, canary result, or other reproducible evidence that the current release has communicated with a real account. Mocked tests are valuable but are not real-account evidence.

## Scoring method

Each slice is scored **0–5**: 0 absent, 1 scaffold/unsafe, 2 partial, 3 usable with material gaps, 4 release-grade, 5 mature and evidenced. The total is a simple average, not a claim of Home Assistant certification.

| Slice | What is evaluated |
|---|---|
| API and auth | API legitimacy, credential minimization, token/key lifecycle, auth failure classification |
| Identity and tenancy | Stable tenant/account/site/device identity; duplicate and multi-tenant behavior |
| Polling and resilience | Cadence, quotas, retry/backoff, outage and recovery semantics, shared sessions |
| Data semantics | Freshness, timestamps/time zones, units, interval/counter/statistics semantics, pagination/backfill |
| Privacy and diagnostics | Secret handling, household/location inference, diagnostic authorization and redaction |
| Verification and delivery | Provider-shaped tests, real-account evidence, CI, dependencies, release provenance |

## Package scorecard

| Package | Class / API standing | Implementation verdict | API & auth | Identity | Polling & resilience | Data semantics | Privacy & diagnostics | Verification & delivery | Overall | Release posture |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `piphi-network-airthings` | Account monitoring; **official Consumer API** | Real, broad adapter | 3.5 | 2.5 | 3.0 | 2.5 | 2.5 | 2.5 | **2.8** | Hold for P0 account selection, pagination/rate-limit, and secret-lifecycle fixes |
| `piphi-network-sense` | Account monitoring; **unofficial API/library** | Real adapter over `sense-energy` | 2.5 | 3.0 | 2.5 | 2.5 | 1.5 | 2.5 | **2.4** | Experimental only; disclose unsupported API and minimize occupancy telemetry |
| `piphi-network-solaredge` | Account/site monitoring; **official V1 API** | Real, quota-conscious adapter | 3.0 | 3.5 | 3.0 | 2.5 | 2.5 | 3.0 | **2.9** | Best account package, but no historical statistics/backfill and V1 transition unowned |
| `piphi-network-kaiterra-api` | Device monitoring; **official API** | Executable scaffold-derived adapter | 1.5 | 2.5 | 1.0 | 2.0 | 1.0 | 1.5 | **1.6** | Not production-ready |
| `piphi-network-weatherxm` | Account/station monitoring; **unofficial mobile-account API** | Executable scaffold-derived adapter | 1.0 | 1.5 | 1.0 | 1.5 | 0.5 | 1.5 | **1.2** | Do not release as an official-quality integration |
| `piphi-network-octopus-energy` | **Public tariff data**; official unauthenticated REST endpoint | Real, deliberately narrow client | 4.0 | 2.5 | 2.5 | 3.5 | 4.0 | 2.5 | **3.2** | Releaseable as “public tariff prices,” never as account energy monitoring |
| `piphi-network-nord-pool` | **Public market data**; first-party but unofficial portal endpoint | Real, interval-aware client | 2.0 | 3.0 | 3.0 | 4.0 | 4.0 | 2.5 | **3.1** | Technical beta only until data terms/endpoint support are resolved |

The low absolute scores are intentional. Home Assistant's mature integrations add reauth/reconfigure flows, owner accountability, diagnostics redaction, >95% coverage, and provider-specific lifecycle tests. A passing generic contract suite is not equivalent.

## Honest package slices

### Airthings

**What is real.** The package implements the official client-credentials flow, in-memory access-token caching with an expiry margin, account lookup, device discovery, serial-number identity, latest-sample timestamps, deduplicated telemetry delivery, a long-lived poll task, 429/5xx retry, and authenticated diagnostics. The provider documents the same Consumer API origins, client-credentials setup, account/device/sensor resources, and a 50-record sensor page ([Consumer API getting started](https://consumer-api-doc.airthings.com/), [OpenAPI](https://consumer-api.airthings.com/openapi.yaml)). The implementation is visible in the immutable [client](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-airthings/src/piphi_network_airthings/cloud/client.py) and [runtime](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-airthings/src/piphi_network_airthings/runtime.py).

**What is not yet honest enough for release.** `_account_id` silently selects the first account, although the API explicitly allows account membership and says only consumer account IDs may be assumed stable. Sensor parsing ignores `hasNext`/`totalPages`; filtering by one serial usually masks this, but multi-device batching is not supported. The retry parser reads standard `Retry-After`, while current Consumer API documentation specifies `X-RateLimit-Retry-After` and warns that rejected retries also consume quota ([rate-limit contract](https://consumer-api-doc.airthings.com/docs/api/rate-limit)). Device listing has no pagination guard. Token failures clear cache but there is no explicit reauth state or user repair path. The UI allows 60-second polling even though the package itself says samples are typically five-minute data, while Home Assistant uses six minutes ([HA coordinator](https://github.com/home-assistant/core/blob/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/airthings/coordinator.py)).

**Privacy and semantics.** Serial, account ID, device name/home metadata, radon/CO2/VOC/PM, and occupancy-correlated environmental history are sensitive household data. The client logs account IDs, client IDs, and serials. Diagnostics avoid credentials but include config IDs, complete state snapshots, and error/poll metadata. `client_secret` is a plain `str`, copied into registry entries and `config.model_dump()`, and discovery records carry it forward. The code reports vendor sample time for measurements, which is good, but derived mold risk is a local heuristic with partial-window weighting and must not be represented as an Airthings-provided measurement.

**HA comparison.** HA 2026.11.0 is also cloud polling, pins owning library `airthings-cloud==0.3.1`, and polls every six minutes ([manifest](https://github.com/home-assistant/core/blob/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/airthings/manifest.json), [coordinator](https://github.com/home-assistant/core/blob/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/airthings/coordinator.py)). PiPhi has stronger explicit delivery tracking, but weaker library ownership, account selection, repair UX, secret typing, and provider-contract alignment.

### Sense

**What is real.** The package deliberately labels `sense-energy` unofficial, reuses one authenticated session, handles MFA during initial configuration, separates 60-second realtime polling from 15-minute trend polling, uses monitor/device IDs, exposes timezone, and has service/client tests. `sense-energy` itself calls the API unofficial and advises a single reusable instance, authentication no more than every 15–20 minutes, and default realtime rate limiting to 30 seconds ([owning-library README](https://github.com/scottbonline/sense/blob/stable/README.md)). PiPhi pins `>=0.14.3,<0.15.0`; HA 2026.11.0 pins `0.15.0` ([HA manifest](https://github.com/home-assistant/core/blob/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/sense/manifest.json)).

**Gaps.** Password/MFA login is repeated after restart or reconfigure; persisted access/refresh token rotation is not implemented. Authentication exceptions during background polling become a generic disconnected state rather than a durable reauth request. There is no bounded exponential backoff, 429 handling, or “log once unavailable / once recovered” behavior. Best-effort calls to private endpoints swallow every exception and indefinitely retain the previous values without a stale marker. Timeline fetching has a fixed item count, no cursor/backfill, and no gap detection.

**Privacy and semantics.** Whole-home power, per-appliance power/on state, first-use metadata, and timeline text can reveal occupancy, sleep, cooking, EV charging, and named appliances. The integration publishes device telemetry and stores timeline events in state by default. Diagnostics expose active config IDs; runtime state can expose the richer household snapshot elsewhere. This data needs an explicit opt-in and retention policy. “Daily” energy is tied to Sense's monitor timezone, but PiPhi does not attach period start/end or reset semantics, so it is not a safe monotonic total for long-term statistics. The library documents that hourly grid import/export may be approximated; PiPhi currently exposes daily values but does not document provenance.

**HA comparison.** HA 2026.11.0 stores access/refresh token, user/device/monitor IDs, raises `ConfigEntryAuthFailed`, distinguishes setup retry from auth failure, and supports reauth/MFA in its UI flow (immutable [`__init__.py`](https://github.com/home-assistant/core/blob/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/sense/__init__.py), [`config_flow.py`](https://github.com/home-assistant/core/blob/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/sense/config_flow.py)). PiPhi's extra timeline/private endpoints increase feature surface and privacy risk without equivalent lifecycle maturity.

### SolarEdge

**What is real.** The adapter uses an owning async library for the documented Monitoring API V1, validates API key + site ID with site details, differentiates auth, quota, caller, and transient failures, maintains one session/site, enforces a minimum ten-minute live poll and hourly summary poll, normalizes power units, preserves signed grid/storage direction, and deduplicates unchanged summary telemetry ([client](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-solaredge/src/solar_edge/solaredge_client.py), [service](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-solaredge/src/solar_edge/service.py)). SolarEdge's current developer site documents OAuth-based V2 live and historical site/device endpoints ([provider portal](https://developer.solaredge.com/)); V1 remains the path used here and by HA 2026.11.0.

**Gaps.** There is no automatic backoff or `Retry-After` handling after quota exhaustion, no persistent shared quota budget, no reauth/reconfigure UX, and no V2 migration owner. `vendor_last_update` is surfaced in state, but live telemetry is timestamped with PiPhi poll time rather than source measurement time. Day/month/year/lifetime energy are snapshots, not imported period statistics; resets/corrections, site timezone, currency code, and history backfill are absent. One runtime supports one site even though an API key can authorize multiple sites.

**Privacy.** Site ID/name, production/consumption, grid exchange, battery behavior, and revenue reveal property operation and occupancy patterns. API key uses `SecretStr`, but the active service keeps a `(site_id, plaintext key)` comparison tuple in memory. Diagnostics expose poll errors and active config IDs but not the key. Error text should still be scrubbed before diagnostics because upstream exceptions can include URLs/query parameters.

**HA comparison.** HA pins `aiosolaredge==1.0.2` and `solaredge-web==0.5.0`, operates multiple provider services at quota-aware cadences, and imports corrected module energy into external recorder statistics while preserving sums ([manifest](https://github.com/home-assistant/core/blob/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/solaredge/manifest.json), [coordinator](https://github.com/home-assistant/core/blob/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/solaredge/coordinator.py)). The web-account path is itself unofficial; PiPhi correctly avoids it, but also lacks HA's inventory, historical statistics, correction handling, and test depth.

### Kaiterra API

**What is real.** The package calls provider-hosted `/v1/devices/{udid}/top` and metadata endpoints with API key + UDID, maps a broad set of air-quality/motion/light values, uses source point timestamps, and tests normalization with HTTP fixtures ([client](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-kaiterra-api/src/piphi_network_kaiterra_api/kaiterra.py)). HA also treats Kaiterra as cloud polling and pins the owning `kaiterra-async-client==1.1.0`, but classifies the integration as legacy ([HA manifest](https://github.com/home-assistant/core/blob/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/kaiterra/manifest.json)).

**Why this remains scaffold-derived.** `poll_interval_seconds` is accepted but no package poll loop consumes it. Every refresh creates two new HTTP sessions/requests; there is no retry, rate-limit handling, auth classification, stale state, outage recovery, or source freshness threshold. API key is a plain optional string, placed in `config.model_dump()` inside the registry. The key is sent as a query parameter as required by the API shape, increasing URL/log leakage risk. `latest_raw` and complete metadata remain in registry memory. Generic diagnostics do not redact or summarize provider fields. There are no pagination/backfill concepts and no real-device evidence.

**Semantics.** Motion is high-risk occupancy data. Units are passed through without canonical conversion; `ug/m3`, `C`, and a motion unit of `x` are not strong telemetry contracts. Selecting the last point assumes provider ordering; points should be selected by parsed timestamp and malformed/future/stale samples rejected.

### WeatherXM

**What is real.** The client can call `api.weatherxm.com/api/v1`, log in with username/password or use a bearer token, list account devices, read one station, and normalize current weather plus QoD ([client](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-weatherxm/src/piphi_network_weatherxm/weatherxm.py)). WeatherXM documents a distinct WeatherXM Pro API requiring a Pro API key and offering real-time/history/forecast data ([WeatherXM Pro](https://docs.weatherxm.com/weatherxm-pro)); it also publishes an official Pro MCP client that requires that key ([owner repository](https://github.com/WeatherXM/weatherxm-pro-mcp)). No first-party HA WeatherXM integration exists at the cutoff.

**Why this remains scaffold-derived and unofficial.** The account endpoints used here are not the documented Pro contract. Username, password, and token are plain strings; login token is cached only in one short-lived client object, while each refresh creates a new client and therefore can log in again. There is no refresh-token/expiry lifecycle, auth error classification, retry/backoff, rate-limit handling, owned poll loop, or pagination. If no station is selected, the first device is silently chosen. Configuration identity is initially derived from a user input/fallback, then a resolved station ID mutates only the entry/state and not necessarily the runtime device identity. `poll_interval_seconds` is unused.

**Privacy and semantics.** Station address/name, exact location, relationship/ownership, timezone, and local observations are location data. `latest_raw` retains the full provider device object. Diagnostics expose config IDs and recent-event counts but have no explicit provider-data redaction policy. Accumulated precipitation has no stated reset window. Timestamps are copied as strings without timezone validation or stale/future checks. The integration must either adopt the official Pro API or be clearly named “WeatherXM account (unofficial)” with compatibility and privacy warnings.

### Octopus Energy

**Scope distinction.** This package does **not** monitor an Octopus account, meter, consumption, billing, or household energy. It reads the official, unauthenticated product/tariff `standard-unit-rates` endpoint using product and tariff codes. Octopus documents product/rate endpoints as public, while consumption endpoints require authentication and meter identifiers ([REST endpoints](https://developer.octopus.energy/rest/guides/endpoints), [API basics](https://developer.octopus.energy/rest/guides/api-basics)). The unused generic `api_key` field is excluded and should be removed to prevent a false account-monitoring promise.

**Strengths.** The package fixes the HTTPS origin, validates interpolated codes, bounds the query to one hour behind and 25 hours ahead, requests UTC-aware windows, handles negative prices, chooses active/next intervals independent of result order, filters direct-debit variants deterministically, and never handles customer identifiers ([tariff client](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-octopus-energy/src/piphi_network_octopus_energy/tariffs.py)).

**Gaps.** The response's `next` pagination link is ignored; `page_size=100` covers the current narrow window but the invariant is implicit. `current_valid_to` is parsed then discarded from state/telemetry, so consumers cannot distinguish a stale rate after an outage. Poll failures replace state with disconnected rather than retaining last good rate plus `stale=true`, source interval, and fetch error. There is no `Retry-After`/5xx backoff. Only electricity standard single-register prices are represented: no standing charge, day/night registers, gas, export direction, account agreement, region discovery, or consumption. This narrowness is acceptable only if naming/docs remain exact.

**HA comparison.** There is no matching first-party HA Octopus Energy account integration at this cutoff. The correct analogues are public-price integrations and HA's energy-price entities, not authenticated utility-account integrations.

### Nord Pool

**Scope distinction.** This is public bidding-area market data, not a personal electricity tariff, retailer contract, tax/network fee, or account. Market area can weakly reveal region, but no household identifier or credential is required.

**Strengths.** The package reads today and optional tomorrow, uses Europe/Oslo to determine the market day, validates response date/currency/size, preserves explicit source intervals, supports 15-minute MTUs, normalizes currency/MWh to currency/kWh, rejects overlaps, and refuses to invent a “next” price across a gap ([market client](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-nord-pool/src/piphi_network_nord_pool/market_client.py), [normalizer](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-nord-pool/src/piphi_network_nord_pool/pricing.py)). Nord Pool confirms the transition to 15-minute delivery intervals ([provider notice](https://developers.nordpoolgroup.com/reference/15-minute-mtu)).

**Critical governance gap.** `dataportal-api.nordpoolgroup.com/api/DayAheadPrices` is the unauthenticated backend of Nord Pool's first-party website, not the documented, authenticated Market Data API. The official 2026 offering charges for API data and applies redistribution terms ([day-ahead market data](https://www.nordpoolgroup.com/en/services/power-market-data-services/day-ahead-market-data), [2026 fee schedule](https://www.nordpoolgroup.com/4a7b5e/globalassets/trading-and-services/nord-pool-fee-schedule-2026-market-data---data-services.pdf)). Technical accessibility does not grant redistribution rights. Legal/product approval is a P0 gate.

**Runtime gaps.** On failure, the prior state is retained but `connected=false`; there is no explicit stale age or last successful source interval in the published state. Retry is a fixed 60 seconds without jitter or response-aware backoff. Tomorrow is queried every successful refresh even before publication. Market area syntax is validated but not constrained to supported areas. Full `chart_intervals` are computed but only current/next are published, so there is no backfill/history API. `data_updated_at` is discarded.

**HA comparison.** HA 2026.11.0 marks Nord Pool **Platinum**, pins the owning `pynordpool==0.4.0`, injects HA's web session, polls hourly, updates listeners on 15-minute boundaries, keeps yesterday/today/tomorrow, and tolerates tomorrow being unavailable ([manifest](https://github.com/home-assistant/core/blob/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/nordpool/manifest.json), [coordinator](https://github.com/home-assistant/core/blob/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/nordpool/coordinator.py)). That demonstrates engineering maturity, not provider endorsement or redistribution permission; `pynordpool` is community-owned, not Nord Pool-owned.

## Evidence matrix

| Area | Airthings | Sense | SolarEdge | Kaiterra | WeatherXM | Octopus | Nord Pool |
|---|---|---|---|---|---|---|---|
| Auth/key lifecycle | Client credentials; token expiry cache; no account chooser/repair | Password + one-shot MFA; no persisted token rotation | Long-lived V1 API key; no rotation/reauth | Static key in query string | Plain password/token; token lifetime unknown | None required; generic key is misleading | None required for portal backend |
| Tenant/site/device identity | First account silently selected; serial stable | One account; monitor + appliance IDs | One site/runtime; numeric site ID | UDID | First station fallback; identity can drift | Product+tariff should be identity, currently generic runtime ID | Area+currency should be identity |
| Polling/rates | Poll task; 429/5xx retry; wrong current retry header; no page loop | Reused session; fixed cadence; no backoff/429 | Reused session; bounded cadence; no quota backoff | No autonomous poller | No autonomous poller | Poller; no response-aware backoff | Poller; fixed one-minute failure retry |
| Freshness/time zone | Source UTC sample used; no stale threshold | Monitor timezone present; periods not modeled | Vendor update visible; delivery uses poll time | Raw source string; no parse/stale check | Raw string/timezone; no validation | UTC interval parsed but interval discarded from state | Strong UTC interval normalization; updated time discarded |
| Units/statistics | Mostly canonical; derived mold score provenance risk | Power/energy units; daily reset semantics unclear | W/kWh conversion; snapshots, no recorder-style statistics | Pass-through units; weak canonicalization | Fixed mappings; accumulated rain reset unclear | p/kWh incl. VAT; no interval metadata | Currency/kWh from currency/MWh; not a retail tariff |
| Pagination/backfill | Sensor pagination omitted; no history | Fixed timeline count; no cursor/history | No historical import | None | None | Pagination ignored; narrow bounded window | Today/tomorrow only; no historical import |
| Outage/reauth | Last state marked disconnected; no durable reauth | Generic disconnect; stale private values retained | Failure heartbeat; no reauth/quota repair | Exception escapes | Exception escapes | Last good state replaced | Last good values retained with connected false |
| Sensitive data | Air quality + serial/home | Appliance/occupancy/timeline | Energy/revenue/site | Air quality + motion | Location/address/weather | Public tariff selection only | Public area price only |
| Diagnostics/redaction | Authorized; state snapshots; no secrets shown | Generic IDs only | Poll errors/IDs; no key shown | Generic but key/raw live in registry | Generic but secrets/raw live in registry | Generic; no customer secret | Generic; public fields |
| Tests | Client/runtime mocks, release tooling | Client/service/private endpoint/widget mocks | Client/service/TestKit/release mocks | Normalizer/routes/contracts | Client/routes/contracts | Parser/state/contracts | DST/15-min/gap/client/runtime/widget |
| Real-account evidence | None found | None found | None found | None found | None found | Public endpoint not exercised live in tests | Public endpoint not exercised live in tests |

## Analogical Home Assistant IQS assessment

This is an **analogy**, not an HA score: PiPhi packages are not HA config-entry integrations, and HA's tiers are cumulative. The current IQS rules require UI setup and connection testing at Bronze; unloading, reauthentication and >95% module coverage at Silver; diagnostics, reconfiguration, repairs and rich docs at Gold; and async dependencies, injected sessions, and strict typing at Platinum ([HA IQS rules](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules)).

| Package | Analogical tier | Reason the next tier is not met |
|---|---|---|
| Airthings | **Bronze-like, not Silver** | Real setup/polling/tests, but no reauth/reconfigure, no coverage proof, no multi-account handling, and diagnostics/privacy gaps |
| Sense | **Bronze-like, not Silver** | Real lifecycle and MFA setup, but unofficial private endpoints, no token/reauth lifecycle, broad sensitive state, and no coverage proof |
| SolarEdge | **Bronze-like; several Silver traits** | Strong error taxonomy, owned poller, unloading and tests, but cumulative Silver is blocked by reauth, owner/coverage proof, recovery logging and configuration documentation |
| Kaiterra API | **Below Bronze** | Connection can be tested, but configured polling is not implemented and secrets/error lifecycle are scaffold-grade |
| WeatherXM | **Below Bronze** | Unsupported API contract, plain secrets, unstable first-device selection, and no polling/auth recovery lifecycle |
| Octopus Energy | **Bronze-like narrow service** | Safe public endpoint and parser tests, but no interval/stale UX, pagination assertion, coverage proof, owner/reconfigure/diagnostic depth |
| Nord Pool | **Bronze-like; several Gold/Platinum technical traits** | Good interval/outage tests and async client, but cumulative Silver is blocked by owner/coverage/recovery evidence; no injected session, terms gate, stale metadata, or provider-supported endpoint |

The HA comparison also prevents false inference from names: HA's Nord Pool package is Platinum, HA's Kaiterra package is Legacy, while HA's Airthings/Sense/SolarEdge manifests have no declared scale at the pinned revision. A mature analogue does not automatically transfer quality to a PiPhi implementation.

## Required data and privacy invariants

These should become executable contract tests shared by the portfolio.

1. **Credentials never become telemetry, state, events, diagnostics, exception text, URLs in logs, discovery output, or user-visible IDs.** Secrets use secret types and are stored only in the Core secret/config boundary. Query-string API keys are redacted before logging.
2. **Public-data integrations accept no account credential.** Octopus tariff and Nord Pool area-price configurations must reject/ignore no secret field; docs must state that they do not show the user's tariff agreement, consumption, bill, taxes, or network charges.
3. **Account scope is explicit.** Never silently select `accounts[0]`, `devices[0]`, or the first site. Persist provider tenant/account/site/device identifiers and validate that they still belong together on every reconfigure.
4. **Entity identity is immutable.** Display name, address, currency, and mutable labels cannot form identity. Airthings serial, Sense monitor/appliance ID, SolarEdge site/equipment ID, Kaiterra UDID, WeatherXM station ID, Octopus product+tariff+direction, and Nord Pool area+currency are the minimum provider keys.
5. **Source time and fetch time are separate.** Every observation/rate carries parsed timezone-aware `source_observed_at` or interval `[valid_from, valid_to)`, plus `fetched_at`. Naive, future, reversed, overlapping, and implausibly old timestamps are rejected or explicitly stale.
6. **Last good data is never relabeled fresh.** Cloud failure preserves values only with `available=false`/`stale=true`, last-success time, age, and redacted error class. Unofficial Sense fallback caches must carry per-slice freshness.
7. **Units and signs are canonical.** Raw units are validated against a provider mapping; conversions are explicit. Import/export and charge/discharge signs are tested. Market MWh→kWh conversion is exactly `/1000`; Octopus prices explicitly indicate pence and VAT inclusion.
8. **Statistics semantics are explicit.** Instantaneous power is measurement data; day/month energy is a resetting period aggregate; lifetime energy is a monotonic total unless reset/correction is detected. Do not feed period snapshots into long-term sums as if they were monotonic counters.
9. **Pagination is complete or bounded by proof.** Follow provider cursors/pages with hard page/record limits, or assert that a time/ID filter mathematically bounds the response. Store checkpoint + provider identity for any backfill and make replay idempotent.
10. **Rate limits are shared and durable enough for the provider contract.** Honor provider-specific reset/retry headers, cap and jitter retries, avoid retry storms after restart, and budget discovery/config validation together with runtime polls.
11. **Privacy defaults minimize inference.** Sense appliance/timeline and Kaiterra motion are opt-in; location/address and raw provider payloads never leave the adapter. Retention and purpose are documented for energy, occupancy, location, and indoor-air history.
12. **Diagnostics are authenticated, allowlisted, and tested with canary secrets/PII.** Return versions, redacted stable hashes, freshness, request/error counts, and provider status classes—not full state snapshots, raw payloads, names, serials, emails, addresses, account IDs, or timeline text.
13. **Outage and auth are distinct.** 401/403 enters reauth/repair without destructive recreation; 429 enters quota backoff; 5xx/network errors enter transient unavailable; malformed 2xx enters provider-contract failure. Recovery logs/events occur once.
14. **Deletion is complete.** Deconfigure cancels tasks, closes sessions, evicts tokens/raw caches and pending deliveries, removes local historical/private data according to policy, while preserving only intentionally retained aggregate statistics.

## Prioritized work

### P0 — release blockers

1. **Nord Pool terms and endpoint decision:** obtain written approval for use/redistribution of `dataportal-api`, or move to the official authenticated Market Data API with licensed credentials. Label data as wholesale area price, never retail tariff.
2. **WeatherXM contract decision:** migrate to documented WeatherXM Pro API and API-key lifecycle, or explicitly ship as unsupported/unofficial with owner approval. Remove username/password mobile-account login from a production release until its contract is documented.
3. **Secret boundary:** convert Airthings/Kaiterra/WeatherXM secrets to secret types; prevent registry/config/discovery/raw/error/log propagation; add canary redaction tests for every endpoint. Remove Octopus/Nord Pool generic API-key fields.
4. **Explicit selection and stable identity:** add Airthings account selection, WeatherXM station selection, SolarEdge site selection/multi-site policy, duplicate prevention, and immutable identity migration tests. Never pick the first result.
5. **Make advertised polling true:** implement provider-owned poll/session/error lifecycles for Kaiterra and WeatherXM or stop advertising them as cloud-polling integrations. Add shutdown, retry/backoff, stale, and recovery behavior.
6. **Real-service qualification:** add opt-in secret-gated canaries for all five account integrations and live public-feed smoke tests for Octopus/Nord Pool. Record date, endpoint contract/version, anonymized provider fixture hash, and pass/fail artifact; never require these in fork PR CI.

### P1 — production reliability and truthful data

1. Implement durable reauth/repair/reconfigure paths for Airthings, Sense, SolarEdge, Kaiterra, and WeatherXM; preserve entity identity while rotating credentials.
2. Add provider-specific quota budgets: Airthings `X-RateLimit-*`, SolarEdge V1/V2 quotas, bounded exponential backoff with jitter, and publication-aware Nord Pool tomorrow fetches.
3. Carry source interval/timestamp, fetch time, last success, stale age and source update time through state and telemetry. Retain last good values during outage with explicit staleness.
4. Implement/verify pagination: Airthings sensors, Sense timeline if retained, WeatherXM device lists, and Octopus response `next`; cap loops and test duplicate/out-of-order pages.
5. Define statistics contracts. Add SolarEdge historical import/checkpoints/correction handling if historical energy is a goal; otherwise call values snapshots. Model Sense daily reset timezone and Octopus/Nord Pool price validity intervals.
6. Replace raw-payload caches with typed allowlisted models. Make Sense timeline/appliance activity, Kaiterra motion, and all location/address fields opt-in and retention-bounded.
7. Add diagnostics schemas and snapshot tests proving redaction of secrets, tenant/device IDs, names, energy/occupancy/location values, raw URLs, and upstream exception bodies.

### P2 — quality and delivery maturity

1. Pin provider/owning libraries exactly where used; Airthings should prefer the owning library, Sense should align with the tested HA version or document the older pin, and direct clients need frozen provider contract fixtures.
2. Add branch CI paths for each package: lock integrity, lint/type check, unit + contract + TestKit tests, coverage threshold, container build, SBOM/provenance, vulnerability scan, and immutable-image verification. No package-specific workflow was found at the audited revision.
3. Publish a per-package support matrix: official/unofficial standing, endpoints, regions/devices, cadence, quotas, freshness, units, reset/statistics behavior, privacy class, known outages, and deprecation policy.
4. Add DST, leap day, negative price, duplicate/overlap/gap, stale/future timestamp, counter reset, reordered points/pages, 401/403/404/429/5xx, timeout, cancellation, restart, and partial-cloud-outage tests.
5. Add release evidence linking source commit → lockfile → test artifact → image digest → changelog. Existing release scripts and local version numbers are useful plumbing but not evidence of a published, exercised release.

## Validation performed and limits

* Inspected all production Python sources, manifests, package locks/dependencies, provider-specific tests, generic runtime routes, release scripts, and repository workflow references for the seven packages at the audited commit.
* Compared against immutable Home Assistant 2026.11.0 sources at commit `74cf5a49c63ed8d4d87717844bf14f79c28c9cea`; dynamic provider docs were read as of the stated cutoff.
* Offline syntax validation passed: `ast.parse` accepted all 193 Python files and `json.loads` accepted all 80 JSON files under the seven packages. These checks do not establish imports/dependency compatibility, API compatibility, quota behavior, data correctness, privacy compliance, or a successful release.
* Test execution was attempted with `pdm run pytest -q` for all seven packages. The environment lacked the required Python 3.12 interpreter/runtime TestKit installation and PDM reused its own Python 3.13 environment; collection stopped with `ModuleNotFoundError: piphi_runtime_testkit_python`. No test-pass claim is made.
* No credentials were available or used. No live provider call, cloud-outage simulation, rate-limit experiment, historical backfill, container build/push, image signature check, or real-account acceptance test was performed.
* Public documentation and source cannot prove private provider SLAs, account edge cases, commercial redistribution rights, or production operation. In particular, Nord Pool legal approval and WeatherXM endpoint support require owner/provider confirmation rather than technical inference.

## Primary-source index

* Airthings: [Consumer API docs](https://consumer-api-doc.airthings.com/), [OpenAPI](https://consumer-api.airthings.com/openapi.yaml), [rate limits](https://consumer-api-doc.airthings.com/docs/api/rate-limit).
* Sense: [`sense-energy` owning repository](https://github.com/scottbonline/sense), [HA 2026.11.0 Sense source](https://github.com/home-assistant/core/tree/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/sense).
* SolarEdge: [provider developer portal](https://developer.solaredge.com/), [HA 2026.11.0 SolarEdge source](https://github.com/home-assistant/core/tree/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/solaredge).
* Kaiterra: [HA 2026.11.0 integration and owning-library declaration](https://github.com/home-assistant/core/tree/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/kaiterra).
* WeatherXM: [provider docs](https://docs.weatherxm.com/weatherxm-pro), [provider-owned Pro MCP client](https://github.com/WeatherXM/weatherxm-pro-mcp).
* Octopus Energy: [REST endpoint guide](https://developer.octopus.energy/rest/guides/endpoints), [API/auth/pagination basics](https://developer.octopus.energy/rest/guides/api-basics).
* Nord Pool: [15-minute MTU notice](https://developers.nordpoolgroup.com/reference/15-minute-mtu), [official APIs](https://www.nordpoolgroup.com/en/trading/api), [day-ahead data product](https://www.nordpoolgroup.com/en/services/power-market-data-services/day-ahead-market-data), [2026 fee schedule](https://www.nordpoolgroup.com/4a7b5e/globalassets/trading-and-services/nord-pool-fee-schedule-2026-market-data---data-services.pdf), [HA 2026.11.0 Nord Pool source](https://github.com/home-assistant/core/tree/74cf5a49c63ed8d4d87717844bf14f79c28c9cea/homeassistant/components/nordpool).
* Quality baseline: [Home Assistant IQS rules](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules) and [checklist](https://developers.home-assistant.io/docs/core/integration-quality-scale/checklist).
