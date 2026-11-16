# PiPhi Network WeatherXM

Experimental PiPhi integration runtime for WeatherXM stations using WeatherXM's
**unofficial and unsupported mobile-account API** (`/api/v1/me/devices`). This is
not the documented WeatherXM Pro API, has no provider compatibility guarantee,
and must not be described or published as a production/official integration.

The runtime maps WeatherXM station readings into PiPhi telemetry capabilities
such as temperature, humidity, wind, precipitation, pressure, UV index, solar
irradiance, and WeatherXM quality-of-data score. Configure either an existing
WeatherXM mobile-account bearer token or username/password credentials. An
explicit station ID is always required; the runtime never silently chooses the
first station in an account. Credentials remain in the private client and are
never copied into registry state, discovery results, diagnostics, or events.

Source observation timestamps must include a timezone and may be at most five
minutes in the future. Observations older than 30 minutes are retained for
diagnostic continuity but marked `stale=true` and `available=false`.
Production requests are pinned to `https://api.weatherxm.com/api/v1`; setup and
discovery do not accept endpoint overrides. Isolated tests may set
`PIPHI_ALLOW_TEST_BASE_URL=1` and use a loopback-only URL.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn piphi_network_weatherxm.main:app --reload --port 8090
pytest
python scripts/validate.py
```

The runtime listens on port `8090` by default and exposes the common PiPhi runtime route contract:

- `GET /health`
- `GET /diagnostics`
- `POST /discover`
- `POST /config`
- `POST /config/sync`
- `POST /deconfigure`
- `POST /deconfigure/{config_id}`
- `GET /state`
- `GET /contract`
- `GET /entities`
- `GET /events`
- `POST /events/device/{config_id}/example`
- `POST /telemetry/example`
- `POST /telemetry/device/{config_id}/example`
- `POST /command`

## Manifest

`manifest.json` is configured for the WeatherXM cloud API and the generated
release workflow publishes `docker.io/piphi/piphi-network-weatherxm`.

## Docker

```bash
docker build -t docker.io/piphi/piphi-network-weatherxm:0.1.0 .
docker run --rm -p 8090:8090 docker.io/piphi/piphi-network-weatherxm:0.1.0
```
