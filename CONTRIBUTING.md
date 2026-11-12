# Contributing to PiPhi Apps

Thank you for helping expand the PiPhi ecosystem.

Start with [the app contribution guide](docs/contributing-apps.md). It explains
the language-neutral OCI path, `piphi-app.json`, CI enforcement, and publishing
destinations.

## Contribution flow

1. Fork this repository and create a focused branch.
2. Add or update one app under the appropriate `apps/` directory.
3. Keep the app manifest, runtime registrations, behaviors, widgets, tests, and release metadata consistent.
4. Add tests for meaningful success, failure, authorization, redaction, retry, and offline behavior.
5. Open a pull request using the repository template.
6. Resolve automated validation and maintainer review before merge.

Direct pushes to `main` are not the contribution path.

## App boundaries

Each app must be independently buildable, testable, versioned, and releasable. Do not import another app's private source tree or rely on files outside the app directory unless they are part of an explicitly supported shared contract.

SDKs are consumed as released dependencies and are not developed in this repository.

Repository-specific workflows under an app directory are not accepted. The
trusted root workflows detect the app and execute its reviewed metadata instead.

## Required app metadata

An app contribution must include:

- a PiPhi manifest or Widget SDK package manifest;
- a README with setup, permissions, and supported capabilities;
- an explicit license or a preserved license from its original source;
- maintainer ownership information;
- tests and reproducible build instructions;
- release metadata with an independent semantic version.

New registry listings begin as drafts. Merging source code into this repository does not automatically publish or promote a listing.

## Security

Never commit credentials, tokens, private keys, customer data, or device identifiers. Mutating operations must be opt-in and narrowly allow-listed. Logs, state, telemetry, events, and diagnostics must redact secrets.

Report vulnerabilities privately through the PiPhi organization security process rather than a public issue.
