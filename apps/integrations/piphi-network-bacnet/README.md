# piphi-network-bacnet

Bounded, read-only BACnet/IP integration for a Kaiterra SenseEdge Mini SE-200 or SE-200P.

## Qualification status

Release qualification uses deterministic fixtures plus a real BACpypes UDP simulator against the exact container image. Physical-device testing is optional follow-up evidence rather than a publication gate. Marketplace governance remains `draft`, `unverified`, and rollout `0`; do not represent simulator results as live-device interoperability evidence.

## Implemented scope

- Requires an explicit IPv4 address, UDP port, BACnet device instance, and local IPv4/CIDR.
- Sends an instance-bounded, unicast `Who-Is` to verify the configured target.
- Verifies Kaiterra vendor ID `1307` and the SenseEdge Mini model profile.
- Reads an allowlist of Device metadata and the bounded `Object_List`.
- Reads only installed, fixed-instance Analog Input objects documented by Kaiterra's September 2026 PICS.
- Normalizes recognized engineering units and omits unknown unit/object combinations.
- Polls on a bounded interval and supports one read-only `refresh` action.
- Uses host networking so BACnet/IP addresses are not hidden behind container NAT.

## Deliberately excluded

The runtime exposes no property writes, arbitrary properties, raw APDUs, unbounded network scans, device administration, BBMD mutation, routing, foreign-device registration, BACnet/SC, or MS/TP. COV, alarms, schedules, trend logs, and other vendors remain deferred.

## Configuration

```json
{
  "id": "office-senseedge",
  "host": "192.168.1.50",
  "port": 47808,
  "device_instance": 1234,
  "local_address": "192.168.1.20/24",
  "local_device_instance": 4194000,
  "profile": "kaiterra_sensedge_mini",
  "poll_interval_seconds": 60
}
```

The local client instance must differ from the SenseEdge device instance. All active configurations in one runtime must share the same local address and client instance.

## Local checks

```bash
pdm install --check
pdm run pytest
pdm run python scripts/validate.py
docker build -t piphi-network-bacnet:local .
pdm run python scripts/qualify_release_image.py --image piphi-network-bacnet:local
```

Run the container with host networking for real BACnet/IP access:

```bash
docker run --rm --network host piphi-network-bacnet:local
```

Official profile sources:

- [Kaiterra SenseEdge Mini BACnet manual and PICS](https://support.kaiterra.com/sensedge-mini-bacnet-user-manual)
- Minimum BACnet firmware: `2.1.1`
- PICS baseline reviewed: September 2026, application software `2.6.5`, protocol revision `14`
