# SolarEdge API and Python library research

Research date: 2026-09-01.

## Decision

This first runtime uses the MIT-licensed [`solaredge`](https://github.com/EVWorth/solaredge) Python package through a narrow adapter. Version `1.1.1` supports Python 3.10–3.14, provides synchronous and asynchronous clients, uses `httpx`, and covers the SolarEdge Monitoring API V1.

The adapter boundary is mandatory because SolarEdge says Monitoring API V1 will be deprecated on November 1, 2026. SolarEdge ONE for Developers is the successor, uses granular OAuth scopes and per-user consent, and has a different commercial quota model. The public V2 specification must be validated with a SolarEdge developer application before this registry listing can be promoted from draft.

## SolarEdge ONE commercial transition

SolarEdge advertises the new platform as free during its introductory period through November 1, 2026. Its US store currently lists Starter, Growth, and Pro at $100, $400, and $1,000 per month after that date, with 20,000, 100,000, and 400,000 monthly API credits and ceilings of 25, 50, and 100 calls per minute respectively. Enterprise/custom options and regional pricing may differ. PiPhi should treat those values as deployment planning information, not hard-code them into runtime behavior.

V2 is described as covering site/fleet information, live and historical telemetry, alerts, production, consumption, storage, and inverter-level data. The public landing page does not expose enough machine-readable detail to safely implement token URLs, refresh semantics, scopes, or response models without a developer-console application, so none of those details are guessed here.

## Authentication and access

V1 requests use a Site ID plus an API key in the `api_key` query parameter. Access is read-only. Site owners may need their installer or site administrator to enable API access. PiPhi treats the key as a secret, never returns it from runtime state, and validates access with the site-details endpoint during configuration.

## Limits and polling policy

The official V1 guide documents 300 daily requests for an account token, a parallel per-site limit, at most three concurrent requests from one source IP, and HTTP 429 after exhaustion. Bulk endpoints accept up to 100 site IDs but consume site quota for every included site.

The runtime therefore:

- allows one configured site in this release;
- polls current power flow no faster than every 10 minutes;
- fetches the slower overview summary no faster than hourly;
- reuses one async client for the process lifetime;
- preserves the last good state and reports transient failures as disconnected;
- never retries HTTP 429 in a tight loop.

At the defaults, a continuously running site consumes about 96 flow calls plus 24 summary calls per day, leaving headroom for startup validation and manual refreshes.

## Data surfaces and PiPhi mapping

| SolarEdge value | PiPhi capability | Normalization |
| --- | --- | --- |
| PV current power | `production_power_w` | kW/MW converted to W |
| LOAD current power | `consumption_power_w` | kW/MW converted to W |
| GRID current power | `grid_power_w` | positive import, negative export |
| STORAGE current power | `battery_power_w` | positive discharge, negative charge |
| STORAGE charge level | `battery_soc_percent` | percent |
| Day/month/year/lifetime energy | `*_energy_kwh` | Wh converted to kWh |
| Lifetime revenue | `lifetime_revenue` | numeric value; currency metadata is vendor/site-defined |

Power direction is derived from the API's connection graph rather than assuming the unsigned node magnitude expresses direction. Consumption, grid, and storage nodes are optional because not every installation has the corresponding meter or battery.

## Library coverage not polled in v0.1

The upstream client also exposes site lists/details, energy and power histories, detailed meter breakdowns, storage history, inventory, inverter technical data, environmental benefits, equipment change logs, sensors, meters, accounts, and API-version endpoints. Polling those surfaces by default would spend quota without improving the primary live dashboard. They are candidates for on-demand diagnostics or future history backfill.

## Widgets

Two Widget SDK cards ship as one signed, integration-owned declarative experience: a live solar/home/grid/battery flow card and a production totals card. Core renders both from source-scoped PiPhi capability bindings; SolarEdge credentials, executable widget code, and direct cloud access are never exposed to the package.

## Release blockers

- Validate the SolarEdge ONE V2 OAuth flow, scopes, endpoint schemas, token refresh, and error model using a developer application.
- Replace or extend the V1 adapter before November 1, 2026.
- Publish and qualify the immutable runtime image before registry promotion beyond draft/unverified.

## Primary references

- [SolarEdge Monitoring API V1 guide](https://knowledge-center.solaredge.com/sites/kc/files/se_monitoring_api.pdf)
- [SolarEdge API documentation landing page](https://api-docs.solaredge.com/)
- [SolarEdge ONE for Developers](https://developer.solaredge.com/)
- [`solaredge` Python client](https://github.com/EVWorth/solaredge)
