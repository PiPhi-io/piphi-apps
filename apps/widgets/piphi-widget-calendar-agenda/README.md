# PiPhi Calendar & Agenda Widget

A permissionless, read-only Widget SDK card for current and upcoming events.
It normalizes timed and all-day events, groups them in the host timezone, and
handles empty, loading, stale, offline, reconnecting, denied, and error states.

```bash
npm install
npm test
npm run build
npm run validate
npm run conformance
```

The widget uses only the injected PiPhi host. It makes no network requests,
accesses no host storage, and requests no browser or host permissions.
