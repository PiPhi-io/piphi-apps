# Steam integration contract

This integration polls the official Steam Web API over HTTPS. It accepts one SteamID64 and one secret Web API key per configuration. The key is retained only in the private runtime configuration registry and is never returned through state, telemetry, events, diagnostics, or logs.

Private profile, recent-game, or library data is represented as unavailable. The integration does not scrape Steam Community pages and does not launch games, send messages, trade, purchase, or modify the Steam account.

The first successful sample establishes a baseline. Subsequent samples may emit game-started, game-stopped, game-changed, and persona-changed events. Poll failures are scoped to the affected configuration and preserve the last successful state with `connected=false`.
