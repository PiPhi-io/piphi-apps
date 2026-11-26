# PiPhi Network Sense

PiPhi runtime integration for the [Sense Energy Monitor](https://sense.com/), built with `piphi-runtime-kit-python` and the `piphi-network-create` cloud-polling scaffold.

The integration uses the unofficial [`sense-energy`](https://github.com/scottbonline/sense) Python client. It maintains exactly one authenticated client, polls realtime data no more often than once per minute, refreshes provider-local daily trend data on a slower interval, exposes detected Sense devices as PiPhi entities, and supports Sense MFA during configuration. A best-effort extension reuses that same session for read-only appliance metadata, Always On/Other watts, and at most 20 recent timeline events; failures there never disconnect normal monitoring.

Only `GET /health` is public. Every other route fails closed unless Core supplies the runtime token. Reconfiguration authenticates and reads from a candidate session before replacing the active session, and a different provider monitor cannot silently replace an existing account identity. Access and refresh tokens are stored only in the mode-`0600` session cache on `/var/lib/piphi`; responses, events, diagnostics, and logs apply recursive secret redaction. Core-managed configuration is rehydrated on restart.

Realtime, daily-trend, and opt-in private-activity slices report independent freshness. Authentication failures stop provider retries until reconfiguration; transient and rate-limit recovery uses bounded backoff. Daily totals are explicitly labeled as the current, incomplete calendar day in the monitor's provider timezone rather than as a rolling 24-hour interval.

## Run locally

```bash
pdm install -G dev
pdm run pytest
pdm run python scripts/validate.py
pdm run uvicorn piphi_network_sense.main:app --reload --port 8090
```

Configure the runtime through `POST /config`:

```json
{
  "id": "sense-account",
  "email": "owner@example.com",
  "password": "your-password",
  "mfa_code": "only-when-requested",
  "alias": "Sense Home",
  "poll_interval_seconds": 60,
  "trend_interval_seconds": 900
}
```

The manifest declares `config.maximum_instances: 1`. The runtime independently returns `409 instance_limit_reached` if a second configuration reaches it, protecting Sense from duplicate authenticated sessions even when used with an older Core.

## Behaviors and automations

The behavior catalog defines separate Core behavior types for the Sense monitor and each detected appliance. Monitor automations can react to household power, solar power, Always On, and Other changes or compare those values and daily usage against thresholds. Appliance automations have distinct `turns on` and `turns off` transition triggers, a power-change trigger, and conditions for current state, power, and daily energy.

Each appliance is delivered to Core as its own telemetry device, so `device.state_changed` events target the selected Sense appliance rather than only the parent monitor. Sense remains read-only; `refresh` is its only action, while notifications and load-control actions can be composed from other integrations.

The executable half uses the Runtime SDK directly: `refresh` is registered with `@automations.action`; `device.state_changed`, `device.power.turned_on`, and `device.power.turned_off` are registered as telemetry-projected events; and startup runs `assert_behaviors_contract` to prevent drift between the decorators and `behaviors.json`. Conditions remain declarative because Core evaluates them against projected telemetry state.

## Dashboard cards

The integration-owned `io.piphi.sense-energy` experience package is installed
with Sense and provides two Core-hosted cards:

- **Sense Energy Overview**: connection, live home/solar power, daily totals,
  Always On, and Other loads.
- **Sense Appliance Energy**: current power and daily energy for an individual
  appliance detected by Sense.

The package source lives in `experiences/sense-energy/package.source.json` and
uses the Widget SDK 0.5.1 contract. The overview has a sandboxed,
consumption-first presentation; the appliance card remains declarative. Core
continues to own card sizing, bindings, interaction policy, and runtime
isolation for both.

See [Sense library research](docs/sense-library-research.md) and the [Core single-instance contract](docs/core-single-instance-contract.md) for implementation constraints and the Core-side enforcement design.

## Simulator

The companion `piphi-integration-simulators` repository provides a `sense`
scenario with balanced, high-load, solar-export, overnight, offline, and
per-appliance controls. It mirrors the production entity and telemetry contract
and uses the same integration-owned experience package as the physical runtime,
so simulator-only widget forks are not maintained. Capability and readiness
parity is enforced by `docs/capability-catalog.json`; physical-account validation
remains explicitly pending.

## Runtime contract

The service exposes `/health`, `/diagnostics`, `/discover`, `/config`, `/config/sync`, `/deconfigure`, `/state`, `/contract`, `/entities`, `/events`, `/telemetry/example`, and `/command` on port `8090`.

Build the production image with:

```bash
docker build -t ghcr.io/piphi-io/piphi-network-sense:0.2.1 .
```

## Releases

After source CI passes and the source PR is merged, dispatch the monorepo
**Release one app package** workflow from `main` with package
`piphi-network-sense`, the exact committed version, and publishing enabled. The
workflow creates the immutable namespaced tag `apps/piphi-network-sense/vVERSION`,
publishes `ghcr.io/piphi-io/piphi-network-sense` for `linux/amd64` and
`linux/arm64`, attaches SBOM and provenance attestations, and emits release and
registry-proposal evidence.

Both the release candidate and exact published digest are qualified with the
network-disabled deterministic account fixture in
`scripts/qualify_release_image.py`. It verifies fail-closed routes, stable
identity, privacy, period/freshness semantics, non-root execution, and a
read-only root filesystem. This is simulator evidence only and **does not claim
live-account qualification**. Registry synchronization remains a separate,
reviewed PR and must preserve the existing governance fields.
