# Privacy and runtime access

The sidecar requires an isolated sidecar runtime, direct access to one approved
Z-Wave controller, and persistent storage for the Z-Wave JS cache. Only stable,
explicitly configured controller paths are accepted. The container should be
given access to that device only, not broad host device access.

Security keys are read from environment variables and are never returned by the
API. Controller paths, keys, DSKs, credentials, raw serial frames, binary values,
and NVM data are redacted or excluded from snapshots, events, diagnostics, and
errors. Operational routes require the sidecar bearer token; only `GET /health`
is public. Logs and support evidence must be checked against the same disclosure
rules before sharing.

The sidecar operates locally and does not require internet access at runtime.
Core delivery endpoints and the parent integration receive only bounded,
schema-versioned, sanitized node metadata and events.
