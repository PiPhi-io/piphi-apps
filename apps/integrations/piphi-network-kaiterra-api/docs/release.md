# Release boundary

Source version `0.1.6` is synchronized across `pyproject.toml`, `piphi-app.json`,
the runtime constant, manifest, image reference, and experience package.

The trusted monorepo workflow owns image publication. Before proposing a source
release, run the package-declared CI commands, root app validation, container build,
and secret scan. The image target is:

```text
ghcr.io/piphi-io/kaiterra-api:0.1.6
```

Do not create or move tags, publish images, synchronize the external registry, or
promote governance from this package workflow. Those are separate reviewed steps
after source PR approval and immutable artifact qualification.
