# Privacy and credentials

- Treat the Steam Web API key as a password. Do not commit, log, or share it.
- Use a key belonging to the person configuring the integration and request only data they are authorized to access.
- Steam privacy settings can hide profile, recent-game, and owned-library data. PiPhi reports that data as unavailable and does not bypass those settings.
- Delete the PiPhi configuration to remove the locally retained credential, and revoke the key through Steam if it may have been exposed.
- The runtime holds the key only as a masked in-memory secret and never returns it in state, events, telemetry, entities, or diagnostics.
- Diagnostics contain health reason codes and timestamps, not persona names, game history, profile URLs, avatars, or state snapshots.
- Public state is limited to the capabilities advertised by the integration. Raw recent-game lists, profile URLs, avatars, and last-logoff timestamps are discarded after normalization.

See the [Steam Web API Terms of Use](https://steamcommunity.com/dev/apiterms) and [Valve Privacy Policy](https://store.steampowered.com/privacy_agreement/).
