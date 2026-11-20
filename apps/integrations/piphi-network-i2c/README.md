# piphi_network_i2c

PiPhi integration runtime for an I2C environmental-sensor contract.

Mock-mode sensor shapes:

- BME680
- BME280
- BMP280
- Generic I2C address discovery

Version 0.1.6 accepts only the explicitly enabled `mock` backend. It requests no host devices. `linux_i2c`, MCP2221A, FT232H, and every other physical backend are rejected before preflight or I/O.

The HTTP contract uses `piphi-runtime-kit-python` for runtime auth context, typed config apply/sync, discovery responses, entities, health, diagnostics, and local events.

Experimental physical driver code may remain in the source for future work, but it is unreachable through the 0.1.6 configuration, discovery, and command contracts. No raw-register endpoint, forced I2C takeover, kernel-driver unbind, or generic write API is exposed.

## Run

```bash
pdm install
pdm run piphi_network_i2c
```

The API listens on port `3674` by default.

## Container

The release target is `ghcr.io/piphi-io/i2c-integration:0.1.6`. It runs as a non-root user, drops all capabilities, enables no-new-privileges, and requests no host device mapping or supplementary groups.

```bash
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  -e PIPHI_ALLOW_MOCK_HARDWARE=true \
  -e PIPHI_INTEGRATION_INTERNAL_TOKEN=replace-with-core-issued-token \
  -p 127.0.0.1:3674:3674 \
  -v piphi-i2c-state:/.piphinetwork \
  ghcr.io/piphi-io/i2c-integration:0.1.6
```

Mock mode remains disabled by default and must be explicitly enabled as shown for local contract testing.

## Configuration

The `/ui-config` endpoint exposes these fields:

- `adapter`: `mock` only
- `adapter_id`: optional opaque identity for deterministic mock targets
- `bus`: mock bus identity
- `address`: Optional hex or decimal address, such as `0x76`
- `sensor_model`: `auto`, `bme680`, `bme280`, `bmp280`, or `generic`
- `poll_interval_seconds`: Suggested poll cadence

Physical I2C is not deployable or qualified in this release. Core must first implement a governed dynamic supplementary device GID mechanism for an exact device mapping; app-local `group_add` or `device_gid` fields are unsupported and are not used. See `docs/software-qualification.md`.

The manifest omits a fixed host port and requires Core-allocated private ingress. The loopback publishing above is for local development only. `/health` is the sole public route; every operational route fails closed unless Core supplies `PIPHI_INTEGRATION_INTERNAL_TOKEN`. The package also passes runtime auth context to outbound Core telemetry. Hardware reads are not automatically retried: each refresh cycle makes one bounded attempt, records classified stale/unavailable state on failure, and records recovery after a later successful cycle.

Mock readings are disabled by default. For local UI or SDK-contract development without hardware, set `PIPHI_ALLOW_MOCK_HARDWARE=true` and use `adapter=mock`.
