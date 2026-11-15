# Piphi Network Modbus

PiPhi Modbus runtime for reviewed semantic profiles over local Modbus TCP, UDP,
RTU-over-TCP, certificate-validated TLS, and the authenticated RTU/ASCII
sidecar. Profiles declare exact units, areas, addresses,
types, byte/word order, scaling, bounds, reviewed enums, bit masks, and
writability. The runtime reads
coils, discrete inputs, input registers, and holding registers; exposes typed
entities; and permits only named, bounded writes with protocol confirmation and
read-back.

For TCP, set `host` to a private/local IP (optionally `:port`) or
`.local`/`.lan` name and provide `points`. Compatible adjacent points are read
in one bounded request without crossing unit or data-area boundaries. The
connection is reused, serialized, and re-established once after a failed read.
An unsuccessful block marks only its points unavailable. Modbus TCP is
unencrypted, so use only a trusted local network.

Set `transport` to `udp` for MBAP datagrams or `rtu_over_tcp` for CRC-framed
RTU messages over a persistent TCP stream. Set it to `tls` for Modbus Security
framing on port 802; `tls_ca_certificate` is mandatory and hostname validation
uses `tls_server_name` (or the configured host). TLS never falls back to clear
TCP. Profile reads retry once after transport failure; writes remain single
attempt and always require confirmation plus read-back.

Numeric profiles support signed and unsigned 16-, 32-, and 64-bit integers,
`float32`, and `float64`. Profiles may also define bounded ASCII or UTF-8 fixed
strings, reviewed enum labels, and read-only bitfields. All multi-register types
support `ABCD`, `BADC`, `CDAB`, and `DCBA` byte/word policies. Writable numeric
points become number entities, writable enums become selects, and writable
booleans become switches.

Reviewed profiles may compose those points into light, fan, cover, and climate
entities. Each state role references a stable point ID. Each composite command
references one writable point and either a fixed reviewed value or one named
argument such as brightness, position, mode, fan speed, or temperature. Runtime
callers cannot override the point, unit, address, function, or confirmation
policy.

Polling can be split into reviewed point groups with independent intervals and
priorities. An interval of `0` disables periodic reads while keeping manual
refresh available. The scheduler adds bounded jitter and exponential failure
backoff; TCP and grouped RTU reads support an explicit inter-message delay.
Diagnostics report poll latency and outcomes, stale-point counts, retries,
timeouts, reconnects, queue high-water marks, and per-unit last-success health
without exposing raw frames, credentials, or serial paths.

Profiles may also declare named FC15 commands over ordered contiguous writable
coils. The unit, addresses, values and read-back policy are immutable at
invocation. Steady commands must declare an idempotent policy. Pulses must
declare a non-idempotent policy, bounded duration and fixed reset values; they
are never retried automatically.

The original `register_address` plus optional `unit_id` configuration remains
supported for compatibility as a read-only unsigned holding-register entity.

## Managed serial sidecar

Installing this integration also installs the shared
`piphi-modbus-rtu-sidecar` service in the compatible `0.6.x` line. The service
has no host-published port, runs in production authentication mode, and receives
`/dev/serial` access for explicitly configured RTU or ASCII ports. The parent reaches it
only on the internal service network at
`http://piphi-modbus-rtu-sidecar:4212`.

PiPhi Core injects the internal token used by both containers. Profiles and
configuration never contain that token. Network configurations do not send work
to the sidecar; the shared service remains idle until an RTU or ASCII profile is
applied. ASCII frames use strict hex decoding, CRLF delimiters, LRC validation,
and the same bounded profile request surface as RTU.

The bundled declarative Widget SDK card displays the raw register value and
offers details/history. A Modbus TCP simulator can serve a documented register
at the configured address for end-to-end testing; the same configuration and
read path work with a real device.

## Run locally

```bash
pdm install -G dev
pdm run uvicorn piphi_network_modbus.main:app --reload --port 4222
pdm run pytest
pdm run python scripts/validate.py
```

The runtime listens on port `4222` by default and exposes the common PiPhi runtime route contract:

- `GET /health`
- `GET /diagnostics`
- `POST /discover`
- `POST /config`
- `POST /config/sync`
- `POST /deconfigure`
- `POST /deconfigure/{config_id}`
- `GET /state`
- `GET /contract`
- `GET /entities`
- `GET /events`
- `POST /events/device/{config_id}/example`
- `POST /telemetry/example`
- `POST /telemetry/device/{config_id}/example`
- `POST /command`

## Capability coverage

`capability-catalog.json` inventories Modbus transports, units, profiles,
coils, discrete inputs, registers, types, diagnostics, polling quality, and a
managed RTU gateway boundary. Each candidate is implemented, planned, or
excluded, and contract tests prevent unsupported register operations from
being advertised.

Semantic profiles, typed FC01/02/03/04 reads, contiguous batching, TCP/TLS/UDP/
RTU-over-TCP/serial RTU/serial ASCII framing, bounded reconnect, and constrained
FC05/06/15/16 writes are implemented. Arbitrary addresses, raw PDUs, broadcasts,
and untrusted profiles remain excluded.

## Manifest

`manifest.json` is a starter manifest. Before publishing, update:

- `image`
- `version`
- capabilities and commands
- config fields and identity fields
- entity metadata

## Docker

```bash
docker build -t ghcr.io/piphi-io/piphi-network-modbus:0.8.0 .
docker run --rm -p 4222:4222 ghcr.io/piphi-io/piphi-network-modbus:0.8.0
```
