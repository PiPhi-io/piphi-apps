# PiPhi Network Bambu Lab

Draft, read-only Bambu printer monitor for explicitly enabled LAN Developer Mode. It subscribes to the printer's MQTT reports on port 8883 and exposes print status, progress, remaining minutes, layers, and nozzle/bed temperatures. It includes a compact read-only Widget SDK 0.5.1 dashboard widget. No print-control commands, cloud login, camera feed, or automatic printer discovery are implemented.

This integration has automated contract and parser tests, but has **not** been validated against a physical Bambu printer. It remains draft and is not promoted to stable. An explicit simulator mode feeds synthetic reports through the same normalization and widget state path; the widget labels simulated data.

## Before configuring

1. Review [Bambu's third-party integration and Developer Mode notice](https://forum.bambulab.com/t/updates-and-third-party-integration-with-bambu-connect/137408/). Enable Developer Mode yourself on a supported printer; PiPhi will never enable it remotely.
2. Obtain the printer's private-LAN IPv4 address, serial number, and LAN access code from the printer. The UI requires an explicit acknowledgement of Developer Mode.
3. Configure only a trusted local network. The runtime rejects public IP addresses, verifies the TLS chain against Bambu's CA, and checks that the certificate identifies the configured printer serial **before** MQTT sends the access code. The bundled CA comes from [OpenBambuAPI's published Bambu CA bundle](https://github.com/Doridian/OpenBambuAPI/blob/main/examples/ca_cert.pem), SHA-256 `168852cde67cd9c7648de5f95b46f7b950d1627966d2da6a968fd9ef9d034910`.

The access code is held in the active MQTT session only; registry entries, /state, events, and telemetry never include it. Job names, filenames, and other private report fields are not retained. On disconnect, the state marks the printer offline; a new partial report does not inherit pre-disconnect values.

## Run and verify

```bash
pdm install -G dev
pdm run pytest
pdm run python scripts/validate.py
npm --prefix widgets/print-status ci
npm --prefix widgets/print-status run build
npm --prefix widgets/print-status test
npm --prefix widgets/print-status run validate
npm --prefix widgets/print-status run conformance
docker build -t piphi-network-bambu-lab:local .
```

Start the runtime with `pdm run uvicorn piphi_network_bambu_lab.main:app --port 4203`. Edit `examples/config.json` with real local values before posting it to `/config`. `/discover` deliberately returns no fabricated devices. The refresh command requests a full report at most once every five minutes, in line with the [OpenBambuAPI MQTT reference](https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md); delta reports arrive through the subscription.

For Core/widget testing without a printer, post `examples/simulator-config.json` to `/config`. It requires no credentials, makes no printer network connection, and updates progress every five seconds. Keep its simulation label visible when assessing the dashboard. Deconfigure it when finished.

To attach that real runtime and its widget source to a running local Core, start the runtime on loopback, then from the Core checkout run:

```bash
pdm run python src/piphi_network_core/seed_simulated_integration.py \
  --manifest-path ../piphi-network-bambu-lab/manifest.json \
  --host 127.0.0.1 --port 4203 --config-profile bambu
```

The Core attach profile creates an explicitly simulated configuration and installs the locally built Widget SDK bundle. It does not change marketplace publication status. The generic integration-test lab profile is only a manifest-contract mock; use the `bambu` profile above when testing this runtime's actual state path.

`capability-catalog.json` distinguishes implemented read-only fields from planned model-specific state and controls. Do not promote or publish this draft until a real X/P/A-series printer and Core widget loading have been tested.
