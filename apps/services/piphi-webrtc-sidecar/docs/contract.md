# Runtime contract

- Stable service ID: `piphi.service.webrtc-sidecar`
- Product name: PiPhi Camera Media Service
- Manifest kind: `platform_service`
- Container deployment mode: `sidecar`
- Service capability: `camera.media.v1`
- Runtime API port: Core allocated through `PORT` (container default `8090`)
- WebRTC media port: TCP/UDP `8555`

Core installs one shared service per home. Camera integrations retain ownership of saved devices,
credentials, and source configuration, and send a source only when opening an authenticated media
session. The source is forwarded to the loopback-only go2rtc control API and is not persisted by
this service after the session is removed. Native RTSP is attempted first; a native `EOF` during
WebRTC negotiation triggers one FFmpeg copy-relay retry through a loopback-only RTSP listener.
Other signaling failures fail closed without changing transport.

## Runtime endpoints

- `GET /health`
- `GET /diagnostics`
- `GET /contract`
- `GET /v1/camera-media/status`
- `POST /v1/camera-media/sessions`
- `DELETE /v1/camera-media/sessions/{session_id}`

The service intentionally has no discovery, config, entity, state, event, or device-command
endpoints. Those belong to the camera integration that consumes this service.
