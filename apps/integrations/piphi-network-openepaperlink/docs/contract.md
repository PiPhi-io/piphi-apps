# Runtime contract

Version `0.1.1` exposes the standard health, diagnostics, manual discovery, configuration/sync/removal, entities, state, event-list, UI-config, contract, and command routes declared by `manifest.json`.

Only `/health` is public. Operational routes require `X-PiPhi-Integration-Token`. Manual discovery always returns no devices; configuration supplies the local AP explicitly and must pass a live read before it is committed. Dynamic entities consist of one stable configured AP and privacy-preserving stable tag identities. Tags expose no commands or rendering capabilities.

The only action is a single-target, read-only `refresh`. The runtime does not expose telemetry injection, event injection, arbitrary URLs, redirects, proxy routing, tag commands, rendering, firmware operations, or destructive administration.
