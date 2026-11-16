# Home Assistant camera baseline checklist

This checklist maps the PiPhi camera bundle to the applicable parts of Home Assistant's camera
contract and Integration Quality Scale. It is evidence for engineering review, not Home Assistant
certification. HA-specific repository rules that cannot apply to an external PiPhi runtime are
called out rather than silently counted as passing.

## Implemented baseline

- [x] **Fail-closed secret routes.** Camera source and snapshot routes require runtime identity;
  every Wyze configuration, status, and descriptor route requires a constant-time bearer check in
  production.
- [x] **Private media topology.** go2rtc API/RTSP listeners remain loopback-only. The Wyze RTSP
  listener is exposed only as container port `8554` on the private service network, with no host or
  LAN binding.
- [x] **Connection validation.** New RTSP configuration is accepted only after `ffprobe`
  authenticates and identifies a video stream.
- [x] **Truthful availability.** State comes from a recent source probe, not configuration
  presence. Failures become unavailable, recoveries become available, and transition logs are
  deduplicated.
- [x] **Refresh and stale-state lifecycle.** Manual refresh performs a real probe; periodic probes
  run every 15 seconds by default; deconfiguration removes the state snapshot; no fallback phantom
  camera is returned.
- [x] **Still images.** Core can request one authenticated, bounded JPEG snapshot without exposing
  the source URL.
- [x] **Bounded WebRTC sessions.** Capacity, SDP size, explicit close, shutdown cleanup, failed
  negotiation cleanup, idle expiry, and authenticated activity renewal are implemented.
- [x] **Audio request semantics.** Audio is disabled unless requested. Requested FFmpeg relay audio
  is normalized to Opus rather than blindly copying an incompatible source codec.
- [x] **Wyze process lifecycle.** Configuration waits for authenticated upstream readiness. Child
  exit becomes degraded, retries use bounded backoff and a restart limit, and terminal failure is
  visible in health/status.
- [x] **Reproducible package checks.** Camera Stream declares required central CI, a locked install,
  lint, tests, vulnerability audit, scaffold validation, and multi-architecture container build.
- [x] **Packaged media tools.** A local Camera Stream image build and smoke test verified the
  installed runtime plus FFmpeg/FFprobe 7.1.5. Public CI must reproduce this evidence.
- [x] **Cross-package secret boundary test.** Runtime identity retrieves a source, opens an
  authenticated media session, verifies that no source/credential is returned, and closes and
  cleans up the session.
- [x] **Real packaged go2rtc startup.** The built sidecar image starts pinned go2rtc 1.9.15,
  reports healthy through Docker and `/health`, rejects unauthenticated media status, and reports
  `ready: true` with the production bearer token. Startup allows a bounded 15-second readiness
  window to avoid false failures on slower hosts.
- [x] **Synthetic real-binary media flow.** The packaged go2rtc and FFmpeg create an H.264 test
  source and return a complete JPEG frame. `scripts/smoke_container.py` reproduces process health,
  authentication, readiness, and fixture media checks against a built image.
- [x] **Registry candidate verification.** The complete `linux/amd64` candidate bundle is
  published to GHCR under `:ha-baseline`; each OCI index includes an attestation manifest and was
  pulled and smoke-tested by immutable digest:
  - Camera Stream: `ghcr.io/piphi-io/piphi-camera-stream@sha256:1fede16ef027454960ae037d932bd1df29cfa5e5b0474830fe69113fe7074a34`.
    The packaged runtime reports healthy with authenticated Core binding, and FFmpeg/FFprobe 7.1.5
    are present.
  - WebRTC sidecar: `ghcr.io/piphi-io/piphi-webrtc-sidecar@sha256:3c4dfdd4a83175e124cf8d40669f46bd4f305edc68268ad2d2123a0c7655ae9e`.
    Health, authentication, readiness, go2rtc 1.9.15, and a complete 16,816-byte synthetic JPEG
    media flow pass.
  - Wyze Camera Service: `ghcr.io/piphi-io/piphi-wyze-camera-service@sha256:6531b148aee3b8d68580ded0dc8f80484ea88b75dc6c96e0a8bf1d47c6881dd2`.
    The unconfigured service reports healthy, rejects unauthenticated control requests with 401,
    and accepts the configured production bearer token.
  These are candidate artifacts only: immutable release tags and PiPhi registry catalog versions
  remain unchanged pending public multi-architecture CI, SBOM, provenance, vulnerability, and
  hardware/browser qualification evidence.
- [x] **Coverage gates.** Package test runs enforce current floors of 80% for Camera Stream, 75%
  for the WebRTC sidecar, and 70% for the Wyze service. The measured baselines are 83%, 80%, and
  74% respectively; these floors prevent regression while targeted lifecycle coverage improves.

## Intentionally not required for this baseline

- PTZ
- Two-way audio
- Motion or doorbell events
- Recording and HLS playback
- Camera power controls

These are optional camera capabilities. They must be advertised only if later implemented and
qualified, but their absence does not invalidate the core live-view/still-image baseline.

## Evidence still required before a quality-tier claim

- [ ] Run an immutable public CI build for all three packages and link its test, image, SBOM,
  provenance, and vulnerability evidence.
- [ ] Exercise a representative physical RTSP camera through offer/answer and browser playback.
  Synthetic packaged media flow is verified, but it does not replace camera/network qualification.
- [ ] Qualify representative cameras and browsers for video, requested audio, snapshots,
  disconnect/recovery, concurrent viewers, abandoned sessions, and long-running operation.
- [ ] Qualify LAN and NAT behavior. The current complete-offer/answer signaling contract is valid,
  but trickle ICE and configurable STUN/TURN remain unimplemented and must not be claimed.
- [ ] Build a separate end-user Wyze integration if PiPhi intends to claim a complete Wyze product
  experience. The managed bridge remains infrastructure and does not itself create user entities.

Until the remaining evidence is complete, all three packages should retain `quality_tier:
unrated` and non-GA governance.
