# Home Assistant quality comparison: PiPhi Android TV and ADB sidecar

**Research cutoff:** 2026-11-15

**PiPhi revision audited:** [`e9c7fb5`](https://github.com/PiPhi-io/piphi-apps/tree/e9c7fb55230a5512735f333c7f802e580f81743a)

**Home Assistant Core revision audited:** [`fa833f6`](https://github.com/home-assistant/core/tree/fa833f65085ff72e8191620ae2fc2a378205b6f2)
**Home Assistant documentation revision audited:** [`8d777bf`](https://github.com/home-assistant/home-assistant.io/tree/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f)

## Current implementation status

> **Implementation update (2026-11-25):** The findings below describe the
> audited `e9c7fb5` baseline. The current worktree implements bounded Remote
> Protocol v2 and isolated network ADB slices: authenticated pairing and
> discovery, connect-before-save, stable opaque identities, measured state,
> reconnect and reauth signaling, Core restart restoration, bounded queues,
> opt-in allow-listed short key commands, lifecycle cleanup, recursive secret
> redaction, and fail-closed runtime boundaries. Android 11+ wireless ADB pairing
> and mDNS use pinned Platform Tools in the sidecar. Hardware/firmware
> qualification, USB, long-press/text/deep-link controls, and broad ADB
> administration remain outstanding or deliberately excluded.

## Archived baseline assessment (`e9c7fb5`)

> The remainder of this report is retained as the evidence-based assessment of
> the audited baseline. Statements below about what PiPhi "currently" lacks
> refer to revision `e9c7fb5`, not to the current implementation update
> above.

PiPhi does **not yet implement Android TV control or an ADB sidecar**. Both packages are coherent runtime-contract scaffolds, but configuring either one immediately records `connected: true` without opening a socket, authenticating, pairing, discovering a device, or invoking ADB; the sole `refresh` action records a `runtime.command.received` event and returns its arguments. The honest supported slice is therefore:

- PiPhi configuration registration/removal;
- an in-memory `connected` placeholder, not measured device availability;
- runtime events and basic diagnostics;
- event-only `refresh` dispatch; and
- fail-closed rejection of every undeclared command.

That slice is materially smaller than either first-party Home Assistant integration. It must not be described as monitoring or controlling Android TV, Google TV, or Fire TV, and the ADB sidecar must not be described as owning Platform Tools, pairing, queues, USB, wireless transport, or recovery until those paths exist. PiPhi's catalogs label those areas `planned`, which is accurate, but the marketplace summaries, compatibility claims, `offline_support: full`, and discovery labels currently overstate the executable product ([Android TV manifest](../manifest.json#L7-L8), [ADB sidecar manifest](../../../services/piphi-android-adb-sidecar/manifest.json#L7-L8)).

The two Home Assistant references are also **not interchangeable**:

1. **Android TV Remote** uses Android TV Remote Protocol v2, the protocol used by the Google TV mobile app. It requires the Android TV Remote Service, on-screen PIN pairing, and a client certificate/key, but **does not use ADB or require developer options**. Home Assistant exposes local-push power, volume, foreground-app, remote keys/text, deep links, channels, and media controls. Fire TV is explicitly unsupported because it lacks the service ([library statement](https://github.com/tronikos/androidtvremote2/blob/387de891bd7d0cacf44ede7841470db153c53009/README.md#androidtvremote2), [HA docs](https://github.com/home-assistant/home-assistant.io/blob/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f/source/_integrations/androidtv_remote.markdown#limitations-and-known-issues)).
2. **Android Debug Bridge** is a privileged debugging channel. It requires debugging to be enabled and an RSA authorization accepted on the device, uses either HA's Python ADB client or an optional ADB server, polls shell-derived state, and supports Android/Fire TV. Home Assistant also exposes arbitrary shell commands and bounded-by-HA-path upload/download actions; PiPhi intentionally excludes that broad surface. Android documents ADB as a client/server/daemon architecture with host server port 5037 and access to a device Unix shell ([Android ADB guide](https://developer.android.com/tools/adb#how-adb-works), [HA ADB source](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv/__init__.py#L75-L104)).

The recommended product direction is to make **Remote Protocol v2 the normal Android/Google TV path** and reserve the ADB sidecar for a deliberately smaller, typed, single-target compatibility/observability path (especially Fire TV and capabilities the remote protocol cannot provide). Do not route Remote Protocol v2 through the ADB sidecar.

## Scope and method

This audit reviewed the PiPhi source, tests, manifests, package metadata, Dockerfiles, centralized CI/release workflows, local tags, and docs. External claims use only first-party or owning-project sources: Home Assistant Core and docs, Android/AOSP, and the exact upstream libraries HA pins. Home Assistant's Integration Quality Scale (IQS) is used **analogically** for PiPhi; PiPhi is not a Home Assistant Core integration and cannot literally earn an HA tier.

## Protocol and product boundary

| Question | Android TV Remote Protocol v2 | Android Debug Bridge |
|---|---|---|
| Purpose | Consumer remote-control protocol | General debugging and device-administration bridge |
| Device prerequisite | Android TV Remote Service; no developer mode | Developer options plus USB/wireless ADB debugging |
| Authentication | Generated client certificate/key plus on-screen pairing PIN ([HA flow](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv_remote/config_flow.py#L70-L145)) | RSA host key accepted on-device; HA generates a key if absent ([HA setup](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv/__init__.py#L75-L104)); Android requires unlock and acknowledgement ([Android](https://developer.android.com/tools/adb#enable-adb-debugging-on-your-device)) |
| Discovery/address churn | `_androidtvremote2._tcp.local.`; MAC is stable unique ID and discovery updates host ([manifest](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv_remote/manifest.json), [flow](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv_remote/config_flow.py#L147-L194)) | HA is manual host/port; connection yields Ethernet/Wi-Fi MAC used as unique ID ([flow](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv/config_flow.py#L124-L185)) |
| Update model | Push callbacks for availability, power, current app, and volume | Polling; reconnect attempted on update when unavailable ([media player](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv/media_player.py#L261-L306)) |
| Natural control surface | Key down/up/tap, text IME, app/deep-link launch, power, volume, foreground app | Shell-derived state, keys, app start/stop, media/volume, screenshots, files, arbitrary shell |
| Notable limits | No playback status; app-ID launch can be unreliable; no Fire TV; some powered-off TVs leave the network ([HA docs](https://github.com/home-assistant/home-assistant.io/blob/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f/source/_integrations/androidtv_remote.markdown#limitations-and-known-issues)) | State parsing varies by app/device; debugging is highly privileged; network ADB reliability varies ([HA docs](https://github.com/home-assistant/home-assistant.io/blob/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f/source/_integrations/androidtv.markdown#custom-state-detection)) |
| PiPhi placement | Should be implemented directly in `piphi-network-android-tv` | Should be isolated in `piphi-android-adb-sidecar` and exposed only through typed parent operations |

## Evidence table

| Area | PiPhi evidence at cutoff | Home Assistant / Android reference | Assessment |
|---|---|---|---|
| Executable transport | Neither package depends on `androidtvremote2`, `androidtv`, `adb-shell`, nor Platform Tools; dependencies are FastAPI, Uvicorn, and the PiPhi runtime kit ([integration pyproject](../pyproject.toml#L1-L16), [sidecar pyproject](../../../services/piphi-android-adb-sidecar/pyproject.toml#L1-L17)). | HA pins `androidtvremote2==0.3.3` for Remote v2 and `adb-shell[async]==0.4.4` plus `androidtv[async]==0.0.75` for ADB ([Remote manifest](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv_remote/manifest.json), [ADB manifest](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv/manifest.json)). | **Absent.** |
| Configuration validation | `DeviceConfig` requires only `host`; generic unused fields include `api_key`, `base_url`, and polling interval ([integration schema](../src/piphi_network_android_tv/schemas.py#L6-L12), [sidecar schema](../../../services/piphi-android-adb-sidecar/src/piphi_android_adb_sidecar/schemas.py#L6-L12)). | Both HA flows connect before creating an entry; Remote v2 also pairs, while ADB validates key/server exclusivity and key readability. | PiPhi accepts unreachable/arbitrary hosts and has no protocol/port/transport model. |
| Pairing and authorization | No certificate, private-key, PIN, RSA signer, authorization status, revocation, or secret store exists. Pairing is catalog-only `planned`. | Remote v2 generates a certificate, starts pairing, consumes a PIN, handles invalid auth and reauth ([flow](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv_remote/config_flow.py#L70-L145)). HA ADB generates/loads an RSA key and distinguishes direct Python ADB from server mode ([source](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv/__init__.py#L75-L104)). | **Absent.** Never accept or persist a PIN as normal config. |
| Connectivity truth | `apply_config()` unconditionally writes `connected: true` in both packages ([integration](../src/piphi_network_android_tv/state.py#L72-L89), [sidecar](../../../services/piphi-android-adb-sidecar/src/piphi_android_adb_sidecar/state.py#L72-L89)). | HA Remote times out initial connect, marks setup not ready, reports callbacks, and keeps reconnecting ([source](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv_remote/__init__.py#L20-L70)). HA ADB reconnects while polling. | Current state is configuration presence mislabeled as connectivity. This is the highest-severity correctness defect. |
| Commands and allowlists | The only declared command is `refresh`. Handler code appends an event and echoes data; it does not refresh anything ([integration state](../src/piphi_network_android_tv/state.py#L104-L138), [command route](../src/piphi_network_android_tv/routes/commands.py#L13-L62)). Unknown commands are rejected and tests cover several unsafe names ([test](../tests/test_capability_catalog.py#L99-L114)). Sidecar behavior is identical. | Remote v2 sends keys, including down/up long-press directions, text, and deep links ([remote source](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv_remote/remote.py#L103-L149)). HA ADB accepts known key names **or arbitrary shell**, and also upload/download ([ADB services](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv/services.py)). | Fail-closed catalog enforcement is a useful seed, but `refresh` is a false-success action. PiPhi should remain narrower than HA ADB and add typed enums, not shell strings. |
| Key handling | No keys are implemented. Planned action names cover navigation/text but define no enum, protocol mapping, press/release semantics, repeat limits, text encoding, firmware capability negotiation, or concurrency policy ([catalog](../capability-catalog.json#L48-L55)). | HA Remote forwards protocol key names and supports `SHORT`, `START_LONG`, `END_LONG`, repeats, delay, and timed hold; device/firmware may remap or ignore keys ([source](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv_remote/remote.py#L25-L149), [docs](https://github.com/home-assistant/home-assistant.io/blob/8d777bfc7ab4b0bb6b16a4eb605f6dd5d4138a2f/source/_integrations/androidtv_remote.markdown#sending-key-commands)). | Define a conservative allowlist and exact press lifecycle before exposing keys. Ensure held keys are released on cancellation/disconnect. |
| Device identity | Manifest identity is only user-supplied `host`; discovery returns fixed IDs (`demo-device` / `android-adb-service`) and defaults to loopback ([integration discovery](../src/piphi_network_android_tv/routes/discovery.py#L15-L27), [sidecar discovery](../../../services/piphi-android-adb-sidecar/src/piphi_android_adb_sidecar/routes/discovery.py#L15-L27)). | HA Remote uses device-advertised MAC as unique ID and manufacturer/model in device info ([entity](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv_remote/entity.py#L24-L48)); HA ADB prefers Ethernet/Wi-Fi MAC and refuses setup without a usable ID. | Host/IP is mutable and not device identity. Fake discovery risks collisions and false devices. |
| Lifecycle and reconnect | Startup callback is a no-op; no sessions/tasks/sockets are created or canceled ([integration lifecycle](../src/piphi_network_android_tv/lifecycle.py#L12-L20), [sidecar lifecycle](../../../services/piphi-android-adb-sidecar/src/piphi_android_adb_sidecar/lifecycle.py#L12-L20)). No timeout, retry, jitter, queue, backpressure, or recovery implementation exists. | HA Remote distinguishes invalid auth from network failure, updates address by mDNS, reconnects continuously, and disconnects on unload/HA stop. HA ADB closes on unload/stop and reconnects during updates. | **Absent.** Sidecar queue/recovery catalog is design intent only. |
| State | Only `connected`, `host`, `alias`, and `config_id` are stored. All TV/media/ADB states in catalogs are planned. | HA Remote pushes on/off, volume/mute, current app, availability; playback is explicitly assumed/unsupported ([media source](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv_remote/media_player.py#L38-L105)). HA ADB polls power/playback/app/running apps/volume/HDMI and optional screenshots. | PiPhi must not claim media or monitoring support. Preserve “unknown” rather than manufacture truth. |
| Diagnostics and privacy | Diagnostics provide active config IDs, event count, kind, and contract. They do not provide transport/device health. Config-applied events include host and alias ([health](../src/piphi_network_android_tv/routes/health.py#L17-L29), [state](../src/piphi_network_android_tv/state.py#L85-L89)). Catalogs appropriately exclude raw keys, PINs, raw shell/log/screenshot output, and account/activity history. | HA Remote redacts host and MAC from config diagnostics ([source](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv_remote/diagnostics.py)). HA ADB redacts unique IDs/MACs/serial and registry identifiers ([source](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv/diagnostics.py)). | Good stated privacy direction, but no explicit redaction utility/test, retention bound, credential-path policy, or host hashing. Diagnostics are not yet useful for protocol failures. |
| Host/process boundary | Android TV container maps fixed host port 4220; sidecar uses a Core-allocated port with no manifest host mapping. There is no parent-to-sidecar client, authentication contract, target lease, or credential mount. The sidecar image contains no `adb` binary ([Android Dockerfile](../Dockerfile), [sidecar Dockerfile](../../../services/piphi-android-adb-sidecar/Dockerfile)). | ADB server normally binds its smart socket to `tcp:localhost:5037`; Android documents all clients sharing server port 5037 ([Android](https://developer.android.com/tools/adb#how-adb-works)). | Keep ADB server and its key directory private to the sidecar. Never bind 5037 to LAN/all interfaces. Parent API must be authenticated, typed, single-target, and output-bounded. |
| Tests | Tests validate routes, fixture response keys, catalog/manifest consistency, event emission, and rejection of sample unsafe commands. There are no protocol, pairing, auth, reconnect, cancellation, identity, redaction, queue, timeout, malformed-device, or real/fake-device tests. | HA Remote's declared Platinum file marks full config-flow and >95% per-module coverage complete ([quality file](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv_remote/quality_scale.yaml)). | Current tests prove scaffold consistency, not Android behavior. |
| CI | Central CI discovers changed apps and runs declared PDM install/check and pytest commands. Both packages set `build_container: false`, so PR CI does not build their images ([package metadata](../piphi-app.json#L14-L21), [workflow](https://github.com/PiPhi-io/piphi-apps/blob/e9c7fb55230a5512735f333c7f802e580f81743a/.github/workflows/reusable-app-ci.yml#L72-L84)). | HA IQS requires transparent dependencies, full flow tests, and >95% module coverage for Silver/above ([IQS rules](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules)). | Useful central mechanics, insufficient transport qualification; no hardware/fake-adbd matrix or image smoke test. |
| Release evidence | Manifests are draft, unverified, rollout 0, quality `unrated`. No matching namespaced release tags exist in the audited checkout. `piphi-app.json` targets GHCR while runtime manifests/docs still point to Docker Hub. Central release workflow can qualify, multi-arch build, emit SBOM/provenance, attest, and attach immutable evidence, but no artifact evidence is present for these versions ([workflow](https://github.com/PiPhi-io/piphi-apps/blob/e9c7fb55230a5512735f333c7f802e580f81743a/.github/workflows/release-app.yml#L108-L225)). | HA source pins exact dependency versions. | Treat 0.1.0/0.1.1 as draft metadata, not proven releases. Reconcile registry/image references before any publication. |

## Feature and behavior gaps

### Against Home Assistant Android TV Remote

PiPhi lacks every device-facing behavior: Remote v2 TLS/certificate handling, on-screen PIN flow, reauthentication, mDNS discovery, stable MAC identity, address updates, push listeners, reconnect, unavailable state, device metadata, foreground app, power, volume/mute, media keys, navigation, long press/down/up, bounded repeats/delays, text IME, deep links, app aliases/icons, channel entry, unload cleanup, translated user errors, redacted diagnostics, and documented limitations.

PiPhi should **not** copy HA Remote's broad “send any protocol key name” interface blindly. A behavior/automation system needs a smaller enum, per-action authorization/risk metadata, maximum repeat and hold durations, cancellation-safe key release, per-device serialization, and audit events that omit text content by default.

### Against Home Assistant Android Debug Bridge

PiPhi lacks an ADB binary/client, server ownership, 5037 contention handling, host/device feature negotiation, USB passthrough, TCP targets, mDNS wireless discovery, Android 11+/TV 13+ pairing-code flow, RSA authorization, target selection, device-state tracking (`device`, `offline`, `unauthorized`), command execution, output bounds, queues, deadlines, cancellation, reconnect, and restart reconciliation. Android's current wireless-debugging requirements include same-network pairing and Android 13+ for TV; pairing remains until forgotten/revoked ([Android](https://developer.android.com/tools/adb#wireless-adb-android-11)).

Intentional non-parity is correct for arbitrary shell, package installation/removal, arbitrary file transfer, forwarding/reverse tunnels, root/remount/recovery, unrestricted intents, raw logcat, and raw credential exposure. HA exposes several of these because it is an administrator-operated integration; PiPhi automations should not. Android's own documentation confirms that ADB can run shell commands, copy arbitrary files, install packages, and forward ports, which is why the sidecar is a security boundary rather than merely a helper process ([Android ADB guide](https://developer.android.com/tools/adb#issue-shell-commands)).

### Manifest, docs, and support-claim gaps

- Change “Monitor and control … through managed ADB” to “Draft scaffold; no device transport implemented” until a real slice lands.
- Remove passive/managed discovery claims while `/discover` returns a fabricated object.
- Set offline support to `none` or an equivalent honest value; no operation is possible offline or online.
- Do not claim USB access until the container declares and tests a device-pass-through model.
- Make Remote v2 and ADB support matrices separate. Remote v2 normally covers Android/Google TV but not Fire TV; ADB is the compatibility path for Fire TV.
- Reconcile GHCR package publication metadata with Docker Hub image references and update generated release docs.

## IQS tier assessment

Home Assistant's current IQS has 20 Bronze, 10 Silver, 21 Gold, and 3 Platinum rules; a tier requires all rules at that tier and below ([rules](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules)). The first-party **Android TV Remote integration is Platinum** and carries an explicit rule-by-rule evidence file ([manifest](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv_remote/manifest.json), [quality scale](https://github.com/home-assistant/core/blob/fa833f65085ff72e8191620ae2fc2a378205b6f2/homeassistant/components/androidtv_remote/quality_scale.yaml)). The first-party **Android Debug Bridge integration declares no quality tier** in its manifest, so it is an ungraded legacy reference, not a quality-scale target.

### PiPhi analogical result: below Bronze / not tier-eligible

Positive evidence includes async FastAPI routes, typed configuration models, an unload-like deconfigure route, contract fixtures, fail-closed undeclared commands, a machine-readable planned/excluded catalog, centralized ownership metadata, and baseline user-facing docs. Those do not overcome missing Bronze fundamentals:

- no connection test before configure or startup;
- no real unique device identity or duplicate-device prevention;
- no device entity backed by transport state;
- no functioning action despite advertising `refresh`;
- no setup/auth/pairing/recovery flow;
- no device-facing dependency or transparent protocol adapter;
- no meaningful installation, removal, supported-function, data-update, limitation, or troubleshooting documentation;
- no evidence that callbacks/tasks are attached and removed through lifecycle because none exist; and
- no integration-specific functional test coverage.

Silver is blocked by unavailable-state correctness, reconnection/reauth, action exceptions, parallelism/queue policy, and coverage. Gold is blocked by real discovery, complete device information, redacted useful diagnostics, translations, reconfiguration/repairs, and user documentation. Platinum is blocked by the absence of an async device dependency and strict checked implementation. The sidecar is not itself a user-device HA integration, but the same reliability and diagnostics expectations should gate its publication.

## Safety invariants

These are release blockers, not optional hardening:

1. **No false connectivity:** `connected`/`available` may become true only after the selected protocol authenticates and proves a live target; configuration presence is separate state.
2. **No protocol confusion:** Remote v2 certificates/PINs never enter the ADB sidecar; ADB RSA keys and pairing codes never enter the parent integration's entities/events.
3. **One explicit target per operation:** every sidecar request carries a resolved target lease/transport ID; never fall back to “first device” or `adb -a`/all devices.
4. **No arbitrary execution:** no raw shell, intent, package-manager, file path, forwarding, root, reboot-mode, or recovery primitive crosses the parent-sidecar API.
5. **Typed allowlists at both boundaries:** parent and sidecar independently validate operation enum, key enum, app/package allowlist, argument sizes, and target authorization.
6. **Bound every resource:** queue depth, per-consumer share, command timeout, output bytes, retries, backoff, text length, repeat count, key hold duration, screenshot size/retention, and event retention all have hard limits.
7. **Release held keys:** cancellation, timeout, disconnect, process shutdown, and queue purge must attempt the matching key-up and must not replay non-idempotent key downs after restart.
8. **Credentials are non-exportable secrets:** use restrictive files/volumes; never return private keys, certificates, pairing codes, or raw public-key labels through config, state, logs, events, diagnostics, or backups without an explicit secret policy.
9. **Pairing codes are one-shot:** accept only through an interactive, expiring flow; redact immediately; never persist in config or event payloads.
10. **ADB stays local/private:** do not expose server port 5037 or the sidecar control API to LAN/WAN. Use a private runtime network/socket plus authenticated Core identity and reject non-parent callers.
11. **Identity is device-derived and privacy-safe:** use verified MAC/serial-derived opaque IDs, survive IP changes, reject duplicates, and redact raw MAC/serial/host from diagnostics and telemetry.
12. **No sensitive observation by default:** screenshots, current text, focused window, activity history, logs, and account-bearing metadata require explicit opt-in, minimal collection, short retention, and redaction.
13. **Unknown stays unknown:** unsupported firmware/app parsing yields unknown/unavailable with a reason, never guessed playback, power, authorization, or app state.
14. **Audit without content leakage:** record operation type, target opaque ID, outcome, latency, and bounded error code; do not record entered text, PINs, command output, URLs with tokens, screenshot bytes, or full package/activity history.

## Prioritized next work

### P0 — make current claims truthful and preserve the boundary

1. Stop setting `connected: true` on config and make `refresh` return a clear not-implemented/error result until it performs I/O.
2. Correct marketplace descriptions, discovery/offline/USB claims, compatibility matrix, and image registry references. Keep publication draft/rollout 0.
3. Write and test a versioned parent-sidecar contract containing only typed, single-target, bounded operations and explicit error codes (`unauthorized`, `offline`, `timeout`, `queue_full`, `unsupported`).
4. Add threat-model tests for arbitrary shell/intent/path/package/forwarding fields, target omission, oversized payloads, output truncation, queue exhaustion, and secret redaction.

### P1 — ship a small Remote v2 vertical slice first

5. Add an async Remote v2 adapter directly to the integration: manual host plus `_androidtvremote2._tcp.local.` discovery, certificate generation/storage, expiring PIN pairing, stable MAC identity, connect-before-save, unload, reconnect with jitter, reauth, and redacted diagnostics.
6. Initially expose only measured availability/power/current app and a conservative key set (directional, center, back, home, play/pause, volume). Add per-device serialization, strict repeat/hold bounds, and key-up cleanup.
7. Test with a deterministic fake Remote v2 server plus representative Android/Google TV fixtures: invalid PIN, reset credentials, IP change, disconnect during held key, malformed messages, app/volume updates, and unavailable-to-recovered transitions.

### P2 — implement the isolated ADB compatibility slice

8. Build/pin official Platform Tools in the sidecar image with SBOM/provenance; own one private ADB server and key directory; detect version/features and 5037 contention.
9. Implement manual legacy TCP authorization first, then Android 11+/TV 13+ mDNS pairing-code flow. Model `unauthorized`, `offline`, `device`, and boot-not-ready distinctly.
10. Add bounded per-target queues, fair scheduling, deadlines, cancellation, retry classification, backpressure, restart reconciliation, and health metrics. No operation may silently migrate to another target.
11. Expose only the operations required by the parent slice: allowlisted key event, bounded property queries, and allowlisted app launch/stop if justified. Keep screenshots/logs/package inventory deferred and opt-in.
12. Test against fake ADB smart-socket/adbd endpoints and representative captured, redacted fixtures across Android TV, Google TV, and Fire TV; add container smoke tests and USB/TCP integration jobs.

### P3 — quality and release evidence

13. Add coverage gates, type checking, dependency vulnerability/license checks, container builds on every relevant PR, and protocol compatibility matrices. Keep scaffold contract tests, but do not count them as device-function evidence.
14. Produce user docs for prerequisites, Remote-vs-ADB selection, pairing/revocation, supported devices/functions, data updates, privacy, limitations, troubleshooting, removal, and credential cleanup.
15. Require a release checklist mapped to the safety invariants and an IQS-like rule file. Publish only after immutable image digest, SBOM, provenance attestation, test report, supported-device evidence, and rollback instructions exist.

## Verification notes

- Static source review found no package-specific release tags in the audited checkout.
- The declared tests could not be rerun in the audit shell without installing the package environments: the active PDM environment lacked `piphi_runtime_testkit_python` and the local packages. This does not change the source-level finding; CI configuration declares `pdm install --check` before `pdm run pytest`, but no CI run artifact was present in the repository.
- No files other than this report were changed.
