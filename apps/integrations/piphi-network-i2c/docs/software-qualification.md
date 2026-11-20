# Software qualification and residual limits

Version 0.1.6 is qualified only for its authenticated opt-in mock contract, protocol fixtures, negative backend tests, and exact local container images.

## Software-enforced invariants

- The container runs non-root and non-privileged, drops all capabilities, and requests no host devices or supplementary groups.
- Configuration, discovery, commands, diagnostics, and manifest metadata expose only `mock`; physical adapters are rejected before preflight or I/O.
- Canonical mock backend/bus/address claims ignore caller display IDs. Claims are reserved atomically before mock reads, while all mock addresses and scans on one bus share one operation lock, bounded queue, and deadline.
- Kernel-driver ownership fails closed. The runtime never requests `I2C_SLAVE_FORCE`, writes bind/unbind controls, or changes host permissions.
- Handles close in `finally`; blocking calls run outside the event loop; diagnostics expose hashes/counts/classes rather than paths, aliases, serials, or config IDs.
- SPI physical backends are disabled because the old Blinka implementation could not honor exact bus/CS selection.
- Outbound Core telemetry receives the runtime auth context. Inbound HTTP authorization is supplied by Core's private runtime network, not by this package; direct host/public exposure is unsupported.
- Refresh reads are attempted once rather than blindly retried. Offline failures become classified stale/unavailable snapshots, and a later successful read records recovery.

## Not qualified

No physical I2C path is deployable or qualified. Before one can be advertised, Core must implement and govern dynamic supplementary device GID resolution for an exact device mapping; the shared runtime/orchestrator does not support that prerequisite in 0.1.6. App-local `group_add` or `device_gid` schema is explicitly not used. Physical hardware qualification and a documented matrix would still be required after Core support exists. SPI also remains mock-only.

Timeouts cannot forcibly cancel a Python dependency already executing in a worker thread; the queue slot remains occupied until that call unwinds and its `finally` cleanup runs. Cross-process ownership beyond kernel-driver checks is not detectable by this process.
