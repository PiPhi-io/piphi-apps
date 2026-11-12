# PiPhi Network Kaiterra API

Python PiPhi integration runtime for Kaiterra air-quality devices using the
Kaiterra public API.

Kaiterra API docs: https://dev.kaiterra.com/

## Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn piphi_network_kaiterra_api.main:app --reload --port 8090
```

## Configuration

The PiPhi UI config endpoint asks for:

- `device_udid`: Kaiterra device UDID
- `api_key`: Kaiterra API key
- `base_url`: defaults to `https://api.kaiterra.com/v1`
- `alias`: optional display name
- `poll_interval_seconds`: optional polling cadence

Example:

```json
{
  "id": "kaiterra-sensedge",
  "device_udid": "00000000-0031-0101-0000-00007e57c0de",
  "alias": "Office Kaiterra",
  "base_url": "https://api.kaiterra.com/v1",
  "api_key": "change-me",
  "poll_interval_seconds": 60
}
```

The generated examples use Kaiterra's documented public test UDIDs. A real
deployment needs a Kaiterra API key for the target device.

## Capabilities

The integration maps Kaiterra parameters into PiPhi capabilities:

- `rtemp` -> `temperature_c`
- `rhumid` -> `humidity_percent`
- `rco2` -> `co2_ppm`
- `rpm1c` -> `pm1_ug_m3`
- `rpm25c` -> `pm25_ug_m3`
- `rpm10c` -> `pm10_ug_m3`
- `tvoc` / `rtvoc` -> `tvoc_ppb`
- `ro3` -> `ozone_ppb`

It also exposes `connected`, `api_latency_ms`, `refresh`, and `sync_cloud`.

## Runtime Contract

The integration exposes the standard PiPhi runtime contract:

- `GET /health`
- `GET /diagnostics`
- `POST /discover`
- `POST /config`
- `POST /config/sync`
- `POST /deconfigure`
- `GET /state`
- `GET /contract`
- `GET /entities`
- `GET /events`
- `POST /telemetry/example`
- `POST /command`

`refresh` refreshes one configured Kaiterra device. `sync_cloud` refreshes all
configured devices when no specific config is provided.

## Docker

```bash
docker build -t docker.io/piphi/piphi-network-kaiterra-api:0.1.0 .
docker run --rm -p 8090:8090 docker.io/piphi/piphi-network-kaiterra-api:0.1.0
```

## Release

This project includes `.github/workflows/release.yml`. For Docker Hub releases,
set these GitHub repository secrets:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

The manifest image is currently:

```text
docker.io/piphi/piphi-network-kaiterra-api:0.1.0
```

Before publishing, update `src/manifest.json.version` and the Docker image tag, then
run:

```bash
piphi-network-create publish-check -C .
```
