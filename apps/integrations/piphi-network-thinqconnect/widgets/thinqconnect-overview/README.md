# LG ThinQ overview widget

A first-party PiPhi dashboard widget for `lg-thinq-connect-api`. It renders only capabilities declared by the integration manifest and obtains data exclusively through the PiPhi Widget Host bridge.

## Development

```bash
npm ci
npm test
npm run build
npm run validate
npm run conformance
```

The widget is read-only, sandboxed, network-permissionless, responsive, RTL-aware, theme-aware, and reduced-motion safe.
