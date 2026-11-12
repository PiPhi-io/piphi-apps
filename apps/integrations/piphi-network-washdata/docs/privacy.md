# Privacy notes

## Data handled

WashData processes appliance identifiers, cycle state, program information, estimates, energy or cost readings, and maintenance observations.

Credentials are used only for the configured upstream service or device. They
must not be emitted through PiPhi state, telemetry, events, logs, or diagnostics.

## Data flow and retention

The runtime sends only the requests needed to discover devices, refresh state,
or execute an explicitly requested command. PiPhi installations control their
own configuration and retention. This integration does not introduce a separate
PiPhi-operated analytics or advertising data flow.

Refer to the configured upstream provider's privacy terms for data the provider
already stores and processes. Remove the integration configuration to stop new
requests and delete locally retained credentials according to the PiPhi host's
configuration controls.
