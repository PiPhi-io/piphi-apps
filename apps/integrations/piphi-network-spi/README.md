# piphi_network_spi

PiPhi integration runtime for local SPI environmental sensors.

Protocol fixtures cover these model contracts:

- BME680
- BME280
- BMP280

Physical SPI backends are intentionally disabled. The former Linux and FT232H paths selected Blinka defaults rather than exact physical targets, so transport settings are not accepted in the mock-only public contract.

The HTTP contract uses `piphi-runtime-kit-python` for runtime auth context, typed config apply/sync, discovery responses, entities, health, diagnostics, and local events.

Only opt-in mock operation is advertised in 0.1.6. `linux_spi` and `ft232h` fail validation before hardware access until an exact-node backend is implemented and separately qualified.

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
  -e PIPHI_ALLOW_MOCK_HARDWARE=true \
  -e PIPHI_INTEGRATION_INTERNAL_TOKEN=replace-with-core-issued-token \
  -p 127.0.0.1:3675:3675 \
  ghcr.io/piphi-io/spi-integration:0.1.6
```

The image runs non-root with no host device mapping or capabilities. Mock hardware remains disabled by default.

The manifest omits a fixed host port and requires Core-allocated private ingress. The loopback publishing above is for local development only. `/health` is the sole public route; every operational route fails closed unless Core supplies `PIPHI_INTEGRATION_INTERNAL_TOKEN`. The package also passes runtime auth context to outbound Core telemetry. Hardware refreshes are not blindly retried: each cycle makes one bounded attempt, records classified stale/unavailable state on failure, and records recovery after a later successful cycle.

## Configuration

- `adapter`: `mock` only
- `sensor_model`: `auto`, `bme680`, `bme280`, or `bmp280`
- `poll_interval_seconds`: Suggested poll cadence

`bus`, `chip_select`, and `baudrate` are rejected caller fields in 0.1.6. Mock identity does not represent a physical bus or chip-select target. Experimental physical helper code remains unreachable until an exact backend is implemented and qualified.

No sensor, board, USB bridge, kernel, architecture, or electrical path is physically qualified. Software fixtures do not establish hardware compatibility.
