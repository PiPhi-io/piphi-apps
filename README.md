# PiPhi Zigbee2MQTT Network Map

An official PiPhi Widget SDK package for exploring a Zigbee2MQTT mesh. It shows
the coordinator, routers, end devices, directional links, routes, and link
quality without exposing MQTT credentials or broker access to the browser.

## Runtime contract

The widget binds to a Zigbee2MQTT bridge that exposes:

- `zigbee_network_topology`: normalized nodes, links, collection time, and
  route-inclusion state;
- `refresh_network_map`: an explicit, allow-listed command that asks the
  sidecar to perform a raw Zigbee2MQTT network-map scan.

Scans are never automatic. Zigbee2MQTT warns that a scan can make the network
less responsive for between ten seconds and two minutes, so the widget displays
the cached map until a user activates **Scan network**.

## Develop

Requires Node.js 22 or newer.

```bash
npm ci
npm test
npm run build
npm run validate
npm run conformance
```

Run `npm run dev` for the Widget SDK simulator. The package includes loading,
empty, live, stale, offline, reconnecting, denied, and error behavior plus
light/dark, LTR/RTL, reduced-motion, phone, tablet, and desktop support.

## Security

The sandbox has no network CSP access. Its only permission is the
`refresh_network_map` command, which Core revalidates against the selected
bridge. Pairing, removal, renaming, binding, bridge restart, arbitrary MQTT,
and other administrative actions are deliberately excluded.

## License

Apache License 2.0. This is an original PiPhi implementation inspired by the
general product idea of visual Zigbee topology maps; it does not copy source or
assets from third-party unlicensed projects.
