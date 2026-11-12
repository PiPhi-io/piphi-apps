# Plex provider architecture

## Ownership

- Core owns account configuration, encrypted secrets, installation lifecycle, user authorization, and browser-facing URLs.
- The runtime owns Plex discovery, live server instances, upstream tokens, API normalization, health, and caches.
- Plex remains authoritative for libraries, metadata, permissions, and playback state.

## Multi-server identity

A Plex machine identifier is only stable inside a Plex server context, while a Core config captures the account and household authorization boundary. Provider instances therefore use:

```text
{config_id}:{machine_identifier}
```

Every item also carries `provider_instance_id` and `provider_item_id`. Core verifies ownership of `config_id` before forwarding any request.

## Request path

```text
Media Library page
  -> authenticated Core /media/providers/plex gateway
  -> managed Plex runtime /provider endpoints
  -> Plex Media Server or plex.tv discovery
```

Runtime asset URLs are rewritten by Core. The browser never receives a runtime address or Plex token.

## Phased extension surface

The provider contract is deliberately additive. Playback targets, playlists, ratings, watched state, sessions, DVR, and webhooks can extend the same instance model without changing the identity or security boundary.
