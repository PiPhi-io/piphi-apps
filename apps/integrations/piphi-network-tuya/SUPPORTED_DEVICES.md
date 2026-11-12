# Supported Devices Matrix

This document defines the **current supported-device matrix** for `piphi_network_tuya`.

It is intentionally conservative.

A device being listed here means the runtime has a defined compatibility path for that device family. It does **not** mean every Tuya device in that family is guaranteed to work without overrides.

## Support policy

### Tier 1 — First-class supported
A family is Tier 1 when the runtime provides all of the following:

- explicit `device_type`, `device_class`, and `entity_type`
- discovery normalization and `suggested_config` support
- family-specific normalized capabilities
- family-specific commands beyond raw `set_dp`
- automated route/runtime test coverage in this repo

### Tier 2 — Best-effort / generic support
A device is Tier 2 when it can usually still be discovered or manually configured, but the runtime may rely on:

- raw DPS inspection
- DP override fields
- generic `set_dp`
- manual configuration choices

### Tier 3 — Unsupported / unknown
A device is Tier 3 when there is no first-class runtime profile yet. These devices may still appear through discovery, but should be treated as exploratory integrations until a dedicated family profile is added.

## Validation levels

The matrix distinguishes between these validation levels:

- **Automated** — covered by this repo's pytest/runtime validation
- **Hardware pending** — intended support exists, but this repo does not claim broad real-device certification for all vendor/model variants
- **Model certified** — reserved for specific real devices that have been manually validated in production or lab hardware testing

At the time of writing, the families below are **Automated + Hardware pending** unless otherwise noted.

---

## Family matrix

### Expected setup experience legend

- **Works in common cases** — discovery and default DP assumptions are expected to work for many standard devices in that family
- **May need DP overrides** — discovery usually helps, but some real devices in the family often need manual DP remapping or scale changes
- **Advanced / experimental** — use only if you are comfortable inspecting raw DPS and using `set_dp`

| Family | `device_type` | Primary Tuya categories | Support tier | Expected setup experience | Discovery support | Normalized metrics | Family commands | Typical DP assumptions | Validation |
|---|---|---|---|---|---|---|---|---|---|
| Smart plug / outlet | `plug` | `cz`, `pc` | Tier 1 | Works in common cases | Category + DPS + name heuristics | `power`, `current_ma`, `power_w`, `voltage_v` | `turn_on`, `turn_off` | power on `1`; energy often on `18/19/20` or `4/5/6` | Automated, hardware pending |
| Wall switch / relay | `switch` | `kg` | Tier 1 | Works in common cases | Category + DPS + name heuristics | `power` | `turn_on`, `turn_off` | primary relay often on `1`; multiple boolean channels possible | Automated, hardware pending |
| Light / bulb / strip | `light` | `dj` | Tier 1 | Works in common cases | Category + DPS + name heuristics | `power`, `mode`, `brightness_percent`, `color_temp_percent`, `color_value` | `set_brightness`, `set_color_temp`, `set_color_rgb`, `set_mode` | power often `20`; mode `21`; brightness `22`; CT `23`; RGB `24` | Automated, hardware pending |
| Fan | `fan` | `fs` | Tier 1 | May need DP overrides | Category + DPS + name heuristics | `power`, `fan_speed_percent`, `oscillating`, `mode` | `set_fan_speed`, `set_oscillate`, `set_mode` | power `1`; speed usually `3/4/5`; mode often `4/5/6`; oscillate often `5/4/6` | Automated, hardware pending |
| Cover / blind / curtain | `cover` | `cl` | Tier 1 | May need DP overrides | Category + DPS + name heuristics | `position_percent`, `motion_state` | `open_cover`, `close_cover`, `stop_cover`, `set_cover_position` | control often `1`; position often `2/3/5` | Automated, hardware pending |
| Climate / thermostat | `climate` | `wk`, `wkf` | Tier 1 | May need DP overrides | Category + DPS + name heuristics | `power`, `mode`, `temperature_c`, `target_temperature_c` | `set_temperature`, `set_mode` | target often `16`; current often `24`; mode often `4`; scale often `1` or `10` | Automated, hardware pending |
| Humidifier / diffuser | `humidifier` | `jsq` | Tier 1 | May need DP overrides | Category + DPS + name heuristics | `power`, `mode`, `humidity_percent`, `target_humidity_percent` | `set_humidity`, `set_mode` | target often `103`; current often `104`; mode often `2`; scale often `1` or `10` | Automated, hardware pending |
| Air purifier | `air_purifier` | `kj` | Tier 1 | May need DP overrides | Category + DPS + name heuristics | `power`, `mode`, `fan_speed_percent`, `air_quality_index` | `set_fan_speed`, `set_mode` | speed often `4`; mode often `2`; AQI-like reading often `22`; scale often `1` | Automated, hardware pending |
| Unknown Tuya devices | `device` or inferred fallback | varies | Tier 2 | Advanced / experimental | Best-effort only | raw `dp_<number>` values | `refresh`, `turn_on`, `turn_off`, `set_dp` when applicable | no family guarantees | Automated generic path only |

