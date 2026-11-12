# Registry migration

The initial migration covers the 66 entries currently published by the PiPhi registry: 45 integrations, 11 platform services, and 10 widgets.

Migration is intentionally staged:

1. Inventory every published entry and source repository.
2. Import source history into an isolated app directory.
3. Validate manifests, tests, builds, and artifact metadata.
4. Add path-scoped CI and independent release automation.
5. Publish a namespaced monorepo tag and immutable artifact.
6. Update the registry source URL, manifest path, and ref through review.
7. Archive the old repository only after the cutover is verified.

Old repositories must not be deleted. They preserve existing tags, releases, issue history, links, and rollback artifacts.

`inventory.json` is generated from the public registry by `scripts/build_migration_inventory.py` and records the planned destination for every source repository.
