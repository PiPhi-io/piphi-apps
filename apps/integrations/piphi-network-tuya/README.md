# piphi_network_tuya

A PiPhi Tuya runtime integration built with `piphi-runtime-kit-python`, tested with `piphi-runtime-testkit-python`, and powered by [`tinytuya`](https://github.com/jasonacox/tinytuya) for local Tuya LAN access.

## What this runtime supports

- FastAPI runtime shell with PiPhi-standard endpoints
- Local Tuya device configuration using `host`, `tuya_device_id`, and `local_key`
- `tinytuya`-based local device polling and command execution
- TinyTuya LAN discovery via `deviceScan()` through `/discover`
- Optional Tuya cloud-backed discovery inputs (`api_region`, `api_key`, `api_secret`, `api_device_id`)
- Discovery candidate normalization with Tuya category, DPS, and product-name heuristics
- Discovery-time capability/command hints for plugs, switches, lights, fans, covers, climate devices, humidifiers, and air purifiers
- Background polling scheduler per configured device
- Persistent TinyTuya device sessions for lower socket churn during polling and commands
- Separate plug, switch, light, fan, cover, climate, humidifier, and air purifier entity modeling
- Explicit support-tier documentation in `SUPPORTED_DEVICES.md`
- Runtime config sync through the shared PiPhi Python SDK
- Telemetry and event delivery back to PiPhi Core through the shared SDK
- Contract-focused pytest coverage using the shared PiPhi Python testkit
- Container deployment via `Dockerfile` and `docker-compose.runtime.yml`

## Local development

Create a local virtualenv and install against sibling PiPhi SDK repos:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ../piphi-runtime-kit-python -e ../piphi-runtime-testkit-python -e .[dev]
```

Run tests:

```bash
.venv/bin/pytest
```

Run the runtime:

```bash
.venv/bin/uvicorn piphi_network_tuya.main:app --host 0.0.0.0 --port 4191
```

## Main endpoints

- `GET /health`
- `GET /diagnostics`
- `POST /discover`
- `GET /ui-config`
- `POST /config`
- `POST /config/sync`
- `POST /deconfigure`
- `GET /entities`
- `GET /state`
- `POST /command`
- `GET /events`
- `POST /telemetry/example`
- `GET /manifest.json`
- `GET /manifest.static.json`
- `GET /behaviors.json`
- `GET /behaviors.static.json`

## Example config payload

```json
{
  "id": "tuya-plug-1",
  "config_id": "tuya-plug-1",
  "device_id": "tuya-plug-1",
  "container_id": "runtime-123",
  "integration_id": "piphi-network-tuya",
  "host": "192.168.1.50",
  "tuya_device_id": "bfxxxxxxxxxxxxxxxx",
  "local_key": "replace-with-local-key",
  "alias": "Desk Plug",
  "device_type": "plug",
  "version": "3.3",
  "switch": 1,
  "poll_interval_seconds": 60
}
```

## Supported devices matrix

See `SUPPORTED_DEVICES.md` for the explicit end-user support matrix, including:

- support tiers
- expected setup experience per family
- supported Tuya categories
- normalized metrics and commands per family
- common DP assumptions
- current validation status
- model-level certification appendices
- a per-device hardware certification checklist

This is the document to use when deciding whether a device family should be presented to end users as first-class supported, best-effort, or still unsupported.

## Device-specific commands

When `device_type` is `light`, the runtime also exposes these commands:

- `set_brightness`
- `set_color_temp`
- `set_color_rgb`
- `set_mode`

When `device_type` is `fan`, the runtime also exposes these commands:

- `set_fan_speed`
- `set_oscillate`
- `set_mode`

When `device_type` is `cover`, the runtime also exposes these commands:

- `open_cover`
- `close_cover`
- `stop_cover`
- `set_cover_position`

When `device_type` is `climate`, the runtime also exposes these commands:

- `set_temperature`
- `set_mode`

When `device_type` is `humidifier`, the runtime also exposes these commands:

- `set_humidity`
- `set_mode`

When `device_type` is `air_purifier`, the runtime also exposes these commands:

- `set_fan_speed`
- `set_mode`

## Polling behavior

- Config apply performs an immediate refresh and, by default, now fails fast if the initial device validation cannot connect successfully.
- A tracked background polling task is then started per configured device.
- Each task uses that config's `poll_interval_seconds` value.
- Polling applies a small jitter and failure backoff to reduce synchronized retries and repeated device hammering during outages.
- Polling and command execution reuse persistent TinyTuya device handles where possible.
- Repeated identical poll failures are event-throttled so prolonged outages do not flood downstream event consumers.
- Poll tasks and persistent sessions are cleaned up automatically when configs are removed and during runtime shutdown.

## TinyTuya notes

This runtime uses `tinytuya` in the same local-LAN style recommended by the project:

- local LAN discovery via `deviceScan()`
- targeted discovery filtering by `host` and `tuya_device_id`
- normalized discovery records with `device_type`, `device_class`, `entity_type`, `supported_capabilities`, `supported_commands`, and `resolved_config_preview`
- category-aware cloud discovery mapping for common Tuya families like plugs, wall switches, lights, fans, covers, thermostats/climate devices, humidifiers, and air purifiers
- `/ui-config` discovery-default metadata that explains how to map `/discover` results into `device_type`, `switch`, `version`, and family-specific DP override fields
- local status via device `status()`
- local commands like `turn_on()`, `turn_off()`, `set_value()`, and bulb helpers where available
- optional cloud discovery through TinyTuya `Cloud`

For real devices you will need:

- device IP / host
- Tuya device id
- Tuya local key
- correct protocol version (`3.3`, `3.4`, `3.5`, etc.)

## UI config discovery defaults

`GET /ui-config` now includes a `discovery_defaults` section to make discovery-to-config mapping explicit.
Each discovered device also includes a `resolved_config_preview` object that can be used as a nearly-ready config draft.

Notable mappings:

- `host` ← discovered `host`
- `tuya_device_id` ← discovered `tuya_device_id`
- `alias` ← discovered `alias`
- `device_type` ← `suggested_config.device_type`
- `switch` ← `suggested_config.switch`
- `version` ← `suggested_config.version` with fallback to discovered `version`

The same response also adds field descriptions and `ui:help` text for discovery-sensitive fields like `device_type`, `switch`, and `version`.
It now also exposes optional DP override fields for broader compatibility, including:

- `fan_speed_dp`
- `fan_speed_max`
- `fan_oscillate_dp`
- `fan_mode_dp`
- `cover_control_dp`
- `cover_position_dp`
- `climate_target_temp_dp`
- `climate_current_temp_dp`
- `climate_mode_dp`
- `climate_temp_scale`
- `humidifier_target_humidity_dp`
- `humidifier_current_humidity_dp`
- `humidifier_mode_dp`
- `humidifier_humidity_scale`
- `purifier_speed_dp`
- `purifier_speed_max`
- `purifier_mode_dp`
- `purifier_aqi_dp`
- `purifier_aqi_scale`

`resolved_config_preview` intentionally leaves `local_key` out and pairs with `missing_required_fields: ["local_key"]` so UIs can prompt only for the remaining required secret.

## UI metadata files

Sample PiPhi UI metadata files are included in:

- `piphi_network_tuya/src/manifest.json`
- `piphi_network_tuya/src/behaviors.json`

The runtime also serves these from the runtime itself:

- `GET /manifest.json` — dynamic manifest built from current code configuration
- `GET /manifest.static.json` — exact checked-in `src/manifest.json` file
- `GET /behaviors.json` — dynamic behavior metadata built from current code configuration
- `GET /behaviors.static.json` — exact checked-in `src/behaviors.json` file

## Container deployment

The checked-in container image is production-oriented:

- runs as a non-root `piphi` user
- uses `python -m piphi_network_tuya.main` so runtime port selection follows `PIPHI_RUNTIME_PORT`
- includes a Docker `HEALTHCHECK` against `/health`

Build the image:

```bash
docker build -t piphi-network-tuya:local .
```

Run with compose:

```bash
docker compose -f docker-compose.runtime.yml up --build
```

Validation and release helpers:

```bash
.venv/bin/python scripts/validate.py
.venv/bin/python scripts/release.py --bump patch --dry-run
.venv/bin/python scripts/release.py --bump prepatch --preid beta --dry-run
```

Important environment variables:

- `PIPHI_RUNTIME_PORT`
- `PIPHI_CONTAINER_ID`
- `PIPHI_INTEGRATION_INTERNAL_TOKEN`
- `PIPHI_LOG_LEVEL`
- `PIPHI_TUYA_IO_TIMEOUT_SECONDS`
- `PIPHI_TUYA_DISCOVERY_TIMEOUT_SECONDS`
- `PIPHI_TUYA_STRICT_CONFIG_VALIDATION`
- `PIPHI_TUYA_POLL_JITTER_SECONDS`
- `PIPHI_TUYA_POLL_FAILURE_BACKOFF_SECONDS`
- `PIPHI_TUYA_POLL_ERROR_EVENT_COOLDOWN_SECONDS`

Recommended production defaults are already shown in `docker-compose.runtime.yml`.

## Climate / thermostat notes

For many Tuya thermostats, discovery can now infer and prefill:

- `climate_target_temp_dp`
- `climate_current_temp_dp`
- `climate_mode_dp`
- `climate_temp_scale`

Common DP patterns are target temperature on `16` and current temperature on `24`, but devices vary. Some thermostats report whole-degree values and use `climate_temp_scale: 1`, while others report tenths of a degree and need `climate_temp_scale: 10`.

The runtime exposes both normalized climate metrics:

- `temperature_c`
- `target_temperature_c`

and the raw Tuya datapoints as `dp_<number>` so you can still inspect device-specific behavior when a thermostat does not match the common patterns.

## Humidifier notes

For many Tuya humidifiers and diffusers, discovery can now infer and prefill:

- `humidifier_target_humidity_dp`
- `humidifier_current_humidity_dp`
- `humidifier_mode_dp`
- `humidifier_humidity_scale`

Common DP patterns are target humidity on `103`, current humidity on `104`, and mode on `2`, but devices vary. Some report direct percent values and use `humidifier_humidity_scale: 1`, while others may need `humidifier_humidity_scale: 10`.

The runtime exposes both normalized humidifier metrics:

- `humidity_percent`
- `target_humidity_percent`

and the raw Tuya datapoints as `dp_<number>` so you can still inspect device-specific behavior when a humidifier does not match the common patterns.

## Air purifier notes

For many Tuya air purifiers, discovery can now infer and prefill:

- `purifier_speed_dp`
- `purifier_speed_max`
- `purifier_mode_dp`
- `purifier_aqi_dp`
- `purifier_aqi_scale`

Common DP patterns are speed on `4`, mode on `2`, and AQI-like readings on `22`, but devices vary. Some devices expose discrete speed levels like `1..3` while others use different ranges, so `purifier_speed_max` remains configurable.

The runtime exposes both normalized air purifier metrics:

- `fan_speed_percent`
- `air_quality_index`

and the raw Tuya datapoints as `dp_<number>` so you can still inspect device-specific behavior when an air purifier does not match the common patterns.

## Notes

- This runtime uses TinyTuya LAN-style control and is not guaranteed to support every Tuya datapoint family or every Tuya device model out of the box.
- Discovery gracefully falls back to a manual candidate when cloud credentials are not supplied.
- The runtime currently provides first-class profiles for plug/switch, light, fan, cover, climate, humidifier, and air purifier devices, while still exposing unknown DPS generically as `dp_<number>` metrics.
- `/state` redacts `local_key`, `api_key`, and `api_secret` from stored config payloads.
- `/health` and `/diagnostics` now expose operational summaries such as poll task counts, persistent session counts, and per-device refresh/failure status to help production monitoring.
- Config apply now rejects duplicate Tuya identities and, by default, rejects invalid initial device handshakes instead of accepting a broken config.
- `/discover` now validates cloud credentials as an all-or-nothing set and rejects invalid `scan_seconds` values early.
