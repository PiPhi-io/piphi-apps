# PiPhi Network Steam integration

Connects a homeowner's Steam account to PiPhi using Valve's documented Steam Web API. The integration monitors player presence, current-game activity, recent games, and library-level playtime summaries. It never asks for a Steam password and does not launch games, send messages, trade items, or make purchases.

## Configuration

1. Register a Steam Web API user key at <https://steamcommunity.com/dev/apikey> for the domain where this PiPhi installation is operated.
2. Find the account's 17-digit SteamID64.
3. Add the integration in PiPhi with `steam_id`, the secret `web_api_key`, and an optional display name.
4. Game details must be visible under Steam profile privacy settings for library and recent-game data to be available. Games marked private remain absent.

The Web API key stays inside the integration runtime and is sent only to `https://api.steampowered.com` using the `x-webapi-key` header. It is excluded from state, telemetry, events, diagnostics, and logs.

## Development

```bash
pdm install --frozen-lockfile -G dev
pdm run pytest
pdm run ruff check src tests
pdm run ruff format --check src tests
cd widgets/steam-activity && npm ci && npm test && npm run build && npm run validate && npm run conformance
docker build -t piphi-network-steam:dev .
```

Steam data is subject to Valve's Steam Web API Terms of Use and is provided as-is. This project is not affiliated with or endorsed by Valve Corporation.

