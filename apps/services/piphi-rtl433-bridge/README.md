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
- keep draining decoder output through a bounded queue during destination faults
- deduplicate exact RF repeats and use a finite exponential retry budget
- keep the main runtime simpler and more beginner-friendly

That is what this bridge does.

## Mental model

- `rtl_433` is the radio decoder
- this bridge is the adapter
- the main PiPhi runtime is the integration brain

The bridge does not publish PiPhi telemetry itself.
It only forwards decoded packets to the runtime's `/ingest/rtl433` route.

It can instead publish decoded packets to shared MQTT source topics. HTTP and MQTT
are mutually exclusive authoritative transports to prevent duplicate delivery.

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
- `MAX_FORWARD_ATTEMPTS` (default `4`)
- `PACKET_QUEUE_SIZE` (default `256`)
- `DEDUP_WINDOW_SECONDS` (default `2`)
- `MAX_PACKET_BYTES` (default `65536`)
- `RTL433_INGEST_TOKEN` (shared secret sent as `X-PiPhi-Bridge-Token`)
- `PIPHI_SERVICE_AUTH_TOKEN` (protects `POST /radio/config`)

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

The service exposes `GET /health` and `POST /radio/config`. Health includes bounded
queue/delivery counters. The configuration
route accepts `frequency`, `rtlsdr_device`, `receiver_gain`, and
`rtl433_protocols`, then safely restarts the managed `rtl_433` process. The
container exposes this API only on its Core-managed service network and requires
the platform service token when configured (and always in production).

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
  --device /dev/bus/usb:/dev/bus/usb \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  -e RUNTIME_INGEST_URL="http://127.0.0.1:8090/ingest/rtl433" \
  piphi-rtl433-bridge
```

## Notes

- This bridge is Linux-first because `rtl_433` sidecar containers fit that path best.
- Delivery is bounded to four attempts by default; exhausted packets are dropped and counted so decoder draining cannot block forever.
- The image builds upstream `rtl_433` revision `f15b67699e902522014e7593d060ad37410eda00` from an archive pinned by SHA-256.
- Raw command overrides are intentionally unsupported. The process always starts from validated frequency, receiver, gain, and decoder-ID fields.
- The image runs as a non-root user with `tini`; host udev/group permissions must grant that user access to the mapped receiver nodes.

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
