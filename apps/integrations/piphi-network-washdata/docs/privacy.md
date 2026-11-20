# Privacy notes

## Data handled

WashData receives canonical device identity plus bounded power observations from
PiPhi Core. It derives cycle timestamps, duration, peak power, and energy. It
does not receive provider credentials and does not access producer integration
storage.

## Local retention

The runtime stores the last derived state, opaque Core cursor, and source event
IDs needed for deterministic deduplication in its local SQLite volume. Removing
the configuration deletes that configuration's retained cycle state and event
IDs.

## Data flow

Derived state and events return to the local PiPhi Core using managed-runtime
authentication. There is no PiPhi-operated analytics, advertising, community
profile, or third-party notification flow in this slice.
