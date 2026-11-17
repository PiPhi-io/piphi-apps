# piphi_network_spi

PiPhi integration runtime for local SPI environmental sensors.

Protocol fixtures cover these model contracts:

- BME680
- BME280
- BMP280

Physical SPI backends are intentionally disabled. The former Linux and FT232H paths selected Blinka defaults rather than the configured exact bus/CS node, so accepting those settings would be misleading.

The HTTP contract uses `piphi-runtime-kit-python` for runtime auth context, typed config apply/sync, discovery responses, entities, health, diagnostics, and local events.

Only opt-in mock operation is advertised in 0.1.4. `linux_spi` and `ft232h` fail validation before hardware access until an exact-node backend is implemented and separately qualified.

## Run

```bash
pdm install
pdm run piphi_network_spi
```

The API listens on port `3675` by default.

## Container

The exact local image can be exercised without hardware:

```bash
docker run --rm --cap-drop ALL --security-opt no-new-privileges \
  -e PIPHI_ALLOW_MOCK_HARDWARE=true -p 3675:3675 \
  ghcr.io/piphi-io/spi-integration:0.1.4
```

The image runs non-root with no host device mapping or capabilities. Mock hardware remains disabled by default.

## Configuration

- `adapter`: `mock` only
- `bus`: Linux SPI bus number, usually `0`
- `chip_select`: SPI chip select number, usually `0`
- `sensor_model`: `auto`, `bme680`, `bme280`, or `bmp280`
- `baudrate`: SPI clock speed
- `poll_interval_seconds`: Suggested poll cadence

No sensor, board, USB bridge, kernel, architecture, or electrical path is physically qualified. Software fixtures do not establish hardware compatibility.
