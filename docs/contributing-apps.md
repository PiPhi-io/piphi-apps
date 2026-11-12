# Contributing an app

## Language choice

Use the language and upstream libraries that best fit the integration. PiPhi has
first-class setup adapters for Python, Node.js/TypeScript, Go, Rust, Java/Kotlin,
.NET, Ruby, and PHP. Other languages are welcome when they produce a compliant
OCI image.

An integration or platform service must not depend on a custom privileged GitHub
workflow. Supply a reproducible Dockerfile and expose the PiPhi runtime contract.
The trusted root workflows own publishing and credentials.

## Required files

```text
apps/integrations/example-device/
├── piphi-app.json
├── manifest.json
├── Dockerfile
├── README.md
└── tests/
```

Use `ci.enforcement: full` for new contributions. Declare deterministic commands
that install locked dependencies, test meaningful behavior, lint or type-check
where applicable, and validate the PiPhi contract.

Run before opening a pull request:

```bash
python scripts/validate_apps.py
python scripts/run_app_ci.py apps/integrations/example-device
```

## Publishing destinations

Request an approved OCI registry in `publishing.primary`; do not add credentials.
PiPhi-managed destinations use protected environments. A community-managed image
must be published independently and submitted with immutable, signed evidence.

New registry listings remain drafts with zero rollout until artifact and
marketplace review are complete.
