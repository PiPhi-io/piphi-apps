# Privacy notes

## Data handled

This integration sends caller-selected product and tariff codes to Octopus
Energy's public tariff endpoint. It does not request or accept an account API
key, account identifier, meter identifier, consumption, billing, or payment
data. Product and tariff codes select public prices and do not prove the
caller's household tariff agreement.

Account credential and endpoint-override fields are rejected by configuration.

## Data flow and retention

The runtime sends only the requests needed to discover devices, refresh state,
or execute an explicitly requested command. PiPhi installations control their
own configuration and retention. This integration does not introduce a separate
PiPhi-operated analytics or advertising data flow.

Refer to Octopus Energy's terms and privacy information for requests received by
its public API. Remove the integration configuration to stop new requests.