---

## Per-family notes

### 1. Plug / switch families
These are the most predictable Tuya LAN devices in the current runtime.

Good fit:
- smart plugs
- smart outlets
- simple wall relays
- multi-gang switches where the primary switch DP can be chosen explicitly

Watch for:
- multi-channel devices where the desired power DP is not the first boolean DP
- vendor-specific energy DPS layouts

### 2. Light family
This family works best for Tuya bulbs and strips that match common bulb DPS layouts.

Good fit:
- white-only bulbs using common brightness DPs
- tunable white bulbs
- RGB/RGBW strips and bulbs using standard Tuya bulb DPS

Watch for:
- nonstandard proprietary scene/color encodings
- devices exposing only a subset of standard bulb functions

### 3. Fan family
This runtime assumes speed is a numeric or discrete DP that can be normalized into a percent.

Good fit:
- pedestal or desk fans
- ceiling fans with clear speed/mode/oscillation DPs

Watch for:
- vendor-specific string-based speed encodings
- devices where oscillation and mode DPs overlap in unusual ways

### 4. Cover family
This profile is aimed at curtains, shades, and blinds with open/close/stop semantics.

Good fit:
- curtain motors
- roller shades
- blind controllers with explicit control strings

Watch for:
- inverted position semantics
- devices that report travel values on a different scale

### 5. Climate family
This profile is intended for thermostats and climate-like Tuya controllers.

Good fit:
- thermostats using `16` target / `24` current conventions
- controllers with a simple mode string DP

Watch for:
- special-purpose HVAC controllers with richer mode/state models
- temperature values that require non-default scaling

### 6. Humidifier family
This works best for humidifiers and aroma diffusers exposing target/current humidity and optional mode.

Good fit:
- room humidifiers
- diffusers with mist/mode settings

Watch for:
- dehumidifier-like products using different semantics
- devices where humidity DPs represent percentages on unusual scales

### 7. Air purifier family
This profile is aimed at purifier devices with power, speed, mode, and AQI-like readings.

Good fit:
- HEPA purifiers
- room purifiers with auto/manual/sleep modes
- purifiers exposing a simple fan-level DP

Watch for:
- PM-only sensors that do not map cleanly to AQI semantics
- purifiers with very device-specific filter, ionizer, UV, child-lock, or alarm DPS

---

## What is not yet first-class supported

These areas should currently be treated as Tier 2 or Tier 3 unless proven otherwise:

- robot vacuums until a dedicated profile is added
- cameras
- door locks
- sirens / alarms
- irrigation controllers
- pet feeders
- EV chargers
- garage door operators with non-cover semantics
- appliances with very rich proprietary DPS models
- sensor-only products that do not behave like the families above

For these, the runtime may still:
- discover the device
- expose raw DPS values as `dp_<number>`
- allow manual `set_dp` operations

But that is **not** the same as first-class support.

---

## Production support statement

For production use, this runtime should be treated as:

- **Production-ready runtime implementation** for the Tier 1 families above
- **Best with known devices that match the listed DP assumptions**
- **Still requiring hardware validation per actual model/vendor variant before broad rollout**

The appendices below are the source of truth for model-level certification.

---

## Appendix A — Model certification rules

A specific device model should only be marked **Certified** when all of the following are true:

1. **Discovery works**
   - device appears through LAN discovery or can be manually configured with stable identity fields
   - inferred `device_type` is correct, or required overrides are documented

