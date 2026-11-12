# Piphi Network Octopus Energy

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_octopus_energy.main:app --reload --port 4212
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4212` by default and exposes the common PiPhi runtime route contract:

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

The first live capability slice reads the public Octopus electricity tariff
`standard-unit-rates` endpoint. Configure the electricity `product_code` and
`tariff_code` from your Octopus tariff; no host or API key is needed. The
native Rates widget shows the current VAT-inclusive price in p/kWh and the
next published price when available. The runtime fetches on configuration,
refresh, and a bounded poll cadence. Without valid codes or a successful
response it reports disconnected and does not invent a price. This slice uses
no account API key. See the [Octopus API endpoint guide](https://developer.octopus.energy/guides/rest/api-endpoints/).

The rest of the account and meter surface remains planned; the widget does not
show consumption, bills, export, or tariff-switching controls.

`capability-catalog.json` inventories accounts, properties, meters,
consumption, export, costs, products, tariffs, rates, Intelligent dispatches,
optional programmes, polling health, events, conditions, and safe operations.
Contract tests enforce that only implemented entries are advertised.

Account, meter, region, agreement, tariff, and feature permissions must be
negotiated before those entities expose their precise capability set. API keys,
billing details, tariff switching, and arbitrary API requests are excluded.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-octopus-energy:0.1.0 .
docker run --rm -p 4212:4212 docker.io/piphinetwork/piphi-network-octopus-energy:0.1.0
```
