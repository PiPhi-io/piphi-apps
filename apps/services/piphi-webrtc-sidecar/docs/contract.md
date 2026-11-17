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

Only `GET /health` is public for container liveness. Every diagnostics, contract, status, and
session route requires the Core-issued bearer identity and production fails closed if it is absent.

- `GET /health`
- `GET /diagnostics`
- `GET /contract`
- `GET /v1/camera-media/status`
- `POST /v1/camera-media/sessions`
- `PUT /v1/camera-media/sessions/{session_id}/keepalive`
- `DELETE /v1/camera-media/sessions/{session_id}`

Sessions expire after their requested idle timeout. Core renews active viewers through the
authenticated keepalive endpoint and explicitly closes sessions when viewing ends. Audio is
disabled unless the offer requests it; requested FFmpeg relay audio is normalized to Opus for
browser WebRTC compatibility.
Session SDP responses are non-cacheable. A source must pass a bounded FFprobe video probe before
go2rtc signaling begins; probe and child-process failures propagate as degraded or unavailable
states instead of optimistic readiness.

The service intentionally has no discovery, config, entity, state, event, or device-command
endpoints. Those belong to the camera integration that consumes this service.
