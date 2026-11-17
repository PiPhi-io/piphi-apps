# PiPhi Network pfSense

Monitoring-first PiPhi Network integration for pfSense firewalls running the community
[pfSense REST API v2](https://pfrest.org/). The runtime polls firewall health,
interfaces, gateways, services, and optionally DHCP/VPN status, then publishes
normalized PiPhi entities, telemetry, transition events, and an overview widget.

The integration never modifies firewall configuration, installs packages, or
executes arbitrary commands. Diagnostic ping, service start/restart, and
Wake-on-LAN are explicit, allow-listed actions and are disabled by default.

## Requirements

- Python 3.11 or newer
- A pfSense CE or pfSense Plus installation whose exact release and pfREST v2
  combination has been qualified by the operator
- The community `pfSense-pkg-RESTAPI` v2 package
- HTTPS connectivity from the PiPhi runtime to the pfSense management address
- A dedicated API key with only the endpoint privileges enabled below

Required pfSense API access:

- `GET /api/v2/status/system`
- `GET /api/v2/system/version`
- `GET /api/v2/system/restapi/version`
- `GET /api/v2/status/interfaces`
- `GET /api/v2/status/gateways`
- `GET /api/v2/status/services`

The corresponding generated pfREST privileges are
`api-v2-status-system-get`, `api-v2-system-version-get`,
`api-v2-system-restapi-version-get`, `api-v2-status-interfaces-get`,
`api-v2-status-gateways-get`, and `api-v2-status-services-get`.

Optional access is needed for DHCP leases and VPN status only when those
collection settings are enabled.

Optional action privileges:

- `api-v2-diagnostics-ping-post` for diagnostic ping
- `api-v2-status-service-post` for service start/restart
- `api-v2-services-wake-on-lan-send-post` for Wake-on-LAN

Optional monitoring privileges, enabled by their corresponding collection flags:

- `GET /api/v2/diagnostics/arp_table` and DHCP leases for client inventory
- `GET /api/v2/status/logs/{firewall,auth,dhcp,system}` for log events
- `GET /api/v2/system/certificates` for expiry metadata
- `GET /api/v2/status/carp`, `/api/v2/firewall/virtual_ips`, and
  `/api/v2/system/hasync` for high-availability monitoring

All six baseline GET endpoints above are essential: setup fails, and an active
firewall is marked unavailable, if any is denied or malformed. Optional endpoint
failures remain scoped to their selected feature. Use a separate pfREST API key
containing only these exact endpoint privileges and the explicitly selected
optional privileges; no administrator role is required or recommended.

Selecting an optional profile makes every endpoint in that profile essential
during setup. During later polls, a partial selected profile is explicitly
unavailable (`connected=false`), `degraded`, and `stale`; its profile metrics
are suppressed, and any retained last-known-good profile values are marked
stale. Permanent permission/version failures stop polling for user action,
while transient failures retry. `permission-contract.json` is the machine-readable privilege and
denial matrix. CI verifies deterministic fake pfREST responses and sanitized
recorded schemas only. No physical appliance or firmware combination is
qualified by this package, and no compatibility beyond the exact locally tested
image/version pair should be inferred.

## Local development

```bash
pdm install -G dev
pdm run pytest
pdm run ruff check src tests
pdm run mypy src/piphi_network_pfsense
pdm run python scripts/validate.py
pdm run uvicorn piphi_network_pfsense.main:app --reload --port 8090
```

The development group includes `piphi-runtime-testkit-python==0.1.4`. Its
end-to-end test starts a loopback mock PiPhi Core, configures the runtime with
TestKit payload builders, validates `/entities`, and captures outbound telemetry
and transition events.

Configure the runtime through `POST /config`:

```json
{
  "id": "home-firewall",
  "host": "pfsense.example.lan",
  "api_key": "replace-with-a-least-privilege-api-key",
  "alias": "Home Firewall",
  "port": 443,
  "scheme": "https",
  "verify_tls": true,
  "allow_insecure_transport": false,
  "poll_interval_seconds": 60,
  "collect_dhcp_leases": false,
  "collect_vpn_status": false,
  "collect_client_inventory": true,
  "collect_security_logs": true,
  "collect_certificates": true,
  "collect_ha_status": false,
  "enable_diagnostic_ping": true,
  "allowed_ping_hosts": ["1.1.1.1", "gateway.example.lan"],
  "enable_service_restart": false,
  "enable_service_start": false,
  "allowed_services": [],
  "enable_wake_on_lan": true,
  "wake_on_lan_targets": [
    {
      "id": "office-pc",
      "label": "Office PC",
      "interface": "lan",
      "mac_addr": "aa:bb:cc:dd:ee:ff"
    }
  ]
}
```

For dashboard development, set `simulation_mode` to `true`. Host and API key are
then optional and the runtime supplies deterministic firewall, interface,
gateway, VPN, client, certificate, HA, and security-log data. The simulator only
replaces the pfREST transport; state projection, entity generation, telemetry,
events, allow-list checks, actions, and widgets use the production code paths.

`host` accepts a hostname or IP address, not a URL. HTTPS and certificate
verification are enabled by default. For an internal CA, mount its PEM bundle
read-only under `/etc/ssl/certs/` or `/run/secrets/` and set `ca_bundle_path`.
HTTP or disabled verification additionally requires
`allow_insecure_transport=true` **and** the deployment-level environment gate
`PIPHI_PFSENSE_LAB_ALLOW_INSECURE=true`. The container does not set that gate
by default, so ordinary production configuration cannot disable transport
security. Use both controls only in an isolated lab.

## Runtime model

Each configured firewall becomes a `network_gateway` entity. Live interfaces,
routing gateways, and OpenVPN/IPsec/WireGuard tunnels become child entities with
stable IDs. Interface byte counters are converted into receive/transmit bit
rates after the first sample. No VPN keys are projected into PiPhi state.

The runtime exposes the standard PiPhi endpoints, including `/health`,
`/diagnostics`, `/discover`, `/config`, `/entities`, `/state`, and `/command`.
`refresh` performs an immediate read-only poll. `diagnostic_ping` accepts only
targets in `allowed_ping_hosts`. `restart_service` accepts only services in
`allowed_services`; `start_service` uses the same allowlist. `wake_on_lan`
accepts only a configured target ID, keeping its interface and MAC immutable to
the caller. Service operations require confirmation and prevent multi-firewall
fanout. Every operational action must be enabled independently.

Service control is fail-closed even when a name appears in `allowed_services`.
Only the explicitly classified observability agents `collectd`,
`node_exporter`, and `telegraf` are accepted. DNS, DHCP, routing, VPN, HA,
web/API, authentication, firewall, unknown, and all other services are rejected
during configuration and rechecked at command dispatch. Do not use service
control for network-plane recovery.

Gateway, interface, and service up/down transitions are delivered as Runtime
SDK integration events and exposed as behavior triggers. The widget source is
under `widgets/pfsense-overview`. A second client/security widget displays
inventory, certificate alerts, and recent log volume. Run `npm ci && npm run
conformance` in either widget directory for local validation.

Log collection is an explicit privacy opt-in, establishes the first response as
its baseline, and emits only a stream name plus an opaque event fingerprint for
new entries. Raw firewall/auth/DHCP/system text is never forwarded. Inputs are
bounded and credentials, IP addresses, and hostnames are redacted before
deduplication. Certificate responses are stripped down to description,
type, and validity fields immediately; certificate bodies, CSRs, CA references,
and private keys are never retained in normalized snapshots or PiPhi state.

Action idempotency results are stored in `/data/piphi/automation-actions.sqlite3`.
The manifest mounts `/var/lib/piphi/pfsense` there so a container restart cannot
silently repeat a previously completed service operation.

Optional endpoint failures do not discard the system snapshot. They are
reported under `endpoint_errors` in state and diagnostics so a least-privilege
API key can be expanded deliberately rather than requiring administrator
access.

Requests for one firewall are serialized. Responses are limited to 1 MiB,
ordinary collections to 1,000 rows, and each log stream to 200 reduced records.
Retries use bounded exponential backoff with deterministic jitter; five
consecutive failures open the circuit for five minutes. Diagnostics expose only
safe reason/remediation classes and aggregate status.

## Container

```bash
docker build -t ghcr.io/piphi-io/piphi-network-pfsense:0.1.10 .
```

The container does not require host networking, privileged mode, or access to
the pfSense filesystem.

The runtime and its persistent ledger execute as UID/GID `10001`. Docker named
volumes inherit the image directory ownership. Deployments using the manifest's
bind mount must provision `/var/lib/piphi/pfsense` for UID/GID `10001` before
startup; replacing `/data/piphi` with a root-owned tmpfs is intentionally not a
supported writable-volume contract.

## Releases

Use the monorepo **Release one app package** workflow with package ID
`piphi-network-pfsense`, the committed version, and `publish=false` for
qualification. Publishing creates the immutable tag
`apps/piphi-network-pfsense/v0.1.10` and the managed GHCR image
`ghcr.io/piphi-io/piphi-network-pfsense:0.1.10`; do not create standalone `v*`
tags or Docker Hub releases.

## Upstream status

The pfSense REST API package is community maintained and is not supported by
Netgate. Its compatibility is tied to specific pfSense releases. Validate the
package/firewall version combination in a non-production environment before
deployment.
