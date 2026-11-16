# Privacy notes

## Data handled

This integration sends only a configured bidding zone, currency, and market
date to a public Nord Pool portal backend. It does not request or accept account
credentials. The returned values are wholesale bidding-area prices, not a
household tariff, bill, tax calculation, or network charge.

Credential and endpoint-override fields are rejected by configuration.

## Data flow and retention

The runtime sends only the requests needed to discover devices, refresh state,
or execute an explicitly requested command. PiPhi installations control their
own configuration and retention. This integration does not introduce a separate
PiPhi-operated analytics or advertising data flow.

Refer to Nord Pool's terms and privacy information for requests received by its
portal. Remove the integration configuration to stop new requests.