2. **Status reads are stable**
   - repeated polling returns valid DPS/state without crashing the runtime
   - normalized metrics map correctly for that family

3. **Core commands work**
   - power commands succeed where applicable
   - each family-specific command succeeds and re-reads correctly

4. **Failure modes are acceptable**
   - offline behavior is understandable
   - reconnect after temporary outage is verified
   - no persistent session corruption after failed command/status read

5. **Soak test is complete**
   - recommended minimum: 24h for basic certification
   - preferred: 72h for strong production confidence

6. **Overrides are documented**
   - any non-default DP mappings or scaling values must be recorded in the appendix table

A model that passes automation and ad hoc manual tests but has not completed soak validation should be marked **Validated** instead of **Certified**.

Status meanings:

- **Certified** — validated on real hardware and soak-tested
- **Validated** — validated on real hardware but soak test incomplete or limited
- **Investigating** — partial results exist, not yet reliable
- **Blocked** — known incompatibility or unresolved issue

---

## Appendix B — Certified and validated models

Fill this table only with real hardware results.

| Vendor | Model | Family | Tuya category | Protocol version | Required overrides | Discovery result | Command result | Soak duration | Status | Tested on | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

Example row:

| Example Vendor | Example Purifier 123 | `air_purifier` | `kj` | `3.3` | `purifier_speed_dp=4`, `purifier_aqi_dp=22` | auto-detected correctly | power, `set_mode`, `set_fan_speed` passed | 72h | Certified | 2026-07-07 | Stable LAN polling; AQI normalized correctly |

---

## Appendix C — Pending certification queue

Use this to track real devices that should be tested next.

| Priority | Family | Example device class | Expected category | Known risk areas | Status |
|---|---|---|---|---|---|
| P0 | `robot_vacuum` | robotic vacuums | unknown | usually need a dedicated entity and command model; often not plug/switch-like | queued |
| P1 | `plug` | plugs / outlets | `cz` / `pc` | energy DPS differences, multi-channel variants | ongoing |
| P1 | `light` | bulbs / strips | `dj` | nonstandard scene/color encodings | ongoing |
| P1 | `fan` | pedestal / ceiling fans | `fs` | vendor-specific speed and oscillation semantics | ongoing |
| P1 | `cover` | curtains / blinds / shades | `cl` | inverted position scales, travel semantics | ongoing |
| P1 | `climate` | thermostats / climate controllers | `wk` / `wkf` | scaling and mode differences | ongoing |
| P1 | `humidifier` | humidifiers / diffusers | `jsq` | humidity scale and mode differences | ongoing |
| P1 | `air_purifier` | air purifiers | `kj` | AQI/PM semantics, auxiliary feature DPS | ongoing |

---

## Appendix D — Certification test checklist

Use this checklist for each real device model.

### Identity and setup
- [ ] device IP / host captured
- [ ] Tuya device id captured
- [ ] local key captured
- [ ] protocol version confirmed
- [ ] duplicate-config protections verified
- [ ] product label / model photo archived
- [ ] vendor / manufacturer name recorded

### Discovery
- [ ] appears in `/discover`
- [ ] inferred `device_type` is correct
- [ ] `resolved_config_preview` is usable
- [ ] any required overrides recorded

### State and polling
- [ ] `/config` succeeds with strict validation enabled
- [ ] initial refresh returns connected state
- [ ] normalized metrics are correct
- [ ] raw DPS values are visible for debugging
- [ ] background polling remains stable

### Commands
- [ ] `refresh`
- [ ] `turn_on` / `turn_off` where applicable
- [ ] family-specific commands verified
- [ ] raw `set_dp` tested if needed
- [ ] post-command state refresh reflects change

### Failure behavior
- [ ] temporary offline test completed
- [ ] reconnect after outage verified
- [ ] invalid command/override failure behavior documented
- [ ] no repeated event storm during prolonged outage

### Soak test
- [ ] 24h completed
- [ ] 72h completed
- [ ] no memory/task/session stability issues observed

### Final classification
- [ ] marked `Validated`, `Certified`, `Investigating`, or `Blocked`
- [ ] appendix row added/updated
- [ ] family notes updated if new quirks were discovered


