# Privacy and runtime requirements

This integration requires the managed `piphi-zwave-js-sidecar` runtime. It does
not access the serial controller directly. The sidecar token and PiPhi runtime
identity are credentials and must be injected as secrets rather than stored in
configuration or included in support output.

Only `GET /health` is public. Entity, state, event, discovery, diagnostics,
configuration, telemetry, contract, and command routes require the bound PiPhi
runtime identity. The integration consumes sanitized sidecar snapshots and
events and never exposes controller paths, security keys, DSKs, raw serial or
NVM data, credentials, or unrestricted Z-Wave values.

Node names, locations, state, device identifiers, and usage telemetry are private
home data. They remain local to the PiPhi runtime and configured Core delivery
endpoints. Logs, diagnostics, and qualification evidence must use redacted test
data and must not include private household device data.
