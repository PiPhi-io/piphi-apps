# Runtime contract

- Integration ID: `piphi-android-adb-sidecar`
- Kind: `sidecar`
- Private contract: `1`
- Runtime port: Core-assigned `PORT` (`4213` fallback)

All routes except `GET /health` require the configured internal bearer token.
`POST /command` deliberately rejects every generic runtime command.

## Target lifecycle

`POST /config` accepts one local network endpoint. Platform Tools generates and
stores its key only under the private sidecar data volume. A successful authenticated
probe creates a deterministic, non-reversible, serial-derived `target_id` returned by
`GET /v1/adb/snapshot`. Raw hosts, ports, device serials, and ADB key material
are never returned. Reconfiguration is transactional when an existing session
is active. A failed initial probe is rejected and creates no configuration.
The stable target identity excludes host and port, so an address change does not
change device ownership after the same physical target is authenticated.

`GET /v1/adb/mdns` returns at most 32 sanitized, unverified Android 11+
`_adb-tls-pairing` or `_adb-tls-connect` candidates from authoritative Platform
Tools. `POST /v1/adb/pair` accepts one six-digit code, validates the endpoint as
local, passes it once to `adb pair`, and never persists or echoes the code.

## Execute request

`POST /v1/adb/execute` accepts at most 4096 UTF-8 bytes, rejects duplicate and
extra fields, and requires one explicit target lease:

```json
{
  "version": "1",
  "request_id": "request-1",
  "target": {"target_id": "adb-opaque-target"},
  "timeout_ms": 5000,
  "command": {
    "operation": "key_event",
    "key": "home",
    "repeat": 1
  }
}
```

The other operation is an allow-listed property query:

```json
{
  "version": "1",
  "request_id": "request-2",
  "target": {"target_id": "adb-opaque-target"},
  "timeout_ms": 5000,
  "command": {
    "operation": "property_query",
    "properties": ["ro.product.model", "ro.build.version.sdk"]
  }
}
```

Successful operations return a synchronous `completed` response with either
`repeats_completed` or a bounded property map. Public errors are limited to
`unauthorized`, `offline`, `timeout`, `queue_full`, and `unsupported`.

Property reads may reconnect and retry because they are idempotent. Key events
are never replayed after a timeout or connection failure; the response states
that their outcome is unknown.

## Excluded input

The contract accepts no raw shell, argv, endpoint, serial, intent, package,
path, file transfer, forwarding, privilege, or multi-target field. The
sidecar's internal Platform Tools calls are constructed solely from fixed
allow-lists.

The sidecar does not expose PiPhi device entities. Its `/entities` response is
always empty because the parent integration owns television identity and state.
