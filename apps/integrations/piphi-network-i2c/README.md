# piphi_network_i2c

PiPhi integration runtime for local I2C environmental sensors.

Supported first-pass devices:

- BME680
- BME280
- BMP280
- AHT20 / AHTx0
- PMSA003I / PM2.5 particulate sensor
- Generic I2C address discovery

The runtime is designed for sensors connected directly to the host I2C bus or through USB bridges such as the Adafruit MCP2221A breakout (product 4471) and FT232H boards. Direct hardware reads require the matching optional Python hardware packages to be installed on the runtime host.

The HTTP contract uses `piphi-runtime-kit-python` for runtime auth context, typed config apply/sync, discovery responses, entities, health, diagnostics, and local events.

Direct Linux I2C reads prefer the Pimoroni libraries:

- `pimoroni/bme680-python`
- `pimoroni/bme280-python`

AHT20 reads use `adafruit/Adafruit_CircuitPython_AHTx0`. PMSA003I particulate reads use `adafruit/Adafruit_CircuitPython_PM25`. MCP2221A bridge discovery plus BME280 and BME680 reads now prefer `EasyMCP2221` through its SMBus-compatible interface. FT232H bridge reads use the Adafruit Blinka/CircuitPython stack, and MCP2221A can still fall back to Blinka-based sensor access when the SMBus path is unavailable.

## Run

```bash
pdm install
pdm run piphi_network_i2c
```

The API listens on port `3674` by default.

## Container

The release workflow publishes `piphinetwork/i2c-integration` for `linux/amd64` and `linux/arm64`.
I2C adapters expose host device nodes dynamically, so the current manifest runs this hardware
integration as a privileged container. Only install it on a trusted PiPhi host.

```bash
docker run --rm --privileged \
  -p 3674:3674 \
  -v piphi-i2c-state:/.piphinetwork \
  piphinetwork/i2c-integration:0.1.0
```

Mock mode remains disabled in published images. For a container-only contract test, add
`-e PIPHI_ALLOW_MOCK_HARDWARE=true` and configure the `mock` adapter.

## Configuration

The `/ui-config` endpoint exposes these fields:

- `adapter`: `linux_i2c`, `mcp2221a`, `ft232h`, or `mock`
- `bus`: Linux I2C bus number, usually `1`
- `address`: Optional hex or decimal address, such as `0x76`
- `sensor_model`: `auto`, `bme680`, `bme280`, `bmp280`, `aht20`, `pmsa003i`, or `generic`
- `poll_interval_seconds`: Suggested poll cadence

The default adapter is `linux_i2c`. For MCP2221A usage install `EasyMCP2221` and use `adapter=mcp2221a`. The `bus` field maps to the MCP2221A device index and is usually `1`. For AHT20 or Blinka fallback access on MCP2221A, set `BLINKA_MCP2221=1`. For FT232H usage set `BLINKA_FT232H=1` and use `adapter=ft232h`.

Mock readings are disabled by default. For local UI or SDK-contract development without hardware, set `PIPHI_ALLOW_MOCK_HARDWARE=true` and use `adapter=mock`.
