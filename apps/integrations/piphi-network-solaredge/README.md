# PiPhi Network SolarEdge

Read-only SolarEdge Monitoring integration built with `piphi-runtime-kit-python` and the `piphi-network-create` cloud-polling scaffold.

It provides live solar production, home consumption, signed grid import/export, optional battery power/state of charge, production totals, Core telemetry, a manual refresh command, and two declarative dashboard widgets in one integration-owned experience package.

> SolarEdge says Monitoring API V1 will be deprecated on November 1, 2026. This release remains draft/unverified until the SolarEdge ONE V2 OAuth contract is validated. See [the API/library research](docs/solaredge-library-research.md).

The current V1 implementation passes its automated runtime and experience
qualification, but it is intentionally marked `release_candidate` rather than
complete. OAuth v2 migration and validation against a physical SolarEdge site
remain explicit release gates in `docs/capability-catalog.json`.

## Configure

In SolarEdge Monitoring, enable API access and obtain the numeric Site ID and API key. PiPhi stores the API key as a secret.

```json
{
  "id": "home-solar",
  "site_id": 1234567,
  "api_key": "replace-with-your-api-key",
  "alias": "Home solar",
  "poll_interval_seconds": 900,
  "summary_interval_seconds": 3600
}
```

The minimum intervals deliberately preserve room under SolarEdge's documented 300-request daily quota.

## Develop and verify

```bash
pdm install -G dev
pdm run pytest
pdm run python scripts/validate.py
pdm run python scripts/build_experience.py --check
```

The experience source lives under `experiences/solar-energy/`. It packages the
Energy Flow and Production Summary widgets together, uses only Core-rendered
declarative primitives, and declares package-owned themes, source-scoped binding
slots, stale-data thresholds, history interactions, and Core card replacements.

The Python suite includes vendor-response normalization, quota-conscious service
lifecycle and history behavior, a real Runtime SDK delivery through TestKit's
mock Core, deterministic signed experience packaging, accessibility metadata,
and direct PiPhi Core contract validation when Core is checked out alongside it.

## Run

```bash
pdm run uvicorn solar_edge.main:app --reload --port 8090
```

The runtime exposes `/health`, `/diagnostics`, `/discover`, `/config`, `/config/sync`, `/deconfigure`, `/ui-config`, `/state`, `/contract`, `/entities`, `/events`, `/telemetry/example`, and `/command`.

## Docker

```bash
docker build -t piphinetwork/piphi-network-solaredge:0.2.2 .
docker run --rm -p 8090:8090 piphinetwork/piphi-network-solaredge:0.2.2
```

The container runs as a non-root user, persists the Runtime SDK automation
ledger under `/var/lib/piphi`, and exposes an image health check.
