# PiPhi I2C/SPI direct-hardware quality comparison

**Research cutoff:** 2026-11-16

**PiPhi revision audited:** [`e3eb2d3`](https://github.com/PiPhi-io/piphi-apps/tree/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e)

**Scope:** `piphi-network-i2c` 0.1.3 and `piphi-network-spi` 0.1.3, assessed as one privileged direct-hardware domain.

## Executive conclusion

These integrations are a useful **prototype-quality, sensor-specific slice**, not generic production I2C/SPI buses. I2C can scan and read a small environmental/particulate sensor set through Linux I2C, MCP2221A, or FT232H library paths. SPI can instantiate Adafruit BME280/BME680 drivers on Blinka's default SPI pins. Mock mode is correctly opt-in. Neither service exposes caller-selected registers, arbitrary payloads, raw `ioctl`s, or general raw transfers; preserving that narrow boundary is a material safety positive.

The current release boundary is nevertheless unsafe and in places untruthful:

1. both Linux containers are declared `privileged: true`, run as root, and receive no least-privilege device-node allowlist;
2. SPI accepts bus, chip-select, and baudrate as configuration and identity, but ignores bus and baudrate in hardware access, maps every nonzero chip-select to one fallback pin set, does not use its `spidev` dependency, and reports a device from configuration without probing it;
3. I2C scans every normal 7-bit address using SMBus Quick writes; address/model/adapter values are not server-side allowlisted or range-checked; Linux BME680 silently uses bus 1 regardless of configured bus; Linux Pimoroni handles are not closed;
4. both services perform synchronous hardware I/O inside async request/config paths with no per-adapter transaction serialization, operation deadline, bounded internal retry, hotplug watcher, ownership claim, or kernel-driver conflict policy;
5. tests are mocked contract/unit tests only, while CI is `legacy-static`, has no container-build, lint, type, dependency-audit, coverage, or real-hardware qualification gate.

**Release recommendation:** do not list either integration as production-ready, and do not claim configurable Linux SPI or generic I2C/SPI support, until P0 is closed and representative hardware qualification passes.

## Comparator model: absence is not a gap

At Home Assistant Core [`7682317`](https://github.com/home-assistant/core/tree/76823177f8d296dbbf017fe59627757b695e71d5/homeassistant/components), there is **no first-party generic local I2C or SPI integration** and no HA API for arbitrary register/transfer access. Therefore:

- absence of HA parity for I2C enumeration, SPI chip-select setup, MCP2221A/FT232H support, or raw bus operations is **not itself a PiPhi quality gap**;
- HA's `remote_rpi_gpio` is network GPIO through `gpiozero`/`pigpio`, explicitly `local_push` and `legacy`, not a direct I2C/SPI comparator ([manifest](https://github.com/home-assistant/core/blob/76823177f8d296dbbf017fe59627757b695e71d5/homeassistant/components/remote_rpi_gpio/manifest.json));
- HA's `homeassistant_hardware` integration is an analogical benchmark only. It concerns HA hardware/serial firmware management, but it does demonstrate USB matcher ownership, explicit in-progress ownership, executor isolation for blocking discovery, and coordinated exclusive flashing ([manifest](https://github.com/home-assistant/core/blob/76823177f8d296dbbf017fe59627757b695e71d5/homeassistant/components/homeassistant_hardware/manifest.json), [ownership helpers](https://github.com/home-assistant/core/blob/76823177f8d296dbbf017fe59627757b695e71d5/homeassistant/components/homeassistant_hardware/helpers.py#L64-L68), [exclusive flashing context](https://github.com/home-assistant/core/blob/76823177f8d296dbbf017fe59627757b695e71d5/homeassistant/components/homeassistant_hardware/firmware_config_flow.py#L229-L241)).

The authoritative behavioral comparators are therefore the Linux userspace APIs and the actual Python hardware libraries. Linux states that I2C adapter numbers are dynamically assigned and may change across boots; userspace selects an address and uses SMBus or `I2C_RDWR` transactions ([I2C userspace interface](https://github.com/torvalds/linux/blob/141b164bbe186423e295b139e40e8e2d11cf1341/Documentation/i2c/dev-interface.rst)). Linux SPI identifies a target as `/dev/spidevB.C`, requires the `spidev` driver to be bound, offers synchronous reads/writes/ioctls, bounds request size, provides no low-level acknowledgement, and warns that chip-select polarity mistakes can corrupt traffic to other devices ([SPI userspace API](https://github.com/torvalds/linux/blob/141b164bbe186423e295b139e40e8e2d11cf1341/Documentation/spi/spidev.rst)).

Home Assistant's Integration Quality Scale (IQS) is used below only as an **analogical checklist**, not an official score. PiPhi is not an HA Core integration, and neither PiPhi app has an HA `quality_scale.yaml`; HA defines cumulative Bronze–Platinum characteristics and special tiers for integrations outside the scale ([IQS](https://github.com/home-assistant/developers.home-assistant/blob/50b518898989b67bb76b69827f227aa6f0acd32a/docs/core/integration-quality-scale/index.md)).

Owning-library source observed at the cutoff was also checked for the paths PiPhi delegates: [`smbus2`](https://github.com/kplindegaard/smbus2/tree/7abe0d0d90166d213ce3853ebd8038e7da6465e8), [Pimoroni BME280](https://github.com/pimoroni/bme280-python/tree/5376dfd22c46bad33e1e4259268ee6dda64a0972), [Pimoroni BME680](https://github.com/pimoroni/bme680-python/tree/30fcb34efc2d19f60a63ece656b9059adb373150), [Blinka](https://github.com/adafruit/Adafruit_Blinka/tree/c7d9f6bff57236341cc6d4a9661f07e8799072ce), [Adafruit BusDevice](https://github.com/adafruit/Adafruit_CircuitPython_BusDevice/tree/686728c7b11eb0b7ffb62691b68ccead413e7cc5), [BME280](https://github.com/adafruit/Adafruit_CircuitPython_BME280/tree/252fa2ca61e4187eaad373e6765631cbbf1d8cc3), [BME680](https://github.com/adafruit/Adafruit_CircuitPython_BME680/tree/56c60ad8ffec0eebb191f13bf5923bab3bf14f98), [AHTx0](https://github.com/adafruit/Adafruit_CircuitPython_AHTx0/tree/3dd249f56957d1927dee6e6e31742039c6699cef), [PM25](https://github.com/adafruit/Adafruit_CircuitPython_PM25/tree/c9050a6fc9c94913af2db2ccc12331f065bc5be9), and [EasyMCP2221](https://github.com/electronicayciencia/EasyMCP2221/tree/7babffb025d9e006b2c448911b9bf9089b51cdb9). These are research baselines, **not** proof of the versions in a released PiPhi image: the hardware extra is not represented in either PDM lock's `default`/`dev` groups, and two requirements are floating Git URLs.

## Honest supported slices

### I2C

- Linux `smbus2` scan of addresses `0x03..0x77`; MCP2221A scan through `EasyMCP2221`; FT232H scan through Blinka ([implementation](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-i2c/src/piphi_network_i2c/sensors.py#L53-L128)).
- Sensor-specific reads for BME280/BMP280, BME680, AHT20 and PMSA003I, plus a “generic” presence/address-list result. “Generic” does **not** provide generic register reads or writes ([routing](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-i2c/src/piphi_network_i2c/sensors.py#L152-L188)).
- Explicit address selection and identities containing adapter/bus/address/model at the manifest-config layer ([manifest](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-i2c/src/manifest.json#L110-L135)).
- MCP2221A handles are closed on tested scan/BME paths; mock mode fails closed unless explicitly enabled.

This does **not** honestly support: arbitrary I2C devices; 10-bit addresses; PEC; caller-selected SMBus/I2C_RDWR operations; IRQ-driven devices; guaranteed bus selection for every sensor/backend; safe whole-bus inventory; or concurrent multi-device ownership.

### SPI

- BME280/BMP280 (through the BME280 driver) and BME680 reads through Adafruit CircuitPython drivers on the SPI bus and CS pin Blinka resolves for the running board ([implementation](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-spi/src/piphi_network_spi/sensors.py#L127-L185)).
- FT232H and Linux/default-board labels, diagnostics for module/node presence, and opt-in mock mode.

This does **not** honestly support: arbitrary SPI devices or transfers; a selected `/dev/spidevB.C`; configurable mode/bits-per-word/bit-order; the configured bus; the configured baudrate; chip-select values beyond the two hard-coded pin choices; discovery/probing; or direct use of `spidev`. The owning BME drivers accept a baudrate and use transaction locks through `SPIDevice`, but PiPhi does not pass its configured baudrate ([BME280 SPI constructor](https://github.com/adafruit/Adafruit_CircuitPython_BME280/blob/252fa2ca61e4187eaad373e6765631cbbf1d8cc3/adafruit_bme280/advanced.py), [BME680 SPI constructor](https://github.com/adafruit/Adafruit_CircuitPython_BME680/blob/56c60ad8ffec0eebb191f13bf5923bab3bf14f98/adafruit_bme680.py#L512-L571)).

## Evidence table

| Area | I2C evidence and assessment | SPI evidence and assessment | Authority / comparison |
|---|---|---|---|
| Device-file privilege | Manifest requests a root, fully privileged container rather than a selected `/dev/i2c-N` or USB node. | Same; no selected `/dev/spidevB.C` mapping. | **P0 common gap.** Linux exposes specific character devices; privileged mode grants a much larger host-hardware/capability boundary than either slice needs ([I2C manifest](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-i2c/src/manifest.json#L16-L37), [SPI manifest](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-spi/src/manifest.json#L16-L36)). Actual orchestrator device propagation was not executable here, so this is a declared privilege-boundary finding, not proof that every host node is reachable in every deployment. |
| Bus/target identity | Device ID includes bus/address, but entity ID omits adapter and bus; two buses can produce the same `i2c-{model}-{address}` entity ID. USB bridge “bus” is an index, not stable bridge serial/port identity. Model is incorrectly part of physical identity. | Device/entity IDs include bus/CS but omit adapter; model is part of identity. The stated bus may not be the bus Blinka opens. | **Gap.** Linux warns I2C bus numbers may change across boots; SPI's kernel identity is B.C. Persist stable adapter identity plus target address/CS separately from driver/model presentation. |
| Input allowlists and bounds | UI options exist, but runtime fields are free strings/ints. No adapter/model allowlist; no `0x03..0x77` or reserved-address validation; negative/10-bit/out-of-range values reach libraries. Poll interval only has a local minimum in normalization. | No runtime adapter/model allowlist; bus, CS, baudrate and poll interval have no upper bounds. Any nonzero CS maps to the same second pin candidate. | **P0.** Product UI choices are not a security boundary. Validate at the API model and again before I/O. |
| Discovery/probe safety | Full scan performs `write_quick` to 117 addresses, so discovery is active bus traffic, not passive enumeration. Addresses `0x76/0x77` are guessed as BME280 although BME680/BMP280 share them. MCP scan performs one-byte reads. | “Discovery” always returns one configured BME280/BME680-shaped object without opening or identifying hardware. Linux SPI has no acknowledgement for a nonexistent device. | **P0/P1.** I2C scan must be explicit and warned/bounded; identify supported chips by safe chip-ID transactions. SPI must not call configuration projection discovery. |
| Reads/writes/ioctls | PiPhi exposes no raw API. Owning libraries perform bounded sensor-register reads and initialization/config writes. `smbus2` wraps `I2C_SLAVE`, `I2C_FUNCS`, `I2C_SMBUS` and optionally `I2C_RDWR`; PiPhi uses only high-level methods ([smbus2 source](https://github.com/kplindegaard/smbus2/blob/7abe0d0d90166d213ce3853ebd8038e7da6465e8/smbus2/smbus2.py)). | PiPhi exposes no raw transfer API and does not issue `spidev` ioctls; Adafruit drivers perform sensor-register traffic through `SPIDevice`. | **Positive narrow boundary.** Do not add arbitrary register/raw-transfer endpoints to close a perceived HA parity gap; HA has no such comparator. |
| Transaction bounds | Scan count is fixed; library sensor reads are protocol-sized. No service deadline. AHT/BME operations may sleep/poll inside dependencies. | Library register transfers are small, and BME680 has a 3-second internal data-ready timeout; no service-level deadline. Linux notes spidev request-size limits and synchronous-only I/O. | **Partial.** Explicit operation deadlines and cancellation semantics remain required even when payload sizes are bounded. |
| Bus selection / owning libraries | Linux BME280 passes `SMBus(config.bus)` but never closes it. Linux BME680 constructs `BME680(address)`; Pimoroni then opens `SMBus(1)`, ignoring configured bus, and no close occurs ([PiPhi](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-i2c/src/piphi_network_i2c/sensors.py#L388-L407), [PiPhi BME680](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-i2c/src/piphi_network_i2c/sensors.py#L470-L487), [Pimoroni](https://github.com/pimoroni/bme680-python/blob/30fcb34efc2d19f60a63ece656b9059adb373150/bme680/__init__.py#L30-L43)). | `_spi_bus` has identical branches; bus is never passed. Constructors omit configured baudrate. `spidev` and Pimoroni libraries are installed/reported but unused for SPI. | **P0 claim/behavior mismatch.** Remove ineffective settings/dependencies or implement exact selected-node semantics with tests. |
| Concurrency | Blinka scan briefly uses its lock. There is no service-level per-adapter lock around scan/read/config/refresh, and sync calls execute in async handlers. Separate SMBus handles can interleave with each other or another process. | Adafruit `SPIDevice` locks an individual transfer, but PiPhi creates independent bus/CS objects per read and has no adapter/CS ownership registry or service-level sequencing. Sync reads run on the event loop. | **P0/P1.** Serialize per physical adapter (and SPI CS target), offload blocking I/O, bound queue depth, and reject duplicate/conflicting claims. |
| Retries and errors | Read errors become `connected=false`; command result is marked retryable, but no hardware retry/backoff/classification exists. Discovery converts missing dependencies to an empty list. | Same. SPI can report a configured device before later read failure. | **Gap.** Add small, error-class-specific bounded retry only where sensor protocol permits; never blindly retry mutating initialization. Distinguish not-present, permission, busy/driver-owned, timeout, unplug, unsupported ID, and malformed data. |
| Hotplug / lifecycle | No udev/sysfs watcher, bridge serial identity, reconnect/reopen state machine, or periodic poll task in app lifecycle; a later explicit refresh may reopen. | Same; no spidev bind/unbind or FT232H reconnect handling. | **Gap, not HA parity.** Hardware loss/reappearance needs explicit state transitions and bounded recovery. |
| Kernel-driver conflicts | No sysfs bound-driver check, ownership claim, or clear busy guidance. Default `smbus2` does not force an address, which is safer, but whole-bus scans still create traffic. | No verification that `spidev` is bound to the selected target; no conflict/ownership check with a kernel driver or another userspace client. | **P0.** Fail closed on driver ownership or duplicate PiPhi claims; never use I2C `FORCE` or unbind/rebind a kernel driver automatically. |
| Arbitrary raw exposure | None. Generic mode only returns address presence. | None. | **Good.** Keep sensor drivers and tightly typed operations as the trust boundary. If expert raw access is ever added, it should be a separate local-only tool, not an automation/API capability. |
| Diagnostics/privacy | Reports all `/dev/i2c-*` paths, dependency flags, active config IDs and event count; runtime version constant says 0.1.1 while package/manifest say 0.1.3. No adapter sysfs identity, permissions, driver owner, last success/error class, retry/latency counters, or redaction tests. | Equivalent; reports all `/dev/spidev*`, including host topology, but not selected node, mode/speed, driver binding, or actual bus. Version also says 0.1.1. | **Below supportable.** Device paths and user config IDs can disclose host topology/user naming in exported diagnostics. Add explicit redaction and opt-in full-path handling. |
| CI / release | 26 mocked tests pass. CI runs lock check and pytest only; `build_container=false`; hardware extra is absent from the lock groups, while Docker installs live VCS dependencies. | 18 mocked tests pass; same CI limitations. `spidev` behavior has no test because it is unused. | **P1.** Release workflow can build multi-arch OCI, SBOM, provenance and attestations, but per-app qualification does not build these containers first ([app metadata](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/apps/integrations/piphi-network-i2c/piphi-app.json#L14-L39), [release workflow](https://github.com/PiPhi-io/piphi-apps/blob/e3eb2d3084645ab2cf4f80e925368b28f6fdb27e/.github/workflows/release-app.yml#L138-L157)). Base images and VCS requirements are not immutable. |
| Real-hardware qualification | No checked-in matrix or test marker for Linux I2C, MCP2221A, FT232H, any listed sensor, unplug/replug, collision, or non-default bus. | No matrix/test for Linux SPI, FT232H, CS0/CS1, non-default bus/speed, BME models, mode, unplug/replug, or concurrent targets. | **P0 before claims / P1 gate.** Mock success is not electrical, kernel, timing, architecture, or board qualification. |

## Separate I2C findings

1. **Scanning is a write operation.** `SMBus.write_quick()` is issued across the normal address range. It is bounded in count but may alter/confuse devices that interpret quick commands; scanning must be an explicit maintenance operation, not automatic setup on an unknown shared bus.
2. **Address is not identity enough.** Address `0x76/0x77` cannot distinguish BME280, BMP280, or BME680. The current guess chooses BME280 without reading chip ID. The address must be combined with stable adapter identity and verified device ID; model changes must not create a new physical device.
3. **Configured bus can be false.** Pimoroni BME680 opens bus 1 internally. Adafruit fallback uses `board.I2C()`, also not necessarily `config.bus`. The returned state nevertheless echoes the configured bus.
4. **Handle lifecycle is inconsistent.** MCP2221A paths close handles in `finally`; Linux BME280 and internally opened Linux BME680 handles are not closed. Repeated refresh can leak file descriptors/resources.
5. **No arbitrary-register API is a feature.** Supported sensor libraries do write reset/config/heater registers as part of normal reads, so “read-only sensor” does not mean electrically read-only. Those writes are protocol-specific and should remain allowlisted by driver/model.

## Separate SPI findings

1. **The Linux SPI claim is not implemented as configured.** There is no `spidev.SpiDev().open(bus, chip_select)`, no selected `/dev/spidevB.C`, and no SPI ioctl setup. `board.SCK/MOSI/MISO` chooses Blinka's default board bus.
2. **Baudrate is dead configuration.** The owning BME constructors support it, but PiPhi does not pass it. Configuration, UI, and state imply control that does not exist.
3. **Chip-select bounds are unsafe/misleading.** Zero maps to CE0/C0 (or D5 fallback); every other integer maps to CE1/C1 (or D6). Thus CS2 and CS999 share physical behavior but different identities.
4. **Discovery is fabricated.** It projects one device from input and defaults `auto` to BME280. SPI has no address/ack scan, but a safe supported-device probe can read and validate that sensor's chip ID before import.
5. **Installed dependencies overstate support.** `spidev`, Pimoroni BME280, and Pimoroni BME680 are in the SPI hardware extra/diagnostics yet no SPI path imports them. Remove them or implement and qualify the intended backend.

## Analogical Home Assistant IQS assessment

| Tier | Analogical result | Why |
|---|---|---|
| Bronze | **Not demonstrated** | UI metadata, ownership metadata, docs, typed HTTP models and tests exist, but setup does not validate the physical target; SPI discovery is synthetic; configured SPI behavior is ignored; privileged deployment is not least-privilege; version reporting is inconsistent. |
| Silver | **Not demonstrated** | Failed reads become unavailable and command idempotency is tested, but there is no automatic hotplug recovery, bounded hardware retry/backoff, conflict repair, actionable error taxonomy, coverage gate, or production logging/diagnostic evidence. |
| Gold | **Not demonstrated** | Discovery/diagnostics exist nominally, but stable physical identity, reconfiguration/repair, safe stale-device handling, privacy-safe downloadable diagnostics, hardware qualification, supported-device documentation, and release validation are incomplete. |
| Platinum | **Not demonstrated** | Blocking hardware I/O runs in async handlers; no per-bus coordinator/serialization, shared connection lifecycle, strict typing gate, performance/soak testing, or measured resource efficiency exists. |

Positive foundations worth preserving are the opt-in mock gate, narrow sensor-specific command surface, bounded fixed sensor drivers, typed entities, idempotent refresh action, failure-to-unavailable behavior, MCP handle cleanup in covered paths, and supply-chain evidence capability in the shared release workflow.

## Hardware safety invariants

These must be product constraints and executable tests:

1. **Least privilege by exact node.** Run non-root and non-privileged; map only the selected `/dev/i2c-N`, `/dev/spidevB.C`, or exact USB bridge node, with only required groups/capabilities. No broad `/dev`, GPIO-memory, sysfs-write, or host capability access.
2. **Stable adapter plus target identity.** Resolve I2C adapter/USB bridge by stable sysfs/USB identity and address; resolve SPI by stable controller plus CS. Bus numbering is routing metadata, model is verified presentation, and alias is user metadata.
3. **Validate before I/O.** Adapter, model, address, bus, CS, speed and poll interval are allowlisted/range-checked server-side. Unsupported combinations fail before opening hardware.
4. **One owner, one serialized transaction stream.** Exactly one PiPhi owner per physical target and one coordinator lock per shared adapter. Duplicate configs and conflicts with kernel/other userspace owners fail closed.
5. **No forced takeover.** Never use `I2C_SLAVE_FORCE`, silently unbind a kernel driver, rewrite device tree/overlays, or change chip-select polarity. Repair guidance is explicit and user-confirmed outside the integration.
6. **Discovery is truthful and non-destructive by default.** SPI configuration projection is not discovery. Sensor import requires expected chip ID/protocol evidence. Whole-bus I2C probing is explicit, warned and never concurrent with normal reads.
7. **Configuration equals electrical behavior.** Reported bus, address/CS, mode and speed are the values actually opened/configured. Unsupported settings are rejected, not ignored or coerced.
8. **Bounded operations.** Every scan/read/init has payload, transaction-count and wall-clock bounds; blocking calls are off the event loop; cancellation leaves CS deasserted, bus unlocked and handles closed.
9. **Retries are protocol-aware.** Retry only classified transient read failures, with a small bound/backoff/jitter. Do not blindly retry reset, heater/config writes, scans, or unknown partial transactions.
10. **Hotplug is a state transition.** Unplug marks unavailable once, closes handles and stops traffic; reappearance is verified by stable identity and chip ID before bounded recovery. No log/event storm.
11. **Raw access stays unavailable.** No caller-selected register, address, mode, ioctl, payload, transfer sequence, kernel-driver bind/unbind, or sysfs path through HTTP/automation. New device support is a reviewed typed driver.
12. **Shared-bus compatibility is declared.** A qualified sensor/backend records all initialization/config writes, maximum speed/mode, clock stretching/PEC needs, bus occupancy, and known conflicts.
13. **Diagnostics are private and actionable.** Default exports redact aliases, config IDs, full device paths/serials and topology while retaining hashed stable identity, selected backend, versions, permission/driver status, last success/error class, latency and bounded counters.
14. **Claims follow hardware evidence.** Each advertised adapter/sensor/architecture/backend combination has a released-image qualification record including cold boot, repeated reads, unplug/replug, permission denial, duplicate claim, wrong model/address/CS, concurrency and 24-hour soak.

## Prioritized work

### P0 — release blockers

1. Replace privileged/root containers with non-root, exact-device mapping and documented group permissions for the selected Linux node or USB bridge. Add negative tests proving unrelated devices/sysfs and host capabilities are unavailable.
2. Make hardware configuration truthful. For SPI either implement a selected `spidevB.C`/qualified Blinka backend with exact bus, CS and baudrate semantics, or remove those settings and narrow the claim. Reject CS outside the supported set. For I2C pass the selected bus to every backend or reject unsupported combinations.
3. Add strict server-side adapter/model/range/combination validation, stable adapter identity, duplicate target claims, and kernel-driver/in-use conflict detection. Never force or auto-unbind.
4. Replace synthetic/guess discovery: explicit warned I2C scan plus chip-ID verification; SPI target verification by supported-driver chip ID. Do not import unverifiable devices.
5. Add per-adapter serialization, blocking-I/O executor isolation, operation deadlines, guaranteed close/deinit, bounded queueing and classified failure states. Fix Linux I2C handle leaks.
6. Qualify at least one exact released path before advertising it: released OCI digest, host OS/kernel/board, architecture, adapter/bridge, sensor revision, permissions, cold boot, sustained polling, concurrent API calls, wrong target, conflict, unplug/replug and soak. Until then label all physical paths experimental.

### P1 — reliable supported product

1. Implement bounded protocol-aware retries/backoff and hotplug recovery with stable-identity revalidation, no event storms and repair guidance for permission/busy/driver-owned/wrong-chip cases.
2. Correct identity/entity collisions across adapters/buses; remove model from physical identity; make aliases non-identifying; define migration when bus routing changes but stable USB/sysfs identity does not.
3. Add privacy-safe downloadable diagnostics and redaction regression tests. Include package/runtime/library versions, selected backend/node (redacted), effective electrical settings, driver/permission/ownership state, last success/error and bounded latency/retry counters. Align runtime version 0.1.1 with release 0.1.3.
4. Upgrade CI from `legacy-static`: Ruff, strict typing, dependency audit, coverage threshold, wheel/sdist checks, AMD64/ARM64 OCI builds, container non-root/device-boundary tests, manifest/runtime version consistency and hardware-extra import smoke tests.
5. Make builds reproducible: pin base images by digest; lock hardware extras; replace floating Git VCS dependencies with immutable commits/releases and hashes; gate release on the exact image later qualified on hardware.
6. Remove duplicate nested source/package trees and unused dependencies, or prove packaging intentionally excludes them; add a test that imports the same implementation used by the release entrypoint.

### P2 — quality and completeness

1. Expand only through typed, reviewed sensor drivers with explicit register/write behavior and qualification; do not create a generic raw bus endpoint.
2. Add backend capability reporting (I2C functionality/PEC/10-bit only if supported; SPI effective mode/speed/bits-per-word) and compatibility checks before setup.
3. Add calibration/offset options, measurement-quality metadata and sensor-specific data-validity/range checks without conflating transport success with plausible measurements.
4. Add deterministic fault-injection tests for NACK, short/invalid reads, timeout, bus busy, permission denied, disappearing nodes, wrong chip IDs, dependency absence, queue saturation and cancellation during each operation phase.
5. Publish a versioned hardware support matrix and removal/recovery/troubleshooting documentation, clearly separating Linux I2C, MCP2221A, FT232H, Linux spidev and Blinka board-pin paths.

## Validation performed and limits

Executed from the audited checkout on 2026-11-16:

- I2C: `PDM_IGNORE_ACTIVE_VENV=1 pdm install --check` succeeded; `pdm run pytest -q` **26 passed** (one upstream Starlette/httpx deprecation warning).
- SPI: the same install check succeeded; `pdm run pytest -q` **18 passed** (same warning).
- `python3 scripts/run_app_ci.py` for each app succeeded but explicitly reported **“legacy-static metadata validation only.”**
- Static inspection covered source, duplicated nested source trees, tests, manifests, Dockerfiles, dependency declarations/locks, shared CI/release workflows, Linux I2C/SPI userspace documentation, current HA Core, IQS guidance, and the owning `smbus2`, Pimoroni and Adafruit driver behavior cited above.

No `/dev/i2c-*` or `/dev/spidev*` device, MCP2221A/FT232H bridge, listed sensor, GPIO header, ARM host, or privileged runtime deployment was available. Consequently this audit did **not** validate electrical behavior, actual Docker device visibility, permissions/groups, kernel driver binding, bus contention, scan side effects, effective SPI mode/speed, retries, hotplug, long-run handle use, ARM wheels/images, timing, or real-hardware recovery. Existing tests monkeypatch hardware libraries and do not close that evidence gap. No container build or vulnerability audit was run because the declared app CI disables container builds and the requested deliverable is documentation only.
