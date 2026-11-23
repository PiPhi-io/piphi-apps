# Awair Element physical qualification record

Use this template only for observations from a physical Awair Element. One record applies only to the exact container image digest, source revision, device hardware, firmware, and network conditions tested. Software tests, fake transports, and synthetic payloads are not hardware evidence.

The companion wizard is `scripts/run_hardware_qualification_wizard.sh`. It creates a private copy of this template and guides the operator; it does not manufacture observations or publish a result.

## Handling and publication boundary

- Keep the working record and raw artifacts private.
- Do not include credentials, tokens, account data, exact private addresses, full mDNS names, serial numbers, customer topology, unredacted logs, raw payloads, or packet captures in a public issue or pull request.
- Record redacted summaries below and retain raw evidence under the lab's access and retention policy.
- Completing this record does not authorize a merge, package or image publication, registry synchronization, or governance promotion.

## Identity and test conditions

- Tester/lab and contact:
- Qualification start/end (UTC):
- Container image reference:
- Resolved image digest (`sha256:...`):
- Source revision:
- Integration version:
- Host OS and architecture:
- Container engine and version:
- Awair model and hardware revision:
- Awair firmware version:
- Redacted device identity pattern (for example, `AWAIR-ELEM-[REDACTED]`):
- Redacted network topology, VLAN, firewall, DHCP, and mDNS boundaries:
- Clock synchronization source:
- Raw evidence location and retention policy:

## Preconditions

- [ ] The test device and network are non-production or approved for controlled interruption.
- [ ] The operator can safely restart/isolate the device and restore its original network state.
- [ ] Awair's supported user workflow was used to enable the Local API; credentials were not recorded.
- [ ] The qualification host and device share a trusted LAN that permits required mDNS and local HTTP traffic.
- [ ] No public ingress, transparent HTTP proxy, or cloud relay is used for device access.
- [ ] The exact image digest and source revision are recorded before testing.
- [ ] A fresh local-only runtime token is used and excluded from evidence.
- [ ] The expected polling interval, soak duration, and acceptance authority are defined.

Precondition result: **PASS / FAIL / BLOCKED**

Evidence summary and deviations:

## 1. Local API and mDNS identity

Record the observation method and a redacted summary. Keep exact names, addresses, and raw responses private.

- [ ] A physical device advertises a service under `_http._tcp.local.`, `_awair._tcp.local.`, or `_hap._tcp.local.`.
- [ ] The service's first label matches `AWAIR-ELEM-*` and consistently identifies the tested device.
- [ ] Every resolved destination is private or link-local; no public, loopback, multicast, unspecified, or reserved destination is accepted as the device address.
- [ ] Port 80 responds to `GET /air-data/latest` with HTTP 200 and no redirect.
- [ ] Local API disablement or an unreachable device prevents a successful discovery result.

Observed service types and identity pattern:

Address class and resolution method:

Result: **PASS / FAIL / BLOCKED**

Evidence summary:

## 2. Constrained runtime and authentication

- [ ] The image actually run resolves to the recorded digest.
- [ ] The runtime uses UID/GID `10001`, a read-only root/application filesystem, and only the required writable runtime storage.
- [ ] Privileged mode is disabled, capabilities are dropped, and `no-new-privileges` is enabled.
- [ ] Host networking or an equivalent lab configuration permits mDNS without exposing the service beyond the trusted LAN.
- [ ] `GET /health` succeeds without authentication.
- [ ] Protected routes reject a missing or incorrect `X-PiPhi-Integration-Token`.
- [ ] The reported integration identity/version matches the tested artifact.

Container engine inspection summary:

Result: **PASS / FAIL / BLOCKED**

Evidence summary:

## 3. Firmware payload and telemetry comparison

For each field returned by this firmware, record the field name, JSON type, unit, and whether it is accepted, renamed, or deliberately omitted. Do not place an unredacted raw payload in a shareable copy.

| Local API field | JSON type | Unit | Integration field | Outcome/notes |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

- [ ] Discovery returns the physical device only after both valid mDNS identity and a successful Local API probe.
- [ ] Applying the observed identity and address succeeds without changing device state.
- [ ] `/state` values match the direct `/air-data/latest` observation within timing/rounding expectations.
- [ ] Unknown fields are omitted rather than inferred, and missing fields do not become fabricated readings.
- [ ] Invalid types, non-finite values, or out-of-range values are rejected rather than published.
- [ ] The `refresh` command performs another read-only latest-data request and is idempotent.

Payload timestamp and comparison window:

Result: **PASS / FAIL / BLOCKED**

Evidence summary:

## 4. Restart, outage, and recovery

| Scenario | Start/end UTC | Expected behavior | Observed behavior | Recovery time | Result |
| --- | --- | --- | --- | --- | --- |
| Integration restart while device is online |  | Config/state restoration; polling resumes |  |  |  |
| Integration restart while device is offline |  | Config retained as unavailable/stale; bounded retry |  |  |  |
| Temporary LAN isolation |  | Last-good values marked stale/unavailable |  |  |  |
| Awair restart |  | Bounded failure and automatic recovery |  |  |  |
| DHCP address change with stable identity |  | Discovery observes new address; configured behavior is recorded truthfully |  |  |  |
| Original network state restored |  | Normal polling resumes |  |  |  |

- [ ] Failure state includes an appropriate category and increasing consecutive-failure count.
- [ ] Recovery clears stale/unavailable state and does not duplicate the device identity.
- [ ] No test assumes automatic migration to a changed address; any rediscovery or reconfiguration is documented.
- [ ] The device and network are restored to their original state.

Result: **PASS / FAIL / BLOCKED**

Evidence summary:

## 5. Sustained polling soak

Recommended minimum: 24 continuous hours unless the governing qualification policy requires longer. A shortened or interrupted run must be reported as such, not rounded up.

- Start/end UTC:
- Actual duration:
- Poll interval:
- Expected samples:
- Observed successful samples:
- Failed polls by category:
- Unavailability/restoration events:
- Integration restarts or test interruptions:
- CPU and memory start/peak/end:
- Device/API stability observations:

- [ ] The run uses only the physical device, not a fake transport or replayed payload.
- [ ] Polling remains bounded and does not accelerate during failure.
- [ ] No unbounded memory, task, connection, descriptor, log, or storage growth is observed.
- [ ] Successful recovery follows any incidental outage without operator fabrication of state.

Result: **PASS / FAIL / BLOCKED**

Evidence summary:

## 6. Privacy, egress, and read-only review

- [ ] Device-bound traffic remains local and consists only of `GET /air-data/latest`.
- [ ] No write/control HTTP method, historical endpoint, redirect target, proxy, or cloud device API is contacted.
- [ ] Logs and diagnostics omit tokens, configured addresses, full mDNS names, raw payloads, and account/customer data.
- [ ] Diagnostics expose aggregate runtime counts rather than device details.
- [ ] Runtime authentication is enabled; `PIPHI_ALLOW_UNAUTHENTICATED` is not set.
- [ ] Shared evidence has been manually reviewed and redacted.

Observation method (for example, isolated firewall counters or private packet capture):

Result: **PASS / FAIL / BLOCKED**

Evidence summary:

## Findings

| ID | Severity | Observation | Reproduction/evidence reference | Required action |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## Final decision

- Decision: **PASS / FAIL / BLOCKED**
- Decision authority:
- Decision date (UTC):
- Blockers or deviations:
- Required follow-up:
- Retest scope:

A `PASS` is limited to the exact identity and test conditions recorded above. Any image, source, hardware, firmware, security-boundary, or material network change requires review and may require requalification.
