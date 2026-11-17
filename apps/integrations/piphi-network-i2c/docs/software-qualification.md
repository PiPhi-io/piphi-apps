# Software qualification and residual limits

Version 0.1.4 is qualified only with mocked sysfs/device nodes, fake adapters, protocol fixtures, negative permission and ownership tests, and exact local container images.

## Software-enforced invariants

- The container runs non-root, non-privileged, drops all capabilities, and maps only `/dev/i2c-1`. The manifest requires Core to resolve that node's numeric GID through `container.group_add`; denied access fails preflight before discovery or sensor I/O.
- `linux_i2c` requires bus 1, an explicit non-reserved address, and a provisioned opaque adapter ID.
- Canonical backend/node/bus/address claims ignore caller display IDs. Claims are reserved atomically before I/O, while all addresses and scans on the exact adapter/bus share one operation lock, bounded queue, and deadline.
- Kernel-driver ownership fails closed. The runtime never requests `I2C_SLAVE_FORCE`, writes bind/unbind controls, or changes host permissions.
- Handles close in `finally`; blocking calls run outside the event loop; diagnostics expose hashes/counts/classes rather than paths, aliases, serials, or config IDs.
- SPI physical backends are disabled because the old Blinka implementation could not honor exact bus/CS selection.
- Outbound Core telemetry receives the runtime auth context. Inbound HTTP authorization is supplied by Core's private runtime network, not by this package; direct host/public exposure is unsupported.
- Refresh reads are attempted once rather than blindly retried. Offline failures become classified stale/unavailable snapshots, and a later successful read records recovery.

## Not qualified

No sensor, breakout board, USB bridge, GPIO header, host board, kernel/driver, Linux distribution, container architecture, clock rate, voltage, wiring, electrical behavior, hotplug timing, or sustained polling path has been physically tested or qualified. Linux I2C support is experimental until an immutable released image completes a documented hardware matrix. SPI remains mock-only.

Timeouts cannot forcibly cancel a Python dependency already executing in a worker thread; the queue slot remains occupied until that call unwinds and its `finally` cleanup runs. Cross-process ownership beyond kernel-driver checks is not detectable by this process.
