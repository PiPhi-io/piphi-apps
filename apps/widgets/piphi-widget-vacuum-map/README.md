# PiPhi Vacuum Map Widget

An interactive, capability-scoped Widget SDK card for robot-vacuum maps,
position, cleaning paths, rooms, battery, errors, and basic controls.

```bash
npm install
npm test
npm run build
npm run validate
npm run conformance
```

The widget uses only the injected host, performs no direct network access, and
allow-lists `start`, `pause`, `return_home`, `locate`, and `clean_rooms`.
