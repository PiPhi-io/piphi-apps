# PiPhi Network WeatherXM

PiPhi integration runtime for WeatherXM stations using the WeatherXM public API.

The runtime maps WeatherXM station readings into PiPhi telemetry capabilities
such as temperature, humidity, wind, precipitation, pressure, UV index, solar
irradiance, and WeatherXM quality-of-data score. Configure either an existing
WeatherXM bearer token or username/password credentials.

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
