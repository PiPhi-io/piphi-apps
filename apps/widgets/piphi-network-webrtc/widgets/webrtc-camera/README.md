# PiPhi WebRTC camera widget

A read-only PiPhi dashboard card for low-latency camera playback. The widget
creates a receive-only browser peer connection and delegates signaling to the
trusted PiPhi host. Its keyboard-accessible controls provide mute/unmute,
in-card snapshots, digital zoom, picture-in-picture, fullscreen, and reconnect.

## Host contract

The bound integration must expose a `camera_stream` capability. The package
requires the `camera` permission and calls two protocol-v1 host extensions:

- `host.openCameraSession({ sdp, type: "offer", includeAudio })` returns
  `{ sdp, sessionId, expiresAt? }`.
- `host.closeCameraSession({ sessionId })` releases the brokered session.

Core must derive the camera target from the saved widget binding. It must not
accept a device URL, config ID, capability ID, or credential supplied by iframe
code. The response contains only an SDP answer and opaque session metadata.

## Security defaults

- sandboxed iframe with `allow-scripts` only;
- no direct `connect-src` destinations;
- no camera credentials, signaling URLs, cookies, or browser storage;
- receive-only media transceivers;
- audio is disabled by default and starts muted when enabled;
- snapshots remain inside the widget and are not uploaded or downloaded;
- broker errors are sanitized before display.

## Develop

From the repository root, run `npm install`, followed by `npm test`, `npm run
build`, `npm run validate`, and `npm run conformance`.
