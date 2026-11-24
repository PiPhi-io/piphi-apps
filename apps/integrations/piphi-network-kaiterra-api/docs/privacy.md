# Privacy and diagnostics

This integration sends only allowlisted latest-reading metrics, source timestamps,
and a stable one-way device reference to PiPhi Core. The Kaiterra API key and device
UDID are secret configuration. They are not stored in the runtime registry, entity
metadata, telemetry, events, diagnostics, or logs. Provider metadata is reduced to
display name, model, and firmware version; handshake data, serial numbers, MAC
addresses, region, module records, addresses, and raw responses are discarded.

Kaiterra's `pir` motion value and sound channels can reveal occupancy or activity.
They are deliberately excluded. The integration does not fetch or retain history,
does not expose raw payloads, and keeps only the latest normalized state required for
stale-last-good recovery. Diagnostics contain aggregate counts and timestamps only.

Kaiterra requires the API key in the `key` query parameter. Production transport is
HTTPS-only, request/access logging is disabled in the image, and the runtime installs
query-string and recursive secret redaction. Rotate or revoke the API key in the
Kaiterra dashboard if exposure is suspected.
