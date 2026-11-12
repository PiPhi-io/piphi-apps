# piphi-rtl433-bridge

Small bridge process that runs `rtl_433`, reads decoded sub-GHz radio packets,
and forwards them to a PiPhi runtime such as `piphi-network-433mhz`.

## Why this project exists

`rtl_433` is already very good at radio decoding.

PiPhi still needs a tiny adapter layer that can:

- run `rtl_433`
- read one JSON packet at a time
- forward packets to the runtime endpoint
- support common receive bands such as 315 MHz, 433.92 MHz, 868 MHz, and 915 MHz
- retry if the runtime is temporarily unavailable
- keep the main runtime simpler and more beginner-friendly

That is what this bridge does.

## Mental model

- `rtl_433` is the radio decoder
- this bridge is the adapter
- the main PiPhi runtime is the integration brain

The bridge does not publish PiPhi telemetry itself.
It only forwards decoded packets to the runtime's `/ingest/rtl433` route.

It can also publish the same decoded packets to shared MQTT source topics so
multiple integrations can subscribe without fighting over the SDR device.

## Environment variables

- `RUNTIME_INGEST_URL`
  Default: `http://127.0.0.1:8090/ingest/rtl433`
- `HTTP_FORWARD_ENABLED`
  Default: `true`
- `RADIO_BAND`
  Default: `433mhz`
  Friendly presets: `315mhz`, `433mhz`, `868mhz`, `915mhz`, `custom`
- `CUSTOM_FREQUENCY`
  Optional. Required only when `RADIO_BAND=custom`, for example `344.975M`
- `RTLSDR_DEVICE`
  Default: `auto`
  USB receiver selector. Leave as `auto` unless multiple SDR receivers are attached.
- `RECEIVER_GAIN`
  Default: `auto`
  Signal sensitivity. Leave as `auto` for normal use.
- `RTL433_PROTOCOLS`
  Optional comma-separated rtl_433 protocol IDs. Leave blank for automatic decoding.
- `RTL433_COMMAND`
  Advanced override. If set, this raw command is used and the friendly radio options above are ignored.
- `FORWARD_TIMEOUT_SECONDS`
  Default: `10`
- `RETRY_DELAY_SECONDS`
  Default: `5`
- `STARTUP_DELAY_SECONDS`
  Default: `2`
- `BRIDGE_EXTRA_HEADERS_JSON`
  Optional JSON object of extra headers to send with each forwarded packet
- `MQTT_ENABLED`
  Default: `false`
- `MQTT_HOSTNAME`
  Default: `127.0.0.1`
- `MQTT_PORT`
  Default: `1883`
- `MQTT_USERNAME`
  Optional username
- `MQTT_PASSWORD`
  Optional password
- `MQTT_CLIENT_ID`
  Optional client identifier
- `MQTT_QOS`
  Default: `0`
- `MQTT_TOPIC_ROOT`
  Default: `piphi/sources/rtl433`

## Local development

Install dependencies:

```bash
pdm install -G dev
```

Run the bridge:

```bash
pdm run bridge run
```

Run the local service used by PiPhi discovery:

```bash
uvicorn piphi_rtl433_bridge.service:app --host 127.0.0.1 --port 8091
```

The service exposes `GET /health` and `POST /radio/config`. The configuration
route accepts `frequency`, `rtlsdr_device`, `receiver_gain`, and
`rtl433_protocols`, then safely restarts the managed `rtl_433` process. The
container binds this API to loopback only.

Print the resolved bridge config without starting anything:

```bash
pdm run bridge print-config
```

Ping the runtime ingest endpoint:

```bash
pdm run bridge ping-runtime
```

Example custom run command:

```bash
pdm run bridge run \
  --runtime-ingest-url "http://127.0.0.1:8090/ingest/rtl433" \
  --radio-band 915mhz \
  --receiver-gain auto \
  --header "X-PiPhi-Bridge=true" \
  --log-level DEBUG
```

Advanced raw `rtl_433` override:

```bash
pdm run bridge run \
  --rtl433-command "rtl_433 -F json -M time:unix -f 433.92M"
```

MQTT-only collector mode:

```bash
pdm run bridge run \
  --no-http-forward-enabled \
  --mqtt-enabled \
  --mqtt-hostname "127.0.0.1" \
  --mqtt-topic-root "piphi/sources/rtl433"
```

Dry run without launching `rtl_433`:

```bash
pdm run bridge run --dry-run
```

You can still use environment variables if you prefer:

```bash
RUNTIME_INGEST_URL="http://127.0.0.1:8090/ingest/rtl433" \
RADIO_BAND="915mhz" \
pdm run bridge run
```

## Docker

Build:

```bash
docker build -t piphi-rtl433-bridge .
```

Run:

```bash
docker run --rm \
  --network host \
  --privileged \
  --device /dev/bus/usb:/dev/bus/usb \
  -e RUNTIME_INGEST_URL="http://127.0.0.1:8090/ingest/rtl433" \
  piphi-rtl433-bridge
```

If you want to inspect the SDR device inside the container while debugging, `usbutils` is included so you can run:

```bash
docker run --rm \
  --network host \
  --privileged \
  --device /dev/bus/usb:/dev/bus/usb \
  piphi-rtl433-bridge lsusb
```

## Notes

- This bridge is Linux-first because `rtl_433` sidecar containers fit that path best.
- The bridge keeps retrying packet delivery if the runtime is temporarily unavailable.
- If you later add auth between the helper and runtime, use `BRIDGE_EXTRA_HEADERS_JSON`.
- The image includes `rtl_433`, `rtl-sdr`, `usbutils`, and `tini` so it is better suited for real RTL-SDR helper use.

## MQTT Topic Contract

When MQTT publishing is enabled, the bridge publishes:

- all decoded packets to `piphi/sources/rtl433/packets`
- model-specific packets to `piphi/sources/rtl433/models/<model>/packets`

Each MQTT message is a JSON envelope with:

- `source`
- `received_at`
- `model`
- `device_hint`
- `packet`
