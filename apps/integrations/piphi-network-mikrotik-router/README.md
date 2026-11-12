# Piphi Network Mikrotik Router

Generated PiPhi integration runtime.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_mikrotik_router.main:app --reload --port 4218
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4218` by default and exposes the common PiPhi runtime route contract:

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

The first live capability slice uses an HTTPS-only, authenticated GET of
RouterOS `/rest/system/resource`. Configure the router `host`, a dedicated
read-only `username`, the RouterOS password in the password field, and a
`ca_bundle_path` if the router certificate uses a private CA. The native
Router Health widget shows CPU and memory use. Failed authentication, TLS, or
malformed readings keep the device disconnected; no router password is
returned in state or telemetry. See the [RouterOS REST API](https://help.mikrotik.com/docs/spaces/ROS/pages/47579162/REST%2BAPI)
and [resource fields](https://help.mikrotik.com/docs/spaces/ROS/pages/40992875/Resource).

Other RouterOS features, such as per-interface traffic and client inventory,
remain planned and are not implied by the health widget.

`capability-catalog.json` inventories the reviewed RouterOS system health,
interfaces, traffic, clients, DHCP, wireless, LTE, routing, firewall, VPN,
services, logs, maintenance, and administrative boundaries. Every entry is
classified as implemented, planned, or excluded, and contract tests ensure
that only implemented entries are advertised.

Broader router monitoring needs version fixtures, counter normalization,
redaction, and transition tests. Arbitrary console, REST, and configuration
mutation remain explicitly excluded.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t docker.io/piphinetwork/piphi-network-mikrotik-router:0.1.0 .
docker run --rm -p 4218:4218 docker.io/piphinetwork/piphi-network-mikrotik-router:0.1.0
```
