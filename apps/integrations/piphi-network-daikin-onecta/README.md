# PiPhi Network Daikin Onecta

Daikin Onecta climate integration for PiPhi Network. Version `0.2.0` provides
a bounded Python 3.12 functional slice:

- Core-managed OAuth access-token delivery; tokens are never returned in state,
  events, telemetry, diagnostics, or logs;
- one quota-aware account-wide poll for gateway devices;
- dynamic climate entities for management points that expose room or target
  temperature;
- power, HVAC mode, indoor temperature, target temperature, availability, and
  stale-last-good observation;
- read-only `refresh`; and
- opt-in `set_target_temperature`, constrained by provider mode, writable flag,
  range, and step, with one PATCH and no automatic retry.

This release remains `draft`, rollout `0`, quality `unrated`, and qualification
`unverified`. A Daikin developer application, Core OAuth callback/token
persistence, terms/privacy review, and representative live devices are separate
production-certification gates.

## Development

```bash
pdm install --check
pdm run pytest
pdm run ruff check src tests
pdm run python scripts/validate.py
```

The runtime listens on port `4215`. See `docs/contract.md` for routes and
`capability-catalog.json` for implemented, planned, and excluded surfaces.

## Configuration ownership

`oauth_subject` and `access_token` are authored by PiPhi Core after OAuth. They
are not intended as user-pasted production fields. Users may edit the account
alias, polling interval (300–3600 seconds), and the explicit climate-control
opt-in. Disabling control leaves observation and refresh available.

## Container

```bash
docker build -t ghcr.io/piphi-io/piphi-network-daikin-onecta:0.2.0 .
docker run --rm -p 4215:4215 ghcr.io/piphi-io/piphi-network-daikin-onecta:0.2.0
```
