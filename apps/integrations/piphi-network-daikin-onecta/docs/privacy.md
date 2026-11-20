# Privacy notes

## Data handled

Daikin Onecta processes Daikin account identifiers, device state, temperatures, operating modes, and explicitly requested control commands.

PiPhi Core authors the OAuth account subject and access token delivered to this
runtime. The runtime stores only an opaque hash of the subject in operational
state. Tokens and raw provider identifiers must not be emitted through PiPhi
state, telemetry, events, logs, or diagnostics.

## Data flow and retention

The runtime sends only the requests needed to discover devices, refresh state,
or execute an explicitly requested, opt-in target-temperature command. PiPhi installations control their
own configuration and retention. This integration does not introduce a separate
PiPhi-operated analytics or advertising data flow.

Refer to the configured upstream provider's privacy terms for data the provider
already stores and processes. Remove the integration configuration to stop new
requests and delete locally retained credentials according to the PiPhi host's
configuration controls.
