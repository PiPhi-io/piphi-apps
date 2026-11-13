# PiPhi Apps CI and release system

## Principles

- PiPhi releases artifacts, not programming languages.
- Every package is independently versioned, published, and rolled back.
- Pull-request jobs receive no release credentials.
- Release credentials belong to protected GitHub environments, not app source.
- OCI tags are convenient labels; immutable digests and attestations are authoritative.
- The registry changes only after a release has produced verifiable evidence.

## App metadata

Every directory immediately below `apps/<category>/` contains `piphi-app.json`.
The contract is defined by `contracts/piphi-app.schema.json` and enforced by
`scripts/validate_apps.py`.

One source directory may publish multiple packages. This supports integrations
that include a tightly coupled widget without forcing both artifacts to share a
version or release tag.

```json
{
  "$schema": "../../../contracts/piphi-app.schema.json",
  "schema_version": 1,
  "slug": "example-device",
  "source": { "imported_from": null },
  "languages": ["rust"],
  "ci": {
    "enforcement": "full",
    "commands": ["cargo test --locked", "cargo clippy --locked -- -D warnings"],
    "build_container": true
  },
  "packages": [
    {
      "id": "example-device",
      "type": "integration",
      "version": "1.0.0",
      "manifest": "manifest.json",
      "artifact": {
        "kind": "oci",
        "context": ".",
        "dockerfile": "Dockerfile",
        "platforms": ["linux/amd64", "linux/arm64"]
      },
      "publishing": {
        "mode": "piphi_managed",
        "environment": "release-ghcr-io",
        "primary": {
          "registry": "ghcr.io",
          "repository": "piphi-io/example-device"
        },
        "mirrors": []
      },
      "release": {
        "tag": "apps/{package_id}/v{version}",
        "commands": []
      }
    }
  ]
}
```

Imported apps initially use `legacy-static`. Their metadata and manifests are
validated by the monorepo job, but they do not consume per-app CI runners and the
central release workflow refuses to publish them. Move one app
to `full`, verify its declared commands, and enable `build_container` before its
first monorepo release. This makes migration explicit instead of silently trusting
dozens of old, repository-specific workflows.

## Pull-request CI

`apps-ci.yml` detects affected app directories. Changes to shared contracts,
scripts, or workflows intentionally select every app. The reusable app workflow
can prepare Python, Node.js, Go, Rust, Java/Kotlin, .NET, Ruby, and PHP toolchains.

These adapters improve linting, tests, and caching. They are not an admission
boundary. A contributor using another language can qualify through a reproducible
OCI `Dockerfile` and the PiPhi runtime contract.

Unknown-language app code executes only in credential-free pull-request jobs.
Release jobs execute only committed code from the protected default branch.

## Independent releases

`release-app.yml` accepts one package ID and one version. It verifies that:

1. the package exists in reviewed metadata;
2. the requested version equals the committed manifest version;
3. CI enforcement is `full`;
4. the namespaced tag does not already exist;
5. declared tests and qualification pass.

The resulting tag is:

```text
apps/<package-id>/v<version>
```

OCI releases build once with BuildKit, produce an SBOM and provenance, push to
the configured registry, and record the immutable digest. Widget and binary
packages use reviewed release commands and attach checksummed archives to the
namespaced GitHub release.

## Registry-neutral image publishing

The primary target is split into a registry host and repository namespace:

```json
{
  "registry": "ghcr.io",
  "repository": "piphi-io/example-device"
}
```

This works with Docker Hub, GHCR, ECR, Artifact Registry, ACR, and compatible OCI
registries. Configuration never contains credentials. A protected GitHub
environment named by `publishing.environment` provides:

- `OCI_REGISTRY_USERNAME` as an environment secret;
- `OCI_REGISTRY_TOKEN` as an environment secret.

PiPhi-managed packages use GHCR as their primary target. GHCR uses the workflow's
short-lived `GITHUB_TOKEN`, while GitHub OIDC supplies the identity used for
provenance and attestations. Other registries remain supported for external
packages and approved mirrors; they should use OIDC where supported, with the
username/token pair retained as the compatibility path.

Mirrors are optional. Each mirror must preserve the same image content, and the
release evidence must record every resulting digest. A non-GHCR mirror needs its
own approved authentication integration before it is enabled.

## Community-managed images

`publishing.mode: external` means PiPhi verifies rather than owns publication.
Admission requires namespace ownership, immutable digest, signature, provenance,
SBOM, supported architectures, retention expectations, and permission to mirror
when a PiPhi-controlled fallback is desired. External pull requests never receive
PiPhi registry credentials.

## Registry cutover

For each package:

1. enable full CI and complete a dry-run release;
2. publish the namespaced artifact and retain its evidence;
3. verify installation and update behavior in PiPhi Core;
4. update `repo_url`, `manifest_path`, `ref`, documentation URLs, image digest,
   and mirrors in the registry through review;
5. archive the old repository only after rollback verification.

The current production registry remains unchanged until these steps pass.
