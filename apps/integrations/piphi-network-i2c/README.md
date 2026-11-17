# piphi_network_i2c

PiPhi integration runtime for local I2C environmental sensors.

Software-supported typed drivers (physical paths remain experimental and unverified):

- BME680
- BME280
- BMP280
- Generic I2C address discovery

The production container accepts only `linux_i2c` on the exactly mapped `/dev/i2c-1` node, plus the explicitly enabled `mock` backend. MCP2221A, FT232H, AHT20, and PMSA003I routes are rejected because exact bridge/node selection cannot currently be guaranteed.

The HTTP contract uses `piphi-runtime-kit-python` for runtime auth context, typed config apply/sync, discovery responses, entities, health, diagnostics, and local events.

Direct Linux I2C reads prefer the Pimoroni libraries:

- `pimoroni/bme680-python`
- `pimoroni/bme280-python`

No raw-register endpoint, forced I2C takeover, kernel-driver unbind, or generic write API is exposed.

## Run

```bash
pdm install
pdm run piphi_network_i2c
```

The API listens on port `3674` by default.

## Container

The release target is `ghcr.io/piphi-io/i2c-integration:0.1.4`. It runs as a non-root user, drops all capabilities, enables no-new-privileges, and maps only `/dev/i2c-1` read/write. The service never changes host permissions.

The runtime **must** add the numeric host GID that owns `/dev/i2c-1` as a supplementary container group. Mapping a device does not grant the image's non-root UID access by itself. Startup intentionally fails closed when the node is not readable and writable by that identity.

```bash
I2C_DEVICE_GID="$(stat -c '%g' /dev/i2c-1)"
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  --device /dev/i2c-1:/dev/i2c-1:rw --group-add "$I2C_DEVICE_GID" \
  -p 127.0.0.1:3674:3674 \
  -v piphi-i2c-state:/.piphinetwork \
  ghcr.io/piphi-io/i2c-integration:0.1.4
```

Mock mode remains disabled in published images. For a container-only contract test, add
`-e PIPHI_ALLOW_MOCK_HARDWARE=true` and configure the `mock` adapter.

## Configuration

The `/ui-config` endpoint exposes these fields:

- `adapter`: `linux_i2c` or `mock`
- `adapter_id`: provisioned opaque ID (required for `linux_i2c`; do not use a serial or path)
- `bus`: exactly `1` for `linux_i2c`
- `address`: Optional hex or decimal address, such as `0x76`
- `sensor_model`: `auto`, `bme680`, `bme280`, `bmp280`, or `generic` for physical Linux I2C
- `poll_interval_seconds`: Suggested poll cadence

All sensor, board, kernel, architecture, and electrical compatibility claims are unverified. Mock/sysfs/device-node tests prove software behavior only; they do not qualify hardware. See `docs/software-qualification.md`.

The manifest omits a fixed host port and requires Core-allocated private ingress. The loopback publishing above is for local development only. The package passes the runtime auth context to outbound Core telemetry. It does not provide a standalone ingress-auth boundary, so the API must remain on Core's private container network and must not be published directly. Hardware reads are not automatically retried: each refresh cycle makes one bounded attempt, records classified stale/unavailable state on failure, and records recovery after a later successful cycle.

Mock readings are disabled by default. For local UI or SDK-contract development without hardware, set `PIPHI_ALLOW_MOCK_HARDWARE=true` and use `adapter=mock`.
