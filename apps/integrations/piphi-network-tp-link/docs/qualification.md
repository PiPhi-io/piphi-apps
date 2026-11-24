# TP-Link Kasa qualification strategy

This package follows the Home Assistant and python-kasa testing split without
treating fixture coverage as physical certification.

## Layers

1. **Contract tests:** FastAPI/TestKit tests cover authentication, configuration,
   redaction, identity, capability negotiation, polling, stale/recovery behavior,
   removal, restart restoration, and read-only commands.
2. **Deterministic device doubles:** synthetic device and feature objects exercise
   protocol variants and failures without network access. Synthetic models are not
   listed as supported hardware.
3. **Reviewed response fixtures:** a sanitized physical report may become a replay
   fixture only after checking that it contains no address, MAC, device ID, alias,
   credentials, location, or observed telemetry values.
4. **Physical qualification:** opt-in tests connect to one explicitly configured
   device. The first pass performs reads only and records evidence separately from
   CI. Writes require a later model-and-firmware-specific test plan.

This mirrors Home Assistant's mocked-device parametrization, config-flow error and
IP-change coverage, and diagnostics-redaction assertions. It also follows
python-kasa's real-response fixture approach. Unlike python-kasa's full real-device
suite, this harness does not perform state changes by default.

## Read-only physical run

```bash
./scripts/setup_hardware_qualification.sh
```

The wizard prompts for the host and optional credential pair, hides password input,
and runs both qualification commands. For non-interactive setup, copy
`.qualification.env.example` to `.qualification.env`, set mode `0600`, fill it
locally, and run `pdm run python scripts/qualify_hardware.py` followed by
`pdm run pytest -q -m hardware`.

The report is written with mode `0600` under `.qualification-results/`; both the
environment file and results directory are ignored by Git. The report contains a
one-way identity fingerprint, model/version metadata, capability shape, feature
metadata without values, latency bounds, and explicit statements of what was not
verified.

## Promotion rule

A report is evidence for only the observed model, hardware revision, firmware,
transport, and credential mode. It must not enable writes. A later write profile
needs an isolated safe load, original-state capture, bounded inputs, post-write
verification, unconditional restoration, and an operator confirmation for every
consequential action.
