import test from "node:test";
import assert from "node:assert/strict";
import manifest from "../widget.manifest.json" with { type: "json" };
import { validateWidgetManifest } from "piphi-network-widget-sdk/manifest";
import { captureVideoSnapshot } from "../src/widget.js";
import { BrokeredWebRtcSession, waitForIceGathering } from "../src/webrtc-session.js";

class FakePeerConnection {
  constructor() { this.iceGatheringState = "complete"; this.listeners = new Map(); this.transceivers = []; }
  addTransceiver(kind, options) { this.transceivers.push([kind, options]); }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  removeEventListener(name) { this.listeners.delete(name); }
  async createOffer() { return { type: "offer", sdp: "v=0\r\no=fake-offer" }; }
  async setLocalDescription(description) { this.localDescription = description; }
  async setRemoteDescription(description) { this.remoteDescription = description; }
  close() { this.closed = true; }
}

test("manifest is publishable and requests only camera playback and fullscreen", () => {
  assert.deepEqual(validateWidgetManifest(manifest).filter((item) => item.severity === "error"), []);
  assert.deepEqual(manifest.security.permissions, ["camera", "fullscreen"]);
  assert.deepEqual(manifest.security.sandbox, ["allow-scripts"]);
  assert.deepEqual(manifest.security.csp.connect_src, []);
  assert.equal(manifest.settings.find((setting) => setting.id === "start_muted")?.default, true);
});

test("session exchanges a receive-only offer through the trusted host", async () => {
  let request;
  const session = new BrokeredWebRtcSession({
    PeerConnection: FakePeerConnection,
    includeAudio: true,
    exchangeOffer: async (offer) => {
      request = offer;
      return { sdp: "v=0\r\no=fake-answer", sessionId: "session-1", expiresAt: "2026-09-06T12:00:00Z" };
    },
  });
  const result = await session.start();
  assert.equal(request.type, "offer");
  assert.equal(request.includeAudio, true);
  assert.match(request.sdp, /fake-offer/);
  assert.deepEqual(session.peer.transceivers, [["video", { direction: "recvonly" }], ["audio", { direction: "recvonly" }]]);
  assert.deepEqual(session.peer.remoteDescription, { type: "answer", sdp: "v=0\r\no=fake-answer" });
  assert.equal(result.sessionId, "session-1");
});

test("close is idempotent and asks Core to release the opaque session", async () => {
  const released = [];
  const session = new BrokeredWebRtcSession({
    PeerConnection: FakePeerConnection,
    exchangeOffer: async () => ({ sdp: "answer", sessionId: "session-2" }),
    closeSession: async (value) => released.push(value),
  });
  await session.start();
  await session.close();
  await session.close();
  assert.equal(session.peer.closed, true);
  assert.deepEqual(released, [{ sessionId: "session-2" }]);
});

test("invalid broker answers fail closed", async () => {
  const session = new BrokeredWebRtcSession({ PeerConnection: FakePeerConnection, exchangeOffer: async () => ({ token: "secret" }) });
  await assert.rejects(session.start(), /invalid WebRTC answer/);
});

test("completed ICE gathering does not wait", async () => {
  await waitForIceGathering(new FakePeerConnection(), 1);
});

test("snapshot capture stays local and preserves the camera frame dimensions", () => {
  const originalDocument = globalThis.document;
  let drawArguments;
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ({ drawImage: (...values) => { drawArguments = values; } }),
    toDataURL: (type) => `data:${type};base64,c25hcHNob3Q=`,
  };
  globalThis.document = { createElement: (name) => {
    assert.equal(name, "canvas");
    return canvas;
  } };
  try {
    const video = { readyState: 2, videoWidth: 1920, videoHeight: 1080 };
    assert.equal(captureVideoSnapshot(video), "data:image/png;base64,c25hcHNob3Q=");
    assert.equal(canvas.width, 1920);
    assert.equal(canvas.height, 1080);
    assert.deepEqual(drawArguments, [video, 0, 0, 1920, 1080]);
  } finally {
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
  }
});
