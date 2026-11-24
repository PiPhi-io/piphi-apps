# Runtime contract

Version `0.1.2` exposes the standard health, diagnostics, manual discovery, configuration/sync/removal, entities, state, event-list, UI-config, contract, and command routes declared by `manifest.json`.

Only `/health` is public. Operational routes require `X-PiPhi-Integration-Token`. Manual discovery always returns no devices; configuration supplies the local AP explicitly and must pass a live read before it is committed. Multi-config snapshots are staged and committed atomically. Dynamic entities consist of one stable configured AP and privacy-preserving stable tag identities. Tags expose no commands or rendering capabilities.

The runtime persists hashed inventory and aggregate last-good state to the declared `/var/lib/piphi` volume. Core configuration rehydration combines with this local privacy-safe state so an offline process restart reports stale last-good counts and does not re-emit baseline tag-discovery transitions.

The only action is a single-target, read-only `refresh`. The runtime does not expose telemetry injection, event injection, arbitrary URLs, redirects, proxy routing, tag commands, rendering, firmware operations, or destructive administration.
