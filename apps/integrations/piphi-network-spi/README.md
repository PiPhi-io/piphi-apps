# piphi_network_spi

PiPhi integration runtime for local SPI environmental sensors.

Supported first-pass devices:

- BME680
- BME280
- BMP280

The runtime can target sensors connected to the host SPI bus or through an Adafruit FT232H USB-to-I2C/SPI bridge such as product 4471. Hardware reads require platform SPI support and the matching optional Python hardware packages.

The HTTP contract uses `piphi-runtime-kit-python` for runtime auth context, typed config apply/sync, discovery responses, entities, health, diagnostics, and local events.

The hardware extra includes the Pimoroni BME680/BME280 packages you pointed at for shared package availability, plus Adafruit CircuitPython BME drivers for SPI/FT232H access.

## Run

```bash
pdm install
pdm run piphi_network_spi
```

The API listens on port `3675` by default.

## Container

The release image includes the Linux SPI and FT232H hardware dependencies:

```bash
docker run --rm --privileged -p 3675:3675 piphinetwork/spi-integration:0.1.0
```

Direct SPI and USB bridge discovery require access to host device nodes. The
integration manifest therefore declares the Linux container as privileged, and
PiPhi should surface that elevated hardware-access requirement during install.
Mock hardware remains disabled in the release image.

## Configuration

- `adapter`: `linux_spi`, `ft232h`, or `mock`
- `bus`: Linux SPI bus number, usually `0`
- `chip_select`: SPI chip select number, usually `0`
- `sensor_model`: `auto`, `bme680`, `bme280`, or `bmp280`
- `baudrate`: SPI clock speed
- `poll_interval_seconds`: Suggested poll cadence

The default adapter is `linux_spi`. Mock readings are disabled by default. For local UI or SDK-contract development without hardware, set `PIPHI_ALLOW_MOCK_HARDWARE=true` and use `adapter=mock`.
