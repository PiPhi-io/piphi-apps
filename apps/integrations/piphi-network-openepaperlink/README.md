# OpenEPaperLink

Read-only PiPhi monitoring for a manually configured local OpenEPaperLink access point.

## Supported scope

- Polls the bounded, paginated `GET /get_db` endpoint.
- Reports AP connectivity, configured-tag count, and pending-transfer count.
- Lists tags using stable config-scoped hashes; raw MAC addresses are not retained or sent to Core.
- Emits deduplicated AP unavailable/recovered and tag discovered/removed transitions.
- Preserves last-good counts as stale during failures and restores Core-owned configuration after restart.
- Supports one read-only, single-AP `refresh` action.

Rendering, content transfer, tag radio/power details, maintenance, and all per-tag controls are deliberately not implemented. Physical AP/tag/model/firmware qualification is also outside this source-only package.

## Security and configuration

Only `GET /health` is public. Every other route requires the exact value of
`PIPHI_INTEGRATION_INTERNAL_TOKEN` in `X-PiPhi-Integration-Token`; a missing server token fails closed.

Configure an RFC1918, IPv6 ULA, or link-local AP address, or a `.local`/`.lan` hostname that resolves only to those ranges. The client pins the approved address, disables environment proxies and redirects, bounds responses/pages/tags, and retries transient transport failures at most three times. Configuration is committed only after a successful AP read; failed reconfiguration leaves the previous configuration active.

```bash
pdm install --check
pdm run pytest --cov=piphi_network_openepaperlink --cov-branch --cov-fail-under=80
pdm run ruff check src tests
pdm run ruff format --check src tests
pdm run mypy src/piphi_network_openepaperlink
pdm run bandit -q -r src
pdm run python scripts/validate.py
```

## Container

The locked multi-stage image runs as UID/GID `10001`, contains no mutable application data requirement, and is declared for a read-only root filesystem. Build for the two catalogued platforms with BuildKit/buildx:

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t ghcr.io/piphi-io/piphi-network-openepaperlink:0.1.1 .
```
