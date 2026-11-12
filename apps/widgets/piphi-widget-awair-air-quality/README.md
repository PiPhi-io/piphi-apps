# Awair Air Quality widget

Independent PiPhi Widget SDK package for `awair-element-local-api`.

It provides a native, read-only overview of the Awair score, carbon dioxide, particulates, VOC, temperature, and humidity. The widget is implemented in `src/widget.ts` against `piphi-network-widget-sdk`; `npm run build` bundles the SDK and widget into `assets/awair-widget.mjs` for the sandbox host.

The package is versioned and released independently; the PiPhi registry links it to compatible Awair integrations and Core installs it as an automatic companion.

## Validate

```bash
npm ci
npm run validate
```

Release tags use `v<package-version>`. GitHub Actions signs the immutable archive with PiPhi's first-party widget publisher key and attaches the archive, signed manifest, and checksums to the release.
