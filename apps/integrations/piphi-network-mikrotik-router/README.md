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

Only `GET /health` is public. Core must inject
`PIPHI_INTEGRATION_INTERNAL_TOKEN` and send it in
`X-PiPhi-Integration-Token` for every operational route. The runtime fails
closed when the token is absent or invalid. On startup it restores the mounted
Core config snapshot first, then refreshes from Core when managed-runtime
credentials are available, so a container restart does not silently lose
configured routers.

## Capability coverage

The first live capability slice uses an HTTPS-only, authenticated GET of
RouterOS `/rest/system/resource`. Configure the router `host`, a dedicated
read-only `username`, the RouterOS password in the password field, and a
`ca_bundle_path` under `/etc/ssl/certs/` or `/run/secrets/` if the router
certificate uses a private CA. The native
Router Health widget shows CPU and memory use. Failed authentication, TLS, or
malformed readings keep the device disconnected; no router password is
returned in state or telemetry. See the [RouterOS REST API](https://help.mikrotik.com/docs/spaces/ROS/pages/47579162/REST%2BAPI)
and [resource fields](https://help.mikrotik.com/docs/spaces/ROS/pages/40992875/Resource).

Other RouterOS features, such as per-interface traffic and client inventory,
remain planned and are not implied by the health widget.

Create a dedicated RouterOS group with exactly `read,api,rest-api`; RouterOS
requires `api` alongside `rest-api` for REST login. Do not use the
built-in `read` group, which grants unrelated sensitive privileges. Restrict
the monitoring user's `address` to the PiPhi runtime host or management subnet,
enable `www-ssl`, and disable plain `www`. Setup performs authenticated reads of
`/rest/system/resource` and `/rest/system/license`; both must be permitted.
The license software ID is hashed into the PiPhi device ID, is never exported,
and prevents the same appliance being configured twice under different hosts.
Legacy configuration payloads named `api_key` are accepted as passwords during
migration but are never returned.

`permission-contract.json` defines the exact two-read least-privilege contract
and its automated denial matrix. Setup validates authentication, certificate
trust, both permissions, appliance identity, and a RouterOS 7 version before
saving. Requests are serialized per appliance, responses are capped at 256 KiB,
and polling uses bounded backoff, deterministic jitter, and a five-failure
circuit breaker. Authentication failures request reauthentication; permission,
TLS, version, and schema failures request reconfiguration without exposing
credentials or private host identifiers.

`capability-catalog.json` inventories the reviewed RouterOS system health,
interfaces, traffic, clients, DHCP, wireless, LTE, routing, firewall, VPN,
services, logs, maintenance, and administrative boundaries. Every entry is
classified as implemented, planned, or excluded, and contract tests ensure
that only implemented entries are advertised.

Broader router monitoring needs version fixtures, counter normalization,
redaction, and transition tests. Arbitrary console, REST, and configuration
mutation remain explicitly excluded.

Qualification is software-only: deterministic fake RouterOS HTTPS servers,
sanitized response schemas, and exact local container images. No physical
router, board, package set, or firmware release is qualified, and the manifest
makes no broad RouterOS hardware compatibility claim.

## Manifest

`manifest.json` remains draft/unverified. Before any future publishing, verify:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t ghcr.io/piphi-io/piphi-network-mikrotik-router:0.1.3 .
docker volume create piphi-mikrotik-data
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  -v piphi-mikrotik-data:/data/piphi \
  -e PIPHI_INTEGRATION_INTERNAL_TOKEN=replace-with-core-issued-token \
  -p 127.0.0.1:4218:4218 \
  ghcr.io/piphi-io/piphi-network-mikrotik-router:0.1.3
```

The runtime and its persistent ledger execute as UID/GID `10001`. Deployments
using a bind mount instead of a named volume must provision the host directory
for that ownership before startup.
