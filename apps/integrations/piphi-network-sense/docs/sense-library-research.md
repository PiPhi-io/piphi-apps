# Sense Energy Python library research

Research date: 2026-08-31.

## Project status

- Repository: [`scottbonline/sense`](https://github.com/scottbonline/sense), MIT licensed.
- Package: [`sense-energy`](https://pypi.org/project/sense-energy/), latest observed release `0.14.3` (2026-07-15).
- API status: unofficial and reverse engineered. Sense can change endpoints or authentication without a compatibility guarantee.
- Supported package classifiers currently list Python 3.9–3.11, while the project is pure Python and is used here on Python 3.12. CI must remain the compatibility gate.
- Primary dependencies include `aiohttp`, `websockets`, `msgpack`, `ciso8601`, `orjson`, `requests`, and `websocket-client`.

## Authentication and session lifecycle

`ASyncSenseable.authenticate(email, password)` calls `https://api.sense.com/apiservice/api/v1/authenticate`, establishes access and refresh tokens, selects `monitors[0]`, and fetches discovered devices. A `401` response can carry an MFA token; the caller must then invoke `validate_mfa(totp)`. Expired access tokens can be renewed with the refresh token.

The upstream README explicitly directs logging applications to create only one `Senseable` instance and reuse it. It says authentication should happen at most once every 15–20 minutes. The client also gives realtime calls a 60-second default rate limit. This is why the PiPhi runtime owns one client for its full process lifetime and why both Core and runtime enforce a single configuration.

The library supports loading previously saved access/refresh tokens, but this integration initially keeps tokens only inside the live client. A future encrypted-token persistence enhancement could reduce authentication after container restarts.

## Data surfaces

The async client provides:

- Realtime household power (`w`), solar power (`solar_w`), voltage legs, frequency, active devices, and per-device watts/on state.
- Daily, weekly, monthly, yearly, and billing-cycle consumption and solar production.
- Grid import/export, production percentage, solar-powered percentage, and net production when solar is configured.
- Monitor overview/status, firmware version, timezone, and discovered-device metadata.
- A websocket realtime stream using MessagePack, plus a newer REST realtime endpoint for monitor firmware `>= 1.64`.

This first implementation polls realtime via `update_realtime()` and only the daily trend scale. Fetching every trend scale on every cycle would create unnecessary cloud load.

## Extended read-only API

The community [Sense API Postman collection](https://github.com/Frankwin/SenseApiPostman/blob/master/Sense%20API.postman_collection.json) identifies device detail, Always On, unknown/Other, timeline, and trends endpoints. It has no response fixtures and is not treated as a runtime dependency or authoritative contract.

PiPhi isolates the useful read-only calls in `extended_api.py` and passes it the authenticated `sense-energy` API function. It therefore creates no second session and handles no credentials. Extended calls run only with the slower trend refresh, normalize a deliberately small set of fields, and retain the last good extended snapshot when an endpoint fails. Individual appliance detail lookup is implemented for future on-demand use, but polling uses the single device-list call rather than making one request per appliance.

Per-appliance historical trends remain deferred. The Postman example uses `device_id=usage`; it does not demonstrate that arbitrary detected device IDs work consistently. That capability should only be added after sanitized live response fixtures are available.

## Known limitations and risks

- Authentication always chooses the first monitor returned by the account. Multi-monitor account selection needs an upstream/API enhancement before PiPhi should expose it.
- The project has open reports involving websocket timeouts and a 2025 report that `async_realtime_stream` performs a runtime import that can block the event loop. The REST path is preferred when firmware supports it.
- Sense servers are known to limit concurrent realtime websocket streams; other community clients recommend closing streams promptly so the Sense mobile/web realtime view remains usable.
- Trend totals can move slightly backward due to Sense corrections/rounding, so they should not be assumed to be mathematically monotonic without tolerance.
- Detected devices may be merged, renamed, or rediscovered. The library filters hidden/merged devices and selects the newest duplicate smart-plug record. PiPhi uses the Sense device id as its stable runtime identity.
- There is no official public API/SLA, so failures must remain observable and retryable rather than being treated as permanent device loss.

## PiPhi mapping

| Sense value | PiPhi capability | Unit |
| --- | --- | --- |
| Active household power | `active_power_w` | W |
| Active solar power | `active_solar_power_w` | W |
| Voltage legs | `voltage_l1_v`, `voltage_l2_v` | V |
| Frequency | `frequency_hz` | Hz |
| Daily consumption/production | `daily_usage_kwh`, `daily_production_kwh` | kWh |
| Daily grid import/export | `daily_from_grid_kwh`, `daily_to_grid_kwh` | kWh |
| Detected device state | `device_power_w`, `device_on`, `device_daily_energy_kwh` | mixed |
| Always On load | `always_on_power_w` | W |
| Unknown/Other load | `other_power_w` | W |

The primary entity represents the monitor/account. Each detected Sense device is projected as a read-only child energy entity.

## Widget opportunities

The two included cards cover the strongest first-party experiences: household/solar flow and detected-device breakdown. Useful follow-ons are a 24-hour demand chart, solar self-consumption card, voltage-balance diagnostic, and configurable high-load alert card. Widgets should consume PiPhi capability state through the injected host; they should never call Sense directly or receive Sense credentials.
