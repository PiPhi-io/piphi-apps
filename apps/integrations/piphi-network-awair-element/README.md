# Awair Element (Local API)

Read-only PiPhi integration for Awair Element devices with the local HTTP API enabled.

## Supported contract

- verified mDNS discovery for `AWAIR-ELEM-*` services
- stable device identity derived from the discovered or explicitly configured Awair identity
- latest air-quality readings from `GET /air-data/latest`
- bounded polling, stale-last-good state, recovery, removal, and startup config restoration
- an idempotent, read-only `refresh` command
- telemetry for only validated fields returned by the device

The runtime does **not** control the device, send notifications, infer missing readings, or claim that a device exists without mDNS plus a successful local API probe. Historical endpoints remain outside this release.

## Security boundary

- only `/health` is public
- all other routes require `X-PiPhi-Integration-Token` matching `PIPHI_INTEGRATION_INTERNAL_TOKEN`
- startup fails closed for protected routes when runtime authentication is not configured
- device destinations must resolve exclusively to allowed local addresses
- requests are pinned to the validated address, ignore proxy environment variables, and reject redirects
- diagnostics omit configured addresses, mDNS names, payloads, and credentials
- the container runs as UID/GID `10001`, uses a digest-pinned base, hash-locked dependencies, and a non-writable application tree

`PIPHI_ALLOW_UNAUTHENTICATED=true` exists only for isolated test/development harnesses and must not be set in production.

## Development

```bash
pdm install -G dev
pdm run ruff check src tests
pdm run mypy src
pdm run pytest -q
pdm run bandit -q -r src
pdm run pip-audit --ignore-vuln PYSEC-2026-1845
```

`PYSEC-2026-1845` affects the dev-only pytest runner. The current Runtime TestKit requires pytest 8; the runtime image contains neither package. The exception can be removed when a TestKit release permits pytest 9.

The fake HTTP transport in `lib/awair_client.py` is deterministic and socket-free. It is a test fixture, not hardware evidence or runtime discovery.

## Qualification boundary

Software tests cover the runtime contract and failure behavior. Physical Awair Element qualification remains separate and must verify mDNS naming, Local API enablement, representative firmware payloads, reconnect behavior, and sustained polling on real hardware before any governance promotion.

Use the [physical qualification record template](docs/hardware-qualification-template.md) with a real Awair Element. The companion wizard creates a private record and walks the operator through the required observations without fabricating or publishing evidence:

```bash
./scripts/run_hardware_qualification_wizard.sh
```

The wizard does not merge, publish, synchronize a registry, or authorize governance promotion. Review and redact the generated record before sharing it.
