# Cloud and home-account integration quality comparison

**Audit cutoff:** 2026-11-16

**Repository revision:** [`e3eb2d3084645ab2cf4f80e925368b28f6fdb27e`](https://github.com/PiPhi-io/piphi-apps/tree/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e)

**Packages:** Aqara, Daikin Onecta, Dyson, Eufy Security, ThinQConnect, Tuya, and Xiaomi Home

## Executive result

The seven package names do not represent seven comparable integrations.

- **Aqara, ThinQConnect, and Tuya have executable vendor/device vertical slices.** Aqara and ThinQConnect are account-cloud integrations. Tuya is primarily a **local-LAN integration**; its optional Tuya cloud credentials assist discovery and local-key acquisition but do not make configured-device operation cloud-equivalent to Home Assistant's official Tuya integration.
- **Daikin Onecta, Dyson, Eufy Security, and Xiaomi Home are generated scaffolds.** Their catalogs are useful roadmaps and generally label vendor capabilities as planned or excluded, but there is no vendor client, account/device discovery, vendor state normalization, or vendor mutation path. Configuration currently creates an immediately `connected: true` synthetic state, while commands only emit `runtime.command.received`.
- **No package has production evidence sufficient for an unqualified production-ready claim.** The repository contains useful mock, fixture, simulator, and contract coverage, but this audit found no live-account CI, populated real-hardware certification matrix, soak results, or matching package release tags.

The strongest supported slices are Aqara's signed regional API plus bounded switch/dimmer/cover control, ThinQConnect's profile-driven appliance model plus polling/push fallback, and Tuya's broad TinyTuya LAN path. Their largest gaps are credential/privacy hardening, explicit reauthentication/reconfiguration behavior, mutation safety, and real-account/hardware evidence.

## Method and interpretation

This is a static portfolio audit, not a device certification. It reviewed package source, manifests, capability catalogs, tests, central CI/release workflows, and repository history at the revision above. Comparators are current first-party Home Assistant documentation plus official vendor or owning-library sources appropriate to each architecture. Where no matching first-party Home Assistant integration exists, this report says so rather than treating a similarly named integration as equivalent.

Ratings in the scorecard mean:

- **Strong** — implemented coherently in the reviewed slice with meaningful automated tests.
- **Partial** — implemented, but important lifecycle, safety, or evidence gaps remain.
- **Absent** — no vendor-facing implementation was found.
- **N/A** — the concern does not apply to that architecture.

“IQS analogue” is a directional application of the Home Assistant Integration Quality Scale (IQS), **not an awarded Home Assistant tier**. PiPhi sidecars do not use Home Assistant config entries, entity registries, repairs, or diagnostics APIs, so many IQS rules can only be mapped by intent.

## Concise scorecard

| Package | Honest architecture and supported slice | Auth, identity, lifecycle | State transport and failure behavior | Mutation safety | Test/evidence posture | IQS analogue |
|---|---|---|---|---|---|---|
| `piphi-network-aqara` | **Implemented cloud slice.** Regional Aqara Open API; dynamic resource normalization; switch, dimmer, and cover writes. Lock/camera data are read/event surfaces, not lock or camera-control claims. | **Partial.** Signed requests, token exchange/refresh, region and stable `did`; no complete user-facing reauth/reconfigure path. Secrets remain in runtime config/registry. | **Strong/partial.** 300 s default polling, HTTP push, dedupe/stale handling, and offline snapshots. Push setup is operationally manual. | **Partial.** Commands are bounded by class, but webhook bearer comparison and diagnostic-state privacy need hardening. | Good mock route/client coverage; no live account/hardware or soak evidence. | **Silver-direction candidate after P0 security/lifecycle fixes; not certifiable from current evidence.** |
| `piphi-network-daikin-onecta` | **Scaffold only.** No Onecta OAuth client, account/device discovery, telemetry, or controls. It must not be compared with HA's first-party **local** Daikin integration. | **Absent.** No OAuth authorization-code/refresh lifecycle, EMEA eligibility, account identity, or token persistence model. | **Absent.** Synthetic connected state; no cloud polling, push, quotas, stale, or offline semantics. | **Absent.** No vendor writes; command receipt is not control. | Scaffold/contract tests only; no account/device evidence. | **Below Bronze analogue.** Foundation exists, integration prerequisites do not. |
| `piphi-network-dyson` | **Scaffold only.** Cataloged product discovery, local MQTT, sensing, fan/heating/humidification remain planned. | **Absent.** No account bootstrap, product identity, local credential acquisition, or credential rotation. | **Absent.** Synthetic connected state; no MQTT session, state parsing, stale, or offline behavior. | **Absent.** No appliance writes. Heating/safety boundaries exist only as catalog intent. | Scaffold/contract tests only; no appliance evidence. | **Below Bronze analogue.** |
| `piphi-network-eufy-security` | **Scaffold only.** Security/camera/lock scope is a roadmap, not a sidecar/API implementation. | **Absent.** No account/2FA/captcha/region/session lifecycle or station/device identity path. | **Absent.** Synthetic connected state; no station events, streams, polling, stale, or offline behavior. | **Absent.** No arm/disarm, lock, alarm, or camera mutation path. | Scaffold/contract tests only; no station/device evidence. | **Below Bronze analogue.** |
| `piphi-network-thinqconnect` | **Implemented cloud slice.** Official `thinqconnect` SDK, device/profile/status discovery, profile-derived controls, and simulator. | **Partial.** PAT, country, and client identity are modeled; PATs do not refresh like OAuth tokens. Missing explicit expiry/revocation recovery and user-facing reauth. Initial refresh can fail open after config is retained. | **Strong/partial.** 60 s polling; opt-in MQTT push that degrades to polling; status/profile negotiation and offline/error state. | **Partial/strong.** Writes are bounded by the device profile, but need certified appliance fixtures and clearer high-impact action policy. | Broadest code/test surface of the cloud packages, but tests are mocked/simulated; no live account/appliance evidence. | **Silver-direction candidate after P0 lifecycle fixes; not certifiable from current evidence.** |
| `piphi-network-tuya` | **Implemented LAN slice.** TinyTuya discovery, persistent local sessions, DPS normalization, and LAN control. Optional cloud API is discovery/local-key assistance only. | **Partial.** Stable identity uses device ID plus host/local key/protocol; cloud region/credentials are optional. Local-key rotation and guided recovery are incomplete. | **Partial/strong.** Polling with jitter/backoff, persistent-session recovery, offline state, and secret redaction. No configured-device cloud-push parity with HA Tuya. | **Weak.** Generic `set_dp` is widely advertised; inferred cover/HVAC writes can target wrong DPs. No certified hardware rows constrain those risks. | Significant automated generic/family coverage, but certification table is `_TBD_`; no real-device/soak evidence. | **Bronze-direction only until dangerous writes are gated and hardware evidence exists.** |
| `piphi-network-xiaomi-home` | **Scaffold only.** No OAuth, MIoT spec discovery, device normalization, events, or actions. | **Absent.** No account/region/redirect/token-refresh or device identity lifecycle. | **Absent.** Synthetic connected state; no cloud events/polling/stale/offline behavior. | **Absent.** No vendor writes. | Scaffold/contract tests only; no account/device evidence. | **Below Bronze analogue.** |

## Package findings

### Aqara

**Supported now.** The runtime implements Aqara's app-key signing and regional hosts, exchanges and refreshes access tokens, discovers a device's dynamic resources, polls by default every 300 seconds, accepts Aqara HTTP Push, and publishes normalized state. Push messages are deduplicated and stale or offline messages are tracked. Commands are intentionally narrower than the observed data model: switches, dimmers, and covers are writable; lock and camera observations do not imply unlock or camera-control support.

**Quality gaps.** Access and refresh credentials are retained in runtime configuration/registry structures. Diagnostics expose `state_snapshots`, which requires an explicit recursive redaction contract as new vendor payloads are added. The push bearer token is compared with ordinary equality rather than a constant-time comparison. Token refresh exists internally, but invalid grants, revoked consent, region changes, and credential replacement do not form a complete reauth/reconfigure user journey. Push authenticity also needs a documented threat model beyond possession of the configured bearer token.

**Comparator.** Home Assistant's first-party Aqara integration documents cloud account authorization and supported Aqara device classes. Aqara's Open API documentation is the architecture-matching authority for authorization and regional cloud behavior; it is more relevant than treating any local Zigbee integration as cloud parity.

### Daikin Onecta

**Supported now.** Only the common PiPhi runtime shell: health/contract/config/state routes, synthetic connectivity, refresh receipt, and a capability roadmap.

**Missing vertical slice.** There is no Onecta OAuth flow, refresh-token handling, account/device enumeration, stable management-point identity, state mapper, rate-limit budget, stale/offline model, or bounded HVAC command path. This matters because the official Onecta developer portal is EMEA-scoped and documents a default limit of 200 API calls per day; a production poller must budget calls across devices and actions rather than inherit a generic interval.

**Comparator boundary.** Home Assistant's first-party `daikin` integration is local-network oriented and therefore is not evidence that this cloud scaffold has parity. The official Onecta API and the owning `daikin_onecta` library are the relevant cloud references.

### Dyson

**Supported now.** Only the common runtime shell. The README explicitly says appliance features remain planned until product-type discovery, local credential bootstrap, sanitized MQTT transport, model fixtures, and bounded command tests exist.

**Missing vertical slice.** No Dyson account or credential bootstrap, device/product discovery, local MQTT transport, environment/filter/fault normalization, offline behavior, or fan/oscillation/heating/humidification controls exist. Heating is safety-sensitive and should require model allowlists, range enforcement, post-write verification, and a default-deny policy.

**Comparator boundary.** Home Assistant removed its old Dyson integration and does not provide a current matching first-party cloud/security integration. The owning `libdyson-wg/ha-dyson` project is useful architecture evidence, but it must not be represented as first-party HA quality certification.

### Eufy Security

**Supported now.** Only the common runtime shell and a reviewed capability catalog.

**Missing vertical slice.** No account login, two-factor/captcha challenge handling, region/session lifecycle, station/device identity, event channel, camera stream, or command dispatch exists. Security mutations—arm/disarm, lock/unlock, alarm, and privacy-affecting camera controls—need stronger confirmation, authorization, auditing, and test requirements than ordinary appliance writes.

**Comparator boundary.** Home Assistant's `eufy`/EufyHome material concerns a different product/API surface and is not Eufy Security parity. There is no matching first-party Home Assistant Eufy Security integration to score against; any owning custom sidecar or library is architectural guidance only.

### ThinQConnect

**Supported now.** The package uses the official `thinqconnect` Python dependency and models PAT, country, and client identity. It discovers devices, retrieves profiles and status, derives writable controls from the profile, polls at 60 seconds by default, and optionally consumes MQTT push. Push failure degrades to polling. A simulator and profile/status fixtures support deterministic testing.

**Quality gaps.** A PAT has no OAuth-style refresh token, but expiry, revocation, permission changes, and replacement still require a first-class reauthentication state and actionable diagnostics. Configuration currently survives a failed initial refresh, which can preserve an unusable entry; the result should instead distinguish transient service failure from invalid credentials and unsupported devices. Push is opt-in, so quotas and poll behavior must remain safe by default. Account and appliance identifiers, profiles, and raw status also need an explicit privacy/redaction inventory.

**Comparator.** Home Assistant's first-party LG ThinQ integration and LG's ThinQ Connect SDK/API model support the profile-driven, account-cloud comparison. They do not substitute for live PiPhi account/appliance evidence.

### Tuya

**Supported now.** Configured operation uses TinyTuya over the LAN with `host`, Tuya device ID, local key, and protocol/device-class settings. The runtime maintains persistent sessions, polls with jitter and bounded failure backoff, marks failures/offline state, redacts known config secrets, normalizes common DPS families, and offers family-specific commands. Optional Tuya cloud API credentials call TinyTuya `Cloud` for discovery and local-key/config assistance.

**Critical boundary.** Home Assistant's official Tuya integration is a Tuya cloud integration with cloud-delivered updates. PiPhi's configured device path is LAN polling/control. Optional cloud discovery does **not** provide equivalent cloud runtime semantics, account lifecycle, push delivery, or away-from-home reachability.

**Quality gaps.** Raw `set_dp` is broadly advertised, bypassing family semantics and making arbitrary device mutation possible. Cover and climate mappings rely on category/name/common-DP heuristics, where an incorrect DP, direction, scale, or mode can create physical or equipment risk. Those writes should be gated behind explicit advanced opt-in or a model-certified mapping. `SUPPORTED_DEVICES.md` labels multiple families Tier 1 but every model-certification field remains `_TBD_`; therefore family-level automation is not hardware certification and “production-ready” wording must stay qualified.

### Xiaomi Home

**Supported now.** Only the common runtime shell and capability roadmap. The README accurately says model-specific capabilities remain planned until discovery, normalization, dispatch, and executable tests exist.

**Missing vertical slice.** No Xiaomi account/OAuth and region handling, token refresh, MIoT-spec/device discovery, stable identity, event subscription, polling fallback, capability translation, or bounded actions exist.

**Comparator boundary.** Home Assistant's older first-party `xiaomi_miio` integration covers local-token device families and is not cloud-account parity. Xiaomi's official `ha_xiaomi_home` project is the better source for current account, region, OAuth, and MIoT architecture, while still not conferring quality on this scaffold.

## Cross-cutting evidence

| Claim | Repository evidence at audited revision | Interpretation |
|---|---|---|
| Four packages share a generated shell | Representative [Daikin `state.py`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-daikin-onecta/src/piphi_network_daikin_onecta/state.py), [Dyson README](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-dyson/README.md), [Eufy capability catalog](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-eufy-security/capability-catalog.json), and [Xiaomi README](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-xiaomi-home/README.md). The four `state.py`, command-route, and config-route files are pairwise identical in the reviewed checkout. | Catalog completeness is not implementation completeness. Synthetic connection and command events must not be counted as vendor support. |
| Aqara has a real cloud client/runtime | [Cloud client](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-aqara/src/piphi_network_aqara/cloud/client.py) and [runtime](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-aqara/src/piphi_network_aqara/runtime.py). | Signed regional requests, refresh, resources, polling, push, state, and bounded mutations are executable rather than catalog-only. |
| ThinQConnect has a real SDK adapter | [`pyproject.toml`](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-thinqconnect/pyproject.toml), [SDK adapter](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-thinqconnect/src/piphi_network_thinqconnect/lib/client.py), [push adapter](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-thinqconnect/src/piphi_network_thinqconnect/lib/push.py), and [routes/runtime lifecycle](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-thinqconnect/src/piphi_network_thinqconnect/contract/config/routes.py). | Official SDK use and profile-derived controls reduce guesswork, but do not solve PAT recovery or prove appliance compatibility. |
| Tuya is LAN-first | [TinyTuya adapter](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-tuya/src/piphi_network_tuya/tuya.py), [poll/session state](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-tuya/src/piphi_network_tuya/state.py), and [supported-device matrix](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-tuya/SUPPORTED_DEVICES.md). | Runtime control depends on local host/device ID/key. Cloud discovery is optional assistance, not the operating transport. |
| Tests do not establish field quality | Package tests use mocks, fixtures, simulators, and ASGI clients; Tuya's [model-certification table](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-tuya/SUPPORTED_DEVICES.md#appendix-b--certified-and-validated-models) contains only `_TBD_`. | Automated behavior evidence is meaningful, but account/device compatibility, quotas, reconnection, and soak stability remain unproven. |
| CI/release foundations exist | [Changed-app CI](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/.github/workflows/apps-ci.yml) and [release workflow](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/.github/workflows/release-app.yml). | Declared installs/tests can run centrally; release design supports multi-architecture images, SBOM, provenance, and attestations. For these seven entries, legacy-static/container build flags are false in changed-app CI, and this audit found no matching release tags or published-attestation evidence. |

## Architecture-matched external references

| Area | Primary or owning source | What it establishes—and what it does not |
|---|---|---|
| Quality model | [Home Assistant Integration Quality Scale rules](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/) | Useful expectations for setup, reauth, unique identity, unavailable state, diagnostics, tests, and maintenance. It cannot award a tier to a PiPhi sidecar. |
| Aqara | [HA Aqara](https://www.home-assistant.io/integrations/aqara/); [Aqara Open API authorization](https://opendoc.aqara.com/en/docs/developmanual/authManagement/aqaraauthMode.html) | First-party user expectations and vendor cloud authorization architecture. |
| Daikin | [HA Daikin](https://www.home-assistant.io/integrations/daikin/); [Daikin Onecta developer portal](https://developer.cloud.daikineurope.com/); [owning `daikin_onecta` library at audited commit](https://github.com/jwillemsen/daikin_onecta/tree/78f4207c385fd616b6e3effd894318be64e2b029) | HA's integration is local and is only a UX/lifecycle reference. The portal/library define the relevant cloud OAuth, regional, API, and quota context. |
| Dyson | [HA removed-integration guidance](https://www.home-assistant.io/more-info/removed-integration/); [owning `ha-dyson` at audited commit](https://github.com/libdyson-wg/ha-dyson/tree/41c33383fa0dde1a9b80929ddb7ef96b5ad76474) | There is no current first-party matching integration. The custom owner project supplies architectural context, not first-party parity. |
| Eufy Security | [HA EufyHome](https://www.home-assistant.io/integrations/eufy/); [owning `eufy-security-ws` sidecar at audited commit](https://github.com/bropat/eufy-security-ws/tree/0bfce386045e2542da60e80c224e87998f60d3a9) | HA EufyHome is a different product/API surface. The owning community sidecar supplies architecture context, not first-party parity or vendor support. |
| LG ThinQ | [HA LG ThinQ](https://www.home-assistant.io/integrations/lg_thinq/); [`thinqconnect` package](https://pypi.org/project/thinqconnect/) | First-party account-cloud expectations and the owning SDK surface used by PiPhi. |
| Tuya | [HA Tuya](https://www.home-assistant.io/integrations/tuya/); [TinyTuya at audited commit](https://github.com/jasonacox/tinytuya/tree/b0482da13af473677a78ea76a94bd8ed2c37a3e7) | HA documents cloud integration behavior; TinyTuya documents local discovery/control and optional cloud assistance. They are related but not transport-equivalent. |
| Xiaomi | [HA Xiaomi Miio](https://www.home-assistant.io/integrations/xiaomi_miio/); [Xiaomi official `ha_xiaomi_home` at audited commit](https://github.com/XiaoMi/ha_xiaomi_home/tree/75b3acb6325a3a8d295688b13904737d6738a6a5) | `xiaomi_miio` is mainly a local-token family comparator; Xiaomi's official project is the appropriate current cloud-account/MIoT architecture reference. |

External documentation pages are live references as of the cutoff and may change. Repository-local and owning-library source links are pinned to the revisions audited where possible; package indexes and vendor/HA documentation remain canonical live references.

## Shared invariants for a production account/device integration

Every implemented package should satisfy these invariants regardless of vendor:

1. **Truthful readiness:** configured, authenticated, reachable, stale, unavailable, and unsupported are distinct states. A saved config is never sufficient evidence for `connected: true`.
2. **Stable identity:** account, installation/home, hub/station, and device IDs have documented scopes; hostnames, display names, and IP addresses are not primary identity when a vendor ID exists; duplicate configuration is rejected or merged deterministically.
3. **Credential lifecycle:** secrets are password-typed, never logged or returned by diagnostics, minimally retained, replaceable without delete/re-add, and transition to actionable reauth on expiry/revocation. OAuth refresh is serialized and rotation-safe; PAT/local-key invalidation has equivalent recovery.
4. **Region correctness:** region/country affects endpoints and eligibility explicitly. Region changes cannot silently strand identity or credentials.
5. **Bounded transport:** polling honors documented quotas, adds jitter/backoff, and stops cleanly; push authentication, replay/deduplication, liveness, and polling fallback are defined.
6. **State freshness:** each snapshot carries observation time and source; stale data is marked rather than presented as current; recovery clears unavailable state without duplicating entities or events.
7. **Capability provenance:** capabilities come from a vendor profile/specification or a model-certified mapping—not names alone. Raw vendor payloads remain debug data, not an implied stable contract.
8. **Mutation safety:** command schemas enforce ranges/enums and device capability. Security, heating/HVAC, locks, covers/garage doors, alarms, and raw writes are default-deny, auditable, and followed by state verification.
9. **Privacy by construction:** account/device IDs, home names, IPs, camera/security events, raw payloads, tokens, local keys, and webhook secrets have an explicit classification and recursive redaction tests.
10. **Evidence before claims:** each advertised family has executable tests; production claims additionally require named hardware/account evidence, outage/reconnect tests, and recorded soak results. CI artifacts and releases are traceable to source with SBOM/provenance where the release workflow supports them.

## Prioritized work

### P0 — block misleading or unsafe production claims

1. **Scaffolds:** stop emitting `connected: true` after configuration. Expose an explicit `not_implemented`/`unconfigured` state and ensure manifests, discovery, commands, and documentation cannot imply vendor support. Build one real vertical slice before publishing Daikin, Dyson, Eufy, or Xiaomi as integrations.
2. **All packages:** implement and test recursive secret/PII redaction for config, registry state, diagnostics, events, and errors. Add automated assertions using canary secrets.
3. **Aqara:** use constant-time webhook-token comparison; document webhook authentication/replay assumptions; redact diagnostic snapshots; test invalid/rotated refresh tokens and transition to reauth.
4. **ThinQConnect:** do not silently accept an unusable config after initial refresh. Classify invalid PAT, authorization, region, unsupported device, transient cloud outage, and rate limit; expose PAT replacement/reauth without delete/re-add.
5. **Tuya:** remove generic `set_dp` from ordinary entity command surfaces or require explicit advanced opt-in with DP allowlists. Gate cover/HVAC and similarly consequential inferred writes behind model-certified mappings; make the absence of certified models visible in support claims.

### P1 — complete lifecycle and operational resilience

1. Add common reauth/reconfigure semantics and contract tests: credentials, region/country, polling interval, push enablement, and identity-preserving updates.
2. Add quota-aware scheduling and structured rate-limit/backoff telemetry, especially for Onecta's documented daily budget and cloud polling fallbacks.
3. Add duplicate-account/device prevention, account/home/device identity migration tests, and removal reconciliation.
4. Add stale/unavailable/recovery contract tests with clock control, outage duration, push silence, restart, and post-command verification.
5. Define high-impact mutation classes and shared policy for confirmation, authorization, auditing, model allowlists, and safe ranges.
6. Make changed-app CI build and scan releasable containers for these packages; publish traceable releases with the existing SBOM/provenance/attestation path.

### P2 — expand breadth only after invariants hold

1. Populate real account/device matrices with vendor, model, region, firmware/protocol, supported capabilities, overrides, outage behavior, and 24/72-hour soak results.
2. Aqara: broaden only vendor-documented resource mappings; keep locks/cameras read-only until a separate security review approves writes.
3. ThinQConnect: add certified profile fixtures and field evidence across appliance families and regions; validate MQTT liveness and quota reduction.
4. Tuya: replace heuristic family breadth with product/category profiles and certified DP maps; retain raw DPS for diagnostics rather than default control.
5. Daikin, Dyson, Eufy, and Xiaomi: choose and document the official/owning client architecture, then implement auth → identity/discovery → one read-only state → offline/recovery → one bounded command as the first end-to-end slice.

## Validation performed and limits

- Reviewed source and tests at the pinned revision, including vendor adapters, config/command/state routes, capability catalogs, manifests, package dependencies, CI, and release workflows.
- Compared generated files and confirmed that the four scaffold packages share the same state/config/command implementation shell.
- Inspected test strategy and support matrices. Tests are automated with mocks, fixtures, simulators, or in-process clients; no test examined here demonstrated a real vendor account or physical device.
- No vendor credentials, live accounts, hardware, CI run logs, container registry attestations, or production telemetry were available. Consequently this report does **not** validate API access, current vendor quota behavior, model compatibility, command safety on hardware, reconnect behavior under real outages, or long-running stability.
- External sources were selected to match architecture. Name similarity was not treated as parity: local HA Daikin is not Onecta cloud; EufyHome is not Eufy Security; HA Tuya cloud push is not TinyTuya LAN polling; Xiaomi Miio local-token support is not Xiaomi Home cloud-account support.

The portfolio should therefore describe Aqara, ThinQConnect, and Tuya as **implemented, pre-certification slices with explicit limitations**, and the remaining four as **scaffolds/roadmaps**, until P0 controls and real account/device evidence are complete.
