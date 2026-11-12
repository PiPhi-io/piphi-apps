# Official PiPhi Network GPS Integration

This integration connects USB and NMEA-compatible GPS receivers to PiPhi Network Core through a serial device path.

The runtime now uses the published Node SDK package:

- runtime SDK: `piphi-runtime-kit-node@^0.5.1`
- local test helper during development: `piphi-runtime-testkit-node`

## Supported devices

The integration is currently targeted first at:

- VK162 USB GPS
- VK172 USB GPS

## Likely-compatible devices

The integration is also designed to work with many similar GPS receivers if they expose standard NMEA data over a serial device such as `ttyUSB*`, `ttyACM*`, or similar macOS/Linux serial names.

This commonly includes:

- u-blox based USB GPS receivers
- GlobalSat and similar USB GPS dongles
- BU-353 style USB GPS receivers
- GPS devices connected through common USB-to-serial chipsets such as:
  - Prolific
  - CP210x
  - FTDI
  - CH340

Compatibility depends on the device actually outputting standard NMEA sentences that the integration can parse.

## How device detection works

The integration prefers known GPS VID/PID matches for supported hardware, but it also looks at:

- manufacturer and product strings
- serial metadata
- common GPS-related keywords
- common serial device path patterns

Because of that, devices that are not explicitly hardcoded may still appear in discovery and configuration UI as likely or possible GPS candidates.

## Configuration

You configure the integration by selecting the serial path for the GPS device.

Typical examples:

- `/dev/ttyUSB0`
- `/dev/ttyUSB1`
- `/dev/ttyACM0`

Useful endpoints:

- `GET /discovery`
- `GET /ui`
- `POST /config`
- `POST /deconfigure`
- `GET /state`
- `GET /diagnostics`

## Local development

Install dependencies:

```bash
npm install
```

Build the project:

```bash
npm run build
```

Run the test suite:

```bash
npm test
```

Start the runtime:

```bash
npm start
```

The local test flow uses the Node testkit through a repo-local dev dependency.
The production runtime dependency on `piphi-runtime-kit-node` now comes from npm
instead of a local workspace path.

## Indoor behavior and weak signal handling

GPS reception is always weaker indoors than near a window or outdoors.

This integration now keeps a best-known fix and exposes fix quality details so Core can distinguish between:

- current valid fix
- stale last-known fix
- active searching with no usable fix

When signal quality drops, the integration may continue surfacing the last good coordinates for a limited time while marking them as stale in runtime state and diagnostics.

## Runtime signals you should watch

Important fields exposed through state and diagnostics include:

- `fix_status`
- `fix_quality`
- `position_source`
- `fix_age_ms`
- `satellites`
- `hdop`

General interpretation:

- `fix_quality=excellent|strong|good|usable` means the receiver currently has a usable fix
- `fix_quality=weak` means the receiver has a low-confidence live fix
- `fix_quality=stale` means the integration is using the most recent last-known coordinates
- `fix_quality=searching` means the receiver does not currently have a usable position

## Deployment notes

The container/runtime needs access to the host serial device.

Make sure:

- the GPS receiver is visible on the host
- the selected serial path exists
- the integration runtime has permission to access that path
- the container is running with the expected device/privileged settings from the manifest/runtime configuration

## Troubleshooting

### Device does not appear in discovery

Check:

- the receiver is connected and powered
- the serial path exists on the host
- the device exposes a serial interface
- the adapter is not being claimed by another process

If the device is NMEA-compatible but not explicitly recognized as a known GPS, it may still appear as a possible serial candidate.

### Coordinates are missing or unstable indoors

Try:

- moving the receiver near a window
- giving the receiver more time to acquire satellites
- using a receiver with a better antenna or external antenna
- checking `satellites`, `hdop`, `fix_quality`, and `fix_age_ms` in `/state` or `/diagnostics`

### Coordinates look stale

If `position_source` is `last_known` or `fix_quality` is `stale`, the integration has temporarily lost a fresh live fix and is reporting the most recent valid location it saw.

### Permission problems opening the serial port

Check:

- user/group permissions on `/dev/ttyUSB*` or `/dev/ttyACM*`
- container device access
- whether another service already has the device open

### Unsupported device

A receiver may not work if it:

- does not expose a serial port
- does not output standard NMEA sentences
- requires proprietary initialization before it begins streaming location data

## Notes for integrators

Discovery returns richer device metadata, including confidence and detection reasons, to help diagnose why a device was recognized as a GPS candidate.

The test suite in this repo now exercises happy-path, negative-path, and
edge-case runtime behavior, including runtime-to-Core delivery paths through the
Node testkit.
