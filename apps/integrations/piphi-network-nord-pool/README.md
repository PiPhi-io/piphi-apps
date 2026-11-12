# Piphi Network Nord Pool

PiPhi runtime for Nord Pool day-ahead prices. It reads the published current
and next interval for a configured bidding zone and reports the price in the
selected currency per kWh. It does not trade or change tariffs.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_nord_pool.main:app --reload --port 4214
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4214` by default and exposes the common PiPhi runtime route contract:

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

## Capability coverage

`capability-catalog.json` inventories area prices, variable market intervals,
daily statistics, price windows, currency conversion, VAT, adjustments,
source health, and chart requirements. Tests enforce that only implemented
capabilities are advertised.

Current and next prices use timestamped intervals; no fixed number of hourly
samples is assumed. Missing current data marks the feed unavailable. A missing
tomorrow publication does not erase a valid current price. Daily statistics,
price-window actions, and chart widgets remain planned.

The public data-portal endpoint serves published auction prices, but it is not
Nord Pool's subscription-based Market Data API and has no guaranteed uptime or
schema stability. On a failed refresh, the runtime retains the last good price
and marks `connected=false`. The `telemetry/example` compatibility routes now
refresh real market data rather than sending fabricated samples.

## Manifest

The read-only Widget SDK card is in `widgets/nord-pool-price`. Its local bundle
is declared in `manifest.json`; the Core simulator installer can package it
from the checkout without a marketplace release. In the manifest-driven lab,
set `market_area` to `SE3`, `price_unit` to `EUR/kWh`, and the two price metrics
to realistic numbers through `/__simulator/metrics`. Those values are
explicitly synthetic and do not prove live API behavior.

`manifest.json` remains draft. Before publishing, verify:

- `image`
- `version`
- live API behavior and public endpoint terms
- a Core attach and live-widget visual check
- market-area and currency coverage

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-nord-pool:0.1.0 .
docker run --rm -p 4214:4214 docker.io/piphinetwork/piphi-network-nord-pool:0.1.0
```
