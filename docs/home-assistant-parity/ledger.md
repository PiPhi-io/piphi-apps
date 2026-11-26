# Package audit ledger

**Source baseline:** `197d1b15181d5820f44fc8e620844ed6632b8d62`

**Registry baseline:** `f25a59c42051fdc5cd984a9ddc6e2822b30e64c7`

**Audit cutoff:** 2026-11-19

This is the package-by-package decision ledger. Exact source folders, versions,
release refs, images/digests, governance, and comparator URLs are machine-readable
in [`inventory.json`](inventory.json). Detailed historical comparisons linked by
that inventory remain evidence, but current source outranks stale prose.

Priority meanings: **P0** blocks safe publication or general use; **P1** is
required for a defensible supported product; **P2** is demand-driven breadth.
“Bounded” means a real, deliberately narrow vertical slice—not feature parity.

| Package | Current implementation | Priority | Principal current gap / next outcome |
|---|---|---:|---|
| `official-usb-gps-integration` | Bounded NMEA parser | P1 | Add fail-closed runtime auth, stable USB identity, unplug/replug and stale/no-fix semantics, privacy-safe diagnostics, and receiver fixtures. |
| `piphi-network-433mhz` | Bounded receive-only rtl_433 slice | P0 | Correct SNR/RSSI and identity semantics; add per-device expiry, receiver/LWT health, MQTT TLS, uniform auth, and attributed RF fixtures. |
| `airthings-consumer-cloud-api` | Real official cloud adapter | P1 | Software lifecycle hardening completed for `0.1.10`: guided transactional credential repair, fail-closed runtime auth, bounded quota retry, stable identity, stale/last-good recovery and removal semantics, mounted-snapshot restoration, privacy-safe diagnostics, and exact-image qualification. Live account/device qualification remains unverified. |
| `piphi-network-android-tv` | Real Remote v2 + bounded ADB slice | P0 | Require fail-closed control-plane auth for pairing/actions; then qualify reconnect, identity change, firmware/device cohorts, and rollback. |
| `aqara-open-api` | Real signed cloud adapter | P0 | Remove unsupported Bronze claim until `quality-scale.yaml` evidence exists; improve delegated auth/account modeling and qualify high-impact profile-derived controls. |
| `atmotube-pro-ble` | Real narrow direct-BLE reader | P0 | Repair the declared binary artifact/release path, opaque identity/privacy, restart recovery, shared-gateway strategy, and physical qualification. |
| `awair-element-local-api` | Real local air-quality adapter | P1 | Tighten discovery identity and redirect/host policy; add runtime auth, transactional address changes, stale/recovery tests, and hardware evidence. |
| `piphi-network-bacnet` | Bounded read-only Kaiterra BACnet/IP slice | P0 in remediation | Version 0.1.1 adds fail-closed auth, connect-before-save, transactional replacement, stale-last-good recovery/backoff, transition dedupe, and locked hardened image build. Restart rehydration and physical evidence remain. |
| `piphi-network-bambu-lab` | Real read-only LAN print-status slice | P1 | Preserve the safe narrow scope; add classified freshness/reconnect behavior, explicit model matrix, fail-closed auth, and physical qualification. |
| `piphi-network-bermuda-presence` | Real gateway-backed presence inference | P1 | Add runtime auth, rotating/private-address workflow, calibration/topology diagnostics, scale tests, and physical room-transition evidence. |
| `piphi-network-daikin-onecta` | Nonfunctional scaffold | P0 | Stop synthetic connectivity/demo claims; implement supported OAuth, explicit account/device identity, quota-aware state/recovery, then one bounded HVAC action. |
| `piphi-network-dyson` | Nonfunctional scaffold | P0 | Withdraw from functional distribution; choose an owned client architecture and implement credential bootstrap, local transport, state/recovery, and a model-qualified safe slice. |
| `piphi-network-eufy-security` | Nonfunctional scaffold | P0 | Withdraw misleading security claims; decide sidecar/client architecture, then implement challenge-aware auth, station/device identity, privacy, events, and separately reviewed mutations. |
| `piphi-network-huawei-solar` | Real two-register read-only Modbus slice | P0 | Add route auth, host/port/unit identity, per-endpoint serialization, bounded retry, restart restore, stale state, DNS/IP enforcement, and truthful energy semantics. |
| `piphi-network-i2c` | Deliberately mock-only runtime | P0 | Add runtime auth and make mock-only status unmistakable in catalog UX; physical support requires exact device/GID grants, identity, serialization, hotplug, and qualification. |
| `piphi-network-kaiterra-api` | Real official cloud polling slice | P1 | Add runtime auth, query-key log scrubbing evidence, provider quota/Retry-After behavior, guided reauth, privacy policy for motion, and real-device fixtures. |
| `piphi-network-kia-hyundai-connect` | Nonfunctional scaffold | P0 governance | Stop synthetic availability. Product/legal approval is required before any unofficial owner-service adapter; if approved, start with one read-only brand/region cohort. |
| `piphi-network-knx` | Strong bounded KNX tunnel slice | P1 | Add Core-backed restart state and physical interface evidence; expand DPT/entity/security breadth only from qualified demand. |
| `piphi-network-matter-integration` | Real but On/Off-only parent projection | P1 | Declare compatible sidecar install/network/token contract, project more negotiated sidecar capabilities, sanitize errors, and reconcile physical-evidence docs. |
| `piphi-network-midea-ac-lan` | Real AC climate/control slice | P0 | Secret-type token/key, authenticate all management/action routes, make reauth/reconfigure transactional, prove identity/address recovery, and qualify exact models. |
| `piphi-network-mikrotik-router` | Real read-only RouterOS 7 monitoring slice | P0 | Add runtime auth and Core-backed restart restoration; then expand only from least-privilege profiles and physical RouterBOARD/CHR evidence. |
| `piphi-network-modbus` | Strong multi-transport profile-bound read/write slice | P1 | Narrow serial grants, trust-anchor profiles, improve block scheduling and diagnostics/repair UX, align sidecar docs, and add physical TCP/RTU/ASCII evidence. |
| `piphi-network-nord-pool` | Real interval-aware public market data | P0 governance | Obtain written redistribution/endpoint approval or migrate to the licensed API; then add fuller schedules/statistics/reconfigure UX and full CI. |
| `piphi-network-octopus-energy` | Real narrow public tariff reader | P1 | Keep public-price scope explicit; add supported standing-charge/multi-register/gas/export breadth only deliberately, plus quality evidence and release canary. |
| `piphi-network-openepaperlink` | Real AP aggregate-count slice | P1 | Add route auth, AP trust/SSRF/proxy controls, tag lifecycle and recovery; per-tag rendering/control is later product breadth. |
| `piphi-network-passive-ble-monitor` | Strong bounded BTHome gateway consumer | P0 | Add fail-closed runtime auth; then encrypted bindkeys, wider measurements/events, sleepy-device behavior, and hardware fixture evidence. |
| `piphi-network-pfsense` | Real profile-bound monitoring and bounded actions | P0 | Authenticate every route and restore config on restart; then qualify pfREST/CE/Plus/CARP matrices and postcondition/audit behavior. |
| `piphi-network-plex` | Real browse/search server slice | P0 | Add route auth, secret token boundary, strict SSRF/redirect/TLS policy, reauth/server-address recovery, push/session semantics, and full release evidence. |
| `piphi-network-reolink` | Real authenticated polling/control slice | P1 | Add push events, channel-stable entities, battery-safe behavior, inventory retention, capability-gated controls, and camera/NVR physical matrix. |
| `piphi-network-sense` | Hardened unofficial account adapter; deterministic qualification only | P0 release/registry | Source `0.2.1` adds fail-closed auth, private token persistence, transactional identity-safe reconfiguration, restart rehydration, bounded recovery, per-slice freshness, privacy retention, and provider-local daily periods. Publish and verify the immutable multi-arch artifact, then synchronize the stable registry without changing rollout, lifecycle, tier, or unverified qualification. |
| `piphi-network-solaredge` | Real read-only Monitoring API V1 adapter | P0 | Migrate from the now-deprecated V1 contract to supported V2 OAuth before release; add multi-site identity, inventory and corrected historical/statistics semantics. |
| `piphi-network-sonoff-lan` | Real narrow plaintext DIY monitor | P0 | Add runtime auth and DNS-rebinding controls; preserve trusted-LAN/read-only labeling, then add identity/address recovery and model evidence. |
| `piphi-network-spi` | Deliberately mock-only runtime | P0 | Add runtime auth and truthful mock-only catalog UX; physical support requires one exact spidev grant, chip identity, bus policy, hotplug and qualification. |
| `piphi-network-steam` | Real account/library summary | P0 | Add runtime auth, prevent plaintext key retention, minimize diagnostics/persona activity, and add rate-limit/backoff/reauth behavior before release migration. |
| `piphi-network-tapo-cameras` | Nonfunctional scaffold | P0 | Remove fake discovery/entity/connectivity/refresh and premature camera/media claims; implement local auth/discovery/model state before a separately secured brokered-media lifecycle. |
| `piphi-network-tesla-ev` | Real conservative Fleet API proof of concept | P0 | Implement authorization-code OAuth, rotating refresh/account binding and durable request budgets; keep location off and wake bounded before any broader account/product support. |
| `lg-thinq-connect-api` | Real official SDK/profile-driven adapter | P1 | Add formal quality/release evidence, privacy/retention docs, account-level modeling and model/region appliance qualification—especially for high-impact writes. |
| `tp-link-kasa-local-api` | Real broad local Kasa adapter | P0 | Secret-type credentials, uniform runtime auth, transactional connect-before-replace, and profile/model-qualified actions; remove generic unsafe/reboot surfaces from ordinary use. |
| `piphi-network-tuya` | Real LAN adapter with unsafe inferred writes removed | P1 | Populate model-certified mappings, complete local-key recovery, constrain raw DPS diagnostics/overrides, add runtime auth, and migrate from legacy release discipline. |
| `piphi-network-washdata` | Nonfunctional scaffold | P0 | Stop synthetic availability; implement source-entity binding, persistent cycle state/migrations, detection/learning semantics, recovery and deterministic fixtures. |
| `piphi-network-waste-collection` | Real manual one-date reminder | P1 | Rename/describe exact manual scope; add recurrence, exceptions, multiple streams, rollover and source health only if provider/calendar functionality is intended. |
| `piphi-network-weatherxm` | Real adapter to unsupported mobile-account API | P0 governance | Migrate to documented WeatherXM Pro API or remain explicitly unsupported/experimental; add token lifecycle, conservative cadence, privacy and release evidence. |
| `piphi-network-xiaomi-home` | Nonfunctional scaffold | P0 | Stop synthetic product claims; implement official OAuth/region/MIoT discovery and one truthful state/recovery/action slice before distribution. |
| `piphi-network-zigbee` | Real parent integration over hardened Zigbee2MQTT sidecar | P0 | Authenticate parent routes, restore subscriptions/config on restart, model endpoints separately, and reconcile publish/bridge/device outcomes plus permit-close cleanup. |
| `piphi-network-zwave` | Real parent integration over Z-Wave JS sidecar | P0 | Include full hashed Home ID/controller identity, restore state after restart, declare sidecar dependency/network/token contract, and reconcile node replacement/removal. |
| `piphi-android-adb-sidecar` | Strong narrow authenticated ADB transport | P1 | Add Android 11+ pairing/mDNS, reproducibly pinned platform tools, healthcheck, restart/auth-revocation tests and physical-device matrix. |
| `piphi-ble-gateway-sidecar` | Strong bounded queue/privacy logic | P0 | Make Linux packaging executable: explicit BlueZ/D-Bus mediation, persistent key/checkpoint volume, locked non-root read-only image, dependency-aware readiness, and artifact qualification. |
| `piphi.service.matter-sidecar` | Strong authenticated Matter controller alpha | P0 install contract | Declare stable managed storage/backup identity and parent dependency; sanitize backend errors and qualify exact releases, Thread, arm64, and required device profiles. |
| `piphi-modbus-rtu-sidecar` | Strong serialized profile-bound serial worker | P1 | Reconcile public manifest with real serial/profile contract, make readiness bus-aware, narrow device mapping, add strict quality gates and physical noise/timing evidence. |
| `piphi.service.mqtt-broker` | Hardened authenticated Mosquitto service | P1 | Add managed identity revoke/disconnect lifecycle, backup/restore/disk procedures, `$SYS` observability, pinned build input, vulnerability policy and exact-image qualification. |
| `piphi-network-llm-vision` | Nonfunctional unauthenticated scaffold | P0 | Withdraw or make non-installable; then implement authenticated brokered media references, one provider, bounded/cancellable jobs, consent/retention and typed results. |
| `piphi.service.zigbee2mqtt-sidecar` | Strong coordinator/backup/fencing helper | P1 | Add custom CA/mTLS, endpoint/composite expose fidelity, bridge-aware readiness, remote-coordinator caveats, and exact 0.1.26 artifact qualification. |
| `piphi.service.rtl433-bridge` | Real bounded rtl_433 transport helper | P1 | Add MQTT TLS/LWT/idempotency, independent reconnect, log redaction, truthful health, selected-device mapping, and exact-image/hardware tests. |
| `piphi-zwave-js-sidecar` | Real authenticated Z-Wave JS transport | P0 install contract | Establish parent auto-install/network/token compatibility, narrow serial device access, then implement safe commissioning/NVM backup and physical controller/security qualification. |

## Portfolio release/governance ledger

- **26 packages** use full CI; their baseline registry digests had both-platform
  SBOMs and cryptographically verified provenance at the audit cutoff (25 from
  `PiPhi-io/piphi-apps`, Reolink from its PiPhi-owned external repository).
- **28 packages** remain `legacy-static`; central monorepo publication refuses
  them. Twenty-seven legacy OCI packages declare future GHCR targets while the
  live registry still references Docker Hub.
- **27 in-scope packages** have no registry image digest. Eleven of those are
  stable/100% OCI listings; Atmotube is stable/100% with no immutable artifact.
- Source/registry versions drift for Atmotube, Awair, Sense, LLM Vision, and
  Midea. Sense additionally has mismatched stable version/ref/image.
- All 54 packages remain qualification `unverified`; publication and rollout
  state must be preserved unless a separate governance decision approves change.
