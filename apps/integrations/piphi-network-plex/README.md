# PiPhi Network Plex

Managed Plex media-provider integration for PiPhi Network Core. One runtime can maintain multiple Core account configurations and multiple Plex servers per account.

## Delivered phases

### Phase 1 — Runtime foundation

- Runtime SDK lifecycle, config snapshot sync, health, diagnostics, entities, commands, telemetry, and behavior metadata
- Plex account-token discovery plus direct server URL/host configuration
- Stable provider instance identity: `{core_config_id}:{plex_machine_identifier}`
- Independent health and failure isolation for every connection

### Phase 2 — Media provider

- Provider instances and libraries
- Recently Added and On Deck hubs
- Library browsing and server search
- Normalized movies, episodes, tracks, and artwork
- Server-side authenticated artwork delivery

### Phase 3 — Core and UI

- Authenticated Core provider gateway
- Plex source in the existing Media Library page
- Multi-server selection, library navigation, search, item details, and dashboard-widget handoff

See [docs/architecture.md](docs/architecture.md) for ownership and extension contracts.

## Configuration

Provide a Plex token. Leave `host` and `base_url` empty to discover every server available to the account, or provide one of them to pin the configuration to a specific server.

```json
{
  "id": "plex-account-home",
  "token": "example-token",
  "include_remote_servers": true,
  "poll_interval_seconds": 15
}
```

Tokens are retained only in Core-managed configuration and runtime memory. Provider responses, entities, state, diagnostics, and browser URLs never contain the token.

### Simulator parity

Set `simulation_mode` to `true` to create a deterministic Plex server without a
Plex token. Simulation changes only the upstream transport: discovery, sessions,
libraries, search, hubs, item resolution, artwork, and actions still pass through
the same provider service, normalization, Core gateway, and widget bundles used
by a live Plex server. This keeps dashboard behavior and light/dark theming
identical between simulator and real configurations.

```json
{
  "id": "plex-simulator",
  "simulation_mode": true
}
```

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_plex.main:app --reload --port 8091
pdm run pytest
pdm run python scripts/validate.py
```

Provider routes:

- `GET /provider/instances`
- `GET /provider/{instance_id}/collections`
- `GET /provider/{instance_id}/items`
- `POST /provider/{instance_id}/resolve`
- `POST /provider/{instance_id}/actions`
- `GET /provider/{instance_id}/asset`

## Add Plex to a Core dashboard

1. Open Media Library, choose Plex, and select a server and library or search.
2. Select an item and click **Add to dashboard**.
3. Choose an editable dashboard, then click **Customize widget**.
4. Use Core's existing external-widget editor to adjust the title, settings,
   layout, and visibility. Save, then use **Open dashboard** to view the card.

The overview preserves server, library/search, and selected-item context. Media
details are a saved snapshot, not a live library feed; the overview's account
telemetry continues updating live. No playback capability is added by this flow.
The installed Plex widget package must be ready in Core's capability catalog.
Saving appends a Plex section and uses the latest dashboard revision; conflicts
keep the draft available for retry instead of overwriting concurrent edits.

The widget-rendering regression test runs without a Plex account or JS packages:

```bash
node --test tests/plex_widget.test.mjs
```

## Live Widget SDK packages

The integration includes three independently selectable packages built with
`piphi-network-widget-sdk` 0.5.0:

- **Recently Added**: a live list from the selected server.
- **Continue Watching**: the Plex `/hubs/continueWatching` hub, including watch
  progress. This is distinct from the older On Deck endpoint; see the
  [Plex Media Server API](https://developer.plex.tv/pms/).
- **Plex Search / Library**: a saved server-wide search, or a library listing
  when the search query is empty. Search takes precedence over the library ID.

In Core Media Library, choose a server and select **Create live widget** (works
even with no media results). Pick a dashboard and widget type, then customize
the title, item count (1–24), refresh interval (15–300 seconds), summaries, layout,
and visibility. The builder recommends a package from the selected source.
Existing overview cards keep their previous snapshot behavior.

These are read-only media lists, not playback players. They render titles,
metadata, summaries, and watch progress without requesting Plex directly.
Empty, denied, offline, retrying, and stale-data states are handled; failed
refreshes retain previous results and back off up to five minutes.

The packages use the SDK's generic `host.request("host.queryMedia")` extension.
Deploy the matching Core host bridge: SDK 0.3.0 alone does not add media access to
older Core versions. Core requires the package's `host.queryMedia` permission,
accepts no iframe-supplied query parameters, and reads only the saved
configuration/server and settings. Requests are coalesced for five seconds and
Core's authenticated provider gateway enforces configuration ownership.

Build and test the self-contained bundles (SDK imports are bundled, not left as
bare browser imports):

```bash
npm ci --ignore-scripts
npm run build
npm test
```

The build refreshes all three package manifests, SRI digests, previews, and
integration catalog entries. Generated bundles must be shipped with the runtime;
Docker serves them from `/widgets`. Override `PIPHI_WIDGETS_PATH` for other layouts.
Core exposes installed bundles through its public widget-artifact route (code
and previews only), with anonymous CORS for sandboxed modules and SHA-384
verification against the installed manifest. Artifact paths are allowlisted and
responses are size-limited. Plex media data still uses the authenticated gateway.

## Docker

For registry submission, release validation, and manual image publication, see
[the release guide](docs/releasing.md). The initial registry entry is a draft
with zero rollout; widgets are declared by the integration manifest.

```bash
docker build -t docker.io/piphinetwork/piphi-network-plex:0.1.1 .
docker run --rm -p 8091:8091 docker.io/piphinetwork/piphi-network-plex:0.1.1
```
