# KNX/IP physical qualification record

Use this template when a community tester or lab can provide physical gateway access. One record applies only to the exact image digest, gateway firmware, and tested network conditions.

## Identity

- Tester and contact:
- Date and duration:
- PiPhi image tag:
- PiPhi image digest:
- Host architecture and operating system:
- Gateway manufacturer and model:
- Gateway firmware:
- KNX medium behind gateway:
- Network topology, including NAT/VLAN/firewall:
- ETS project or manually configured group-address source:

Do not attach secrets, keyrings, group-address exports, private IP addresses, or customer topology to a public issue. Redact logs before sharing.

## Preconditions

- [ ] Test installation is non-production or commands cannot create unsafe movement.
- [ ] Every writable datapoint has explicit global and per-datapoint opt-in.
- [ ] Group addresses and DPTs are independently checked against the project.
- [ ] KNX Secure and routing are disabled; this release does not support them.
- [ ] Rollback to the previous runtime image is available.

## Matrix

Record `pass`, `fail`, or `not tested`, plus timestamps and redacted evidence.

| Scenario | Result | Evidence/notes |
|---|---|---|
| Automatic connection |  |  |
| Explicit UDP tunnel |  |  |
| Explicit TCP tunnel, if gateway supports it |  |  |
| Discovery returns the expected gateway |  |  |
| DPT 1.001 initialization read |  |  |
| DPT 1.001 allowlisted write and independent feedback |  |  |
| DPT 5.001 initialization read |  |  |
| DPT 5.001 values at 0, representative midpoint, and 100 |  |  |
| DPT 9.001 initialization read and representative temperature |  |  |
| Runtime restart restores configuration and state becomes available |  |  |
| Gateway restart reconnects without duplicate writes |  |  |
| Network interruption reports unavailable and later reconnects |  |  |
| Pre-send queue rejection reports `not_sent` |  |  |
| Post-send timeout reports unknown outcome and is not retried |  |  |
| Sustained read/feedback traffic for at least 24 hours |  |  |
| Operational responses contain no host or group-address topology |  |  |

## Observations

- Connection/reconnection counts:
- Queue rejection count:
- Unknown write outcome count:
- Unexpected or duplicate telegrams:
- Memory/CPU trend during soak:
- User-visible failures:
- Redacted log or workflow links:

## Decision

- [ ] Pass for the exact bounded slice and hardware combination above.
- [ ] Conditional pass; limitations are documented below.
- [ ] Fail; do not promote rollout.

Limitations and follow-up issues:

Approval must not imply KNX product certification or compatibility beyond the tested gateway, firmware, transport modes, DPTs, and entity mappings.
