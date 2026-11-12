const ICE_GATHERING_TIMEOUT_MS = 8_000;

export class BrokeredWebRtcSession {
  constructor({ PeerConnection, exchangeOffer, closeSession, onTrack, includeAudio = false }) {
    if (typeof PeerConnection !== "function") throw new Error("WebRTC is not supported by this browser.");
    if (typeof exchangeOffer !== "function") throw new TypeError("exchangeOffer is required.");
    this.peer = new PeerConnection({ bundlePolicy: "max-bundle" });
    this.exchangeOffer = exchangeOffer;
    this.closeSession = closeSession;
    this.onTrack = onTrack;
    this.includeAudio = includeAudio;
    this.sessionId = undefined;
    this.closed = false;
  }

  async start() {
    if (this.closed) throw new Error("Camera session is closed.");
    this.peer.addTransceiver("video", { direction: "recvonly" });
    if (this.includeAudio) this.peer.addTransceiver("audio", { direction: "recvonly" });
    this.peer.addEventListener("track", (event) => {
      const stream = event.streams?.[0];
      if (stream) this.onTrack?.(stream);
    });
    const offer = await this.peer.createOffer();
    await this.peer.setLocalDescription(offer);
    await waitForIceGathering(this.peer);
    const localSdp = String(this.peer.localDescription?.sdp || "");
    if (!localSdp) throw new Error("Browser did not create a WebRTC offer.");
    const answer = await this.exchangeOffer({ sdp: localSdp, type: "offer", includeAudio: this.includeAudio });
    if (!answer || typeof answer !== "object" || typeof answer.sdp !== "string" || !answer.sdp.trim()) {
      throw new Error("Camera broker returned an invalid WebRTC answer.");
    }
    this.sessionId = typeof answer.sessionId === "string" ? answer.sessionId : undefined;
    await this.peer.setRemoteDescription({ type: "answer", sdp: answer.sdp });
    return { sessionId: this.sessionId, expiresAt: answer.expiresAt };
  }

  async close() {
    if (this.closed) return;
    this.closed = true;
    this.peer.close();
    if (this.sessionId && this.closeSession) {
      try { await this.closeSession({ sessionId: this.sessionId }); } catch { /* Expired sessions are already safe. */ }
    }
  }
}

export async function waitForIceGathering(peer, timeoutMs = ICE_GATHERING_TIMEOUT_MS) {
  if (peer.iceGatheringState === "complete") return;
  await new Promise((resolve) => {
    let timer;
    const done = () => {
      clearTimeout(timer);
      peer.removeEventListener("icegatheringstatechange", changed);
      resolve();
    };
    const changed = () => { if (peer.iceGatheringState === "complete") done(); };
    peer.addEventListener("icegatheringstatechange", changed);
    timer = setTimeout(done, timeoutMs);
  });
}
