# PiPhi Network Midea AC LAN

Production runtime for monitoring and optionally controlling supported Midea air
conditioners over the local network.

## Run locally

```bash
pdm install -G dev
PIPHI_INTEGRATION_INTERNAL_TOKEN=development-token pdm run uvicorn piphi_network_midea_ac_lan.main:app --reload --port 4208
pdm run pytest --cov=piphi_network_midea_ac_lan --cov-branch
pdm run python scripts/validate.py
```

The runtime listens on port `4208` by default and exposes the common PiPhi runtime route contract:

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
- `POST /command`

Only `/health` is public. All other routes require the token from
`PIPHI_INTEGRATION_INTERNAL_TOKEN` in the `X-PiPhi-Integration-Token` header.
Set `MIDEA_SIMULATION_MODE=true` only for deterministic testing without a
physical appliance.

## Capability coverage

`capability-catalog.json` inventories the reviewed climate state, optional
features, energy and diagnostic telemetry, compatible appliance profiles,
events, conditions, actions, and protocol variants. Every entry is classified
as implemented, planned, or excluded. Contract tests enforce that only
implemented entries are advertised.

The common 0xAC climate profile now includes local power, HVAC mode, target
temperature, device-reported fan and swing modes, and comfort presets. Fan and
swing commands fail closed when the appliance does not advertise the selected
option. The dashboard's HVAC action is an estimate derived from power, mode,
room temperature, target temperature, and a 0.5 °C deadband; it is not direct
compressor telemetry. Tokens, keys, arbitrary attributes, and raw protocol
commands are never exposed through the runtime contract.

## Docker

```bash
docker build -t piphi-network-midea-ac-lan:0.3.1 .
docker run --rm --read-only --user 10001:10001 \
  --tmpfs /tmp --tmpfs /var/lib/piphi:uid=10001,gid=10001 \
  -e PIPHI_INTEGRATION_INTERNAL_TOKEN=replace-me \
  -p 4208:4208 piphi-network-midea-ac-lan:0.3.1
```
