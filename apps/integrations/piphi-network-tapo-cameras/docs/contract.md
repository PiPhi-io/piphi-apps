# Runtime contract

The runtime exposes one dynamic camera entity for each verified configuration.
Only `GET /health` is public. Every other route requires
`X-PiPhi-Integration-Token`, unless the explicit local-test bypass is enabled.

## Configuration

Required fields are `host`, `username`, and `password`. Optional fields are
`alias` and `poll_interval_seconds` (60–3600). Unknown fields fail validation.
The password is held only in memory and excluded from registry entries, state,
events, telemetry, diagnostics, and discovery output.

Targeted `POST /discover` requires the same three credential fields and returns
only an opaque hashed device identity and sanitized display metadata.

## Entity state

Implemented fields:

- `connected`, `available`, and `stale`
- `privacy_mode` and inverse `camera_enabled`, when lens-mask state exists
- `signal_strength` in dBm, when supplied by the camera
- `last_success_at`

On failure, the last observation is retained and marked stale. Public error
categories are bounded to authentication, timeout, unreachable, unsupported,
battery unsupported, child/hub unsupported, identity mismatch, and missing
stable identity. Raw provider exceptions are not returned.

## Command

`POST /command` accepts only `refresh` under
`automation.runtime.command.v1`. It performs a read and has no setter side
effects. All mutating and arbitrary command names fail closed.

## Explicit exclusions

There are no media, snapshot, stream URL, detection, PTZ, alarm, light, pairing,
firmware, privacy mutation, factory-reset, or arbitrary transport surfaces.
