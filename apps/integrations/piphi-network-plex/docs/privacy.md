# Privacy and credentials

- Treat the Plex token as a password. The runtime keeps it as a masked in-memory secret and never returns it in state, telemetry, events, entities, or diagnostics.
- Public runtime state contains aggregate server and session counts. Session titles, usernames, player names, and session identifiers are discarded after each sample.
- Media browsing routes return the media metadata requested by an authenticated PiPhi caller. Artwork is brokered through the authenticated runtime and is never exposed as a public upstream URL.
- Library mutations are disabled by default. Enabling them allows only mark watched, mark unwatched, rating, and library scan operations with validated identifiers.
- Remove the PiPhi configuration to discard its locally retained token, and revoke the Plex token if it may have been exposed.

See the [Plex Privacy Policy](https://www.plex.tv/about/privacy-legal/).
