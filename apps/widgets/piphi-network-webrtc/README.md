# PiPhi WebRTC widgets

Experimental independently installable dashboard widgets for PiPhi Network.

The first package is [`io.piphi.webrtc.camera`](./widgets/webrtc-camera), a
sandboxed camera card that negotiates WebRTC through the trusted PiPhi host. The
widget never receives camera credentials or an arbitrary signaling URL. It
includes optional playback audio, snapshot preview, digital zoom,
picture-in-picture, fullscreen, and reconnect controls.

## Development

Requires Node.js 22 or newer.

```bash
npm install
npm run check
npm test
npm run build
npm run validate
npm run conformance
```

The registry metadata is intentionally a draft with zero rollout until PiPhi
Core implements `host.openCameraSession` and `host.closeCameraSession`, and the
public registry accepts `type: "widget"`.
