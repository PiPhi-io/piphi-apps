# PiPhi Apps

Public monorepo for PiPhi Network integrations, platform services, sidecars, and dashboard widgets.

PiPhi SDKs remain in their own repositories. This repository contains apps built with those SDKs and provides one pull-request workflow for official and community contributions.

## Repository layout

```text
apps/
├── integrations/       # Device, cloud, and protocol integrations
├── services/           # Platform services and managed sidecars
└── widgets/            # Standalone dashboard widget packages
contracts/               # App metadata and release contracts
migration/              # Migration inventory and cutover records
scripts/                # Monorepo maintenance tooling
```

An integration repository that also ships tightly coupled widgets stays together under `apps/integrations/`. Standalone widgets live under `apps/widgets/`.

## Registry relationship

[`PiPhi-io/piphi-nework-registry`](https://github.com/PiPhi-io/piphi-nework-registry) remains the published catalog consumed by PiPhi Core. Moving source code here does not immediately change a published listing.

Registry URLs and immutable refs are updated only after an imported app passes validation and has a working monorepo release path. Existing repositories, tags, releases, and container images remain available during migration.

## Independent apps

Sharing a repository does not give all apps one version or deployment. Every app keeps its own:

- manifest and SDK compatibility declaration;
- dependencies and tests;
- maintainers and review ownership;
- package or container artifact;
- semantic version and changelog;
- release and rollback lifecycle.

App release tags use a namespaced form such as `apps/awair-element-local-api/v0.2.0` to prevent collisions between app versions.

Every app directory contains `piphi-app.json`. It declares package IDs, manifests,
language adapters, CI commands, artifact types, and publishing destinations. The
root workflows use this metadata to validate only affected apps and release one
package independently. See [the release architecture](docs/release-system.md).

## Contributing

Contributions are made through pull requests. See [CONTRIBUTING.md](CONTRIBUTING.md) for the required app contract and review process.

## Licensing

Apps retain the license files and notices from their source repositories. There is intentionally no repository-wide software license that overrides an app's existing terms.
