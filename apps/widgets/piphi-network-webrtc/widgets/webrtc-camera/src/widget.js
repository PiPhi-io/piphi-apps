import { getInjectedPiPhiWidgetHost } from "piphi-network-widget-sdk";
import { BrokeredWebRtcSession } from "./webrtc-session.js";

const HEIGHT = 360;
const ZOOM_LEVELS = [1, 1.5, 2, 3];

export async function mountWebRtcCamera({ host, root, PeerConnection = globalThis.RTCPeerConnection }) {
  const [context, settings, permissions] = await Promise.all([
    host.getContext(), host.getSettings(), host.listPermissions(),
  ]);
  const translate = async (key) => host.translate(key).catch(() => key);
  const labels = Object.fromEntries(await Promise.all([
    "title", "waiting", "connect", "reconnect", "connecting", "live", "offline", "denied",
    "mute", "unmute", "snapshot", "snapshotUnavailable", "closeSnapshot", "pictureInPicture", "fullscreen", "zoom",
  ].map(async (key) => [key, await translate(`widget.${key}`)])));
  const configuredTitle = String(settings.title || "").trim();
  const displayTitle = configuredTitle && configuredTitle !== "Live camera" ? configuredTitle : labels.title;

  root.innerHTML = `
    <style>
      :root { color-scheme: light dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
      * { box-sizing: border-box; }
      body { margin: 0; }
      .card { position: relative; min-block-size: ${HEIGHT}px; overflow: hidden; border-radius: 18px; background: #07111f; color: #fff; }
      video { display: block; inline-size: 100%; block-size: ${HEIGHT}px; object-fit: cover; background: #07111f; transform: scale(var(--camera-zoom, 1)); transition: transform 160ms ease; }
      .shade { position: absolute; inset: 0; display: flex; flex-direction: column; justify-content: space-between; padding: 16px; pointer-events: none; background: linear-gradient(180deg, rgba(2,6,23,.68), transparent 35%, rgba(2,6,23,.58)); }
      .top, .bottom { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
      .bottom { align-items: flex-end; }
      h2 { margin: 0; overflow: hidden; font-size: 1rem; text-overflow: ellipsis; white-space: nowrap; }
      .status { display: inline-flex; align-items: center; gap: 7px; padding: 6px 10px; border: 1px solid rgba(255,255,255,.25); border-radius: 999px; background: rgba(2,6,23,.6); font-size: .75rem; }
      .dot { inline-size: 8px; block-size: 8px; border-radius: 50%; background: #f59e0b; }
      .status[data-state="live"] .dot { background: #22c55e; box-shadow: 0 0 0 4px rgba(34,197,94,.18); }
      .status[data-state="error"] .dot, .status[data-state="denied"] .dot { background: #ef4444; }
      button { pointer-events: auto; min-block-size: 38px; padding: 8px 14px; border: 1px solid rgba(255,255,255,.3); border-radius: 10px; background: rgba(15,23,42,.76); color: inherit; font: inherit; font-weight: 700; cursor: pointer; }
      button:focus-visible { outline: 3px solid #60a5fa; outline-offset: 2px; }
      button:disabled { cursor: wait; opacity: .65; }
      .message { margin: 0; max-inline-size: 70%; font-size: .78rem; color: #dbeafe; }
      .controls { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; pointer-events: auto; }
      .icon-button { display: grid; place-items: center; inline-size: 38px; padding: 0; font-size: 1rem; line-height: 1; }
      .zoom-button { inline-size: 44px; font-size: .72rem; }
      .snapshot-view { position: absolute; inset: 0; z-index: 2; display: grid; place-items: center; padding: 16px; background: rgba(2,6,23,.92); pointer-events: auto; }
      .snapshot-view img { display: block; max-inline-size: 100%; max-block-size: 100%; border-radius: 12px; object-fit: contain; box-shadow: 0 16px 40px rgba(0,0,0,.45); }
      .snapshot-close { position: absolute; inset-block-start: 12px; inset-inline-end: 12px; inline-size: 38px; padding: 0; font-size: 1.3rem; }
      [hidden] { display: none !important; }
      @media (max-width: 300px) {
        .shade { padding: 12px; }
        .top { gap: 8px; }
        .status { padding: 5px 8px; }
        .bottom { flex-direction: column; align-items: stretch; gap: 8px; }
        .message { max-inline-size: 100%; }
      }
    </style>
    <main class="card" dir="${escapeAttribute(context.localization?.direction || "ltr")}">
      <video playsinline ${settings.autoplay === false ? "" : "autoplay"} muted aria-label="${escapeAttribute(labels.title)}"></video>
      <div class="shade">
        <div class="top"><h2>${escapeHtml(displayTitle)}</h2><span class="status" data-state="loading" role="status" aria-live="polite"><span class="dot"></span><span class="status-text">${escapeHtml(labels.waiting)}</span></span></div>
        <div class="bottom">
          <p class="message"></p>
          <div class="controls" role="toolbar" aria-label="${escapeAttribute(labels.title)}">
            <button class="icon-button audio-button" data-action="audio" type="button" aria-label="${escapeAttribute(labels.unmute)}" title="${escapeAttribute(labels.unmute)}">🔇</button>
            <button class="icon-button" data-action="snapshot" type="button" aria-label="${escapeAttribute(labels.snapshot)}" title="${escapeAttribute(labels.snapshot)}">●</button>
            <button class="icon-button zoom-button" data-action="zoom" type="button" aria-label="${escapeAttribute(labels.zoom)}" title="${escapeAttribute(labels.zoom)}">1×</button>
            <button class="icon-button" data-action="pip" type="button" aria-label="${escapeAttribute(labels.pictureInPicture)}" title="${escapeAttribute(labels.pictureInPicture)}">▣</button>
            <button class="icon-button" data-action="fullscreen" type="button" aria-label="${escapeAttribute(labels.fullscreen)}" title="${escapeAttribute(labels.fullscreen)}">⛶</button>
            <button class="icon-button reconnect-button" data-action="reconnect" type="button" aria-label="${escapeAttribute(settings.autoplay === false ? labels.connect : labels.reconnect)}" title="${escapeAttribute(settings.autoplay === false ? labels.connect : labels.reconnect)}">↻</button>
          </div>
        </div>
      </div>
      <div class="snapshot-view" role="dialog" aria-modal="true" aria-label="${escapeAttribute(labels.snapshot)}" hidden>
        <img alt="${escapeAttribute(labels.snapshot)}">
        <button class="snapshot-close" data-action="close-snapshot" type="button" aria-label="${escapeAttribute(labels.closeSnapshot)}" title="${escapeAttribute(labels.closeSnapshot)}">×</button>
      </div>
    </main>`;

  const card = root.querySelector(".card");
  const video = root.querySelector("video");
  const reconnectButton = root.querySelector('[data-action="reconnect"]');
  const audioButton = root.querySelector('[data-action="audio"]');
  const snapshotButton = root.querySelector('[data-action="snapshot"]');
  const snapshotView = root.querySelector(".snapshot-view");
  const snapshotImage = snapshotView.querySelector("img");
  const closeSnapshotButton = root.querySelector('[data-action="close-snapshot"]');
  const zoomButton = root.querySelector('[data-action="zoom"]');
  const pipButton = root.querySelector('[data-action="pip"]');
  const fullscreenButton = root.querySelector('[data-action="fullscreen"]');
  const status = root.querySelector(".status");
  const statusText = root.querySelector(".status-text");
  const message = root.querySelector(".message");
  let session;
  let disposed = false;
  let zoomIndex = 0;

  video.muted = settings.start_muted !== false;
  audioButton.hidden = settings.include_audio !== true;
  pipButton.hidden = !(document.pictureInPictureEnabled && typeof video.requestPictureInPicture === "function");
  fullscreenButton.hidden = typeof card.requestFullscreen !== "function";

  const updateAudioButton = () => {
    const muted = video.muted;
    audioButton.textContent = muted ? "🔇" : "🔊";
    audioButton.setAttribute("aria-label", muted ? labels.unmute : labels.mute);
    audioButton.title = muted ? labels.unmute : labels.mute;
  };
  updateAudioButton();

  const show = (state, text, detail = "") => {
    status.dataset.state = state;
    statusText.textContent = text;
    message.textContent = detail;
  };
  const disconnect = async () => {
    const active = session;
    session = undefined;
    if (active) await active.close();
    video.srcObject = null;
  };
  const connect = async () => {
    if (disposed) return;
    reconnectButton.disabled = true;
    show("connecting", labels.connecting);
    await disconnect();
    try {
      if (!permissions.includes("camera")) throw new CameraPermissionError(labels.denied);
      session = new BrokeredWebRtcSession({
        PeerConnection,
        includeAudio: settings.include_audio === true,
        exchangeOffer: (offer) => host.openCameraSession(offer),
        closeSession: ({ sessionId }) => host.closeCameraSession(sessionId),
        onTrack: (stream) => {
          video.srcObject = stream;
          if (settings.autoplay !== false) void video.play().catch(() => undefined);
          show("live", labels.live);
        },
      });
      await session.start();
    } catch (error) {
      const denied = error instanceof CameraPermissionError;
      show(denied ? "denied" : "error", denied ? labels.denied : labels.offline, safeErrorMessage(error));
      await disconnect();
    } finally {
      reconnectButton.disabled = false;
      reconnectButton.setAttribute("aria-label", labels.reconnect);
      reconnectButton.title = labels.reconnect;
    }
  };

  const toggleAudio = () => { video.muted = !video.muted; updateAudioButton(); };
  const takeSnapshot = async () => {
    try {
      snapshotImage.src = captureVideoSnapshot(video);
      snapshotView.hidden = false;
      closeSnapshotButton.focus();
    } catch {
      show(status.dataset.state || "error", statusText.textContent || labels.offline, labels.snapshotUnavailable);
    }
  };
  const closeSnapshot = () => {
    snapshotView.hidden = true;
    snapshotImage.removeAttribute("src");
    snapshotButton.focus();
  };
  const cycleZoom = () => {
    zoomIndex = (zoomIndex + 1) % ZOOM_LEVELS.length;
    const zoom = ZOOM_LEVELS[zoomIndex];
    card.style.setProperty("--camera-zoom", String(zoom));
    zoomButton.textContent = `${zoom}×`;
    zoomButton.setAttribute("aria-label", `${labels.zoom} ${zoom}×`);
  };
  const togglePictureInPicture = async () => {
    if (document.pictureInPictureElement === video) await document.exitPictureInPicture();
    else await video.requestPictureInPicture();
  };
  const toggleFullscreen = async () => {
    if (document.fullscreenElement === card) await document.exitFullscreen();
    else await card.requestFullscreen();
  };
  const handlePictureInPicture = () => void togglePictureInPicture().catch((error) => {
    show(status.dataset.state || "error", statusText.textContent || labels.offline, safeErrorMessage(error));
  });
  const handleFullscreen = () => void toggleFullscreen().catch((error) => {
    show(status.dataset.state || "error", statusText.textContent || labels.offline, safeErrorMessage(error));
  });

  reconnectButton.addEventListener("click", connect);
  audioButton.addEventListener("click", toggleAudio);
  snapshotButton.addEventListener("click", takeSnapshot);
  closeSnapshotButton.addEventListener("click", closeSnapshot);
  zoomButton.addEventListener("click", cycleZoom);
  pipButton.addEventListener("click", handlePictureInPicture);
  fullscreenButton.addEventListener("click", handleFullscreen);
  await host.ready({ height: HEIGHT });
  if (settings.autoplay !== false) await connect();
  return async () => {
    disposed = true;
    reconnectButton.removeEventListener("click", connect);
    audioButton.removeEventListener("click", toggleAudio);
    snapshotButton.removeEventListener("click", takeSnapshot);
    closeSnapshotButton.removeEventListener("click", closeSnapshot);
    zoomButton.removeEventListener("click", cycleZoom);
    pipButton.removeEventListener("click", handlePictureInPicture);
    fullscreenButton.removeEventListener("click", handleFullscreen);
    await disconnect();
  };
}

export function captureVideoSnapshot(video) {
  if (!video || video.readyState < 2 || !video.videoWidth || !video.videoHeight) {
    throw new Error("Camera frame is not ready.");
  }
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Snapshot canvas is unavailable.");
  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/png");
}

class CameraPermissionError extends Error {}

function safeErrorMessage(error) {
  if (!(error instanceof Error)) return "Unable to start the camera session.";
  return error.message.replace(/https?:\/\/\S+/gi, "camera endpoint").slice(0, 180);
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
}

function escapeAttribute(value) { return escapeHtml(String(value)); }

if (typeof window !== "undefined" && typeof document !== "undefined") {
  const host = getInjectedPiPhiWidgetHost();
  const root = document.querySelector("#piphi-widget-root") || document.body;
  const dispose = await mountWebRtcCamera({ host, root });
  window.addEventListener("pagehide", () => void dispose(), { once: true });
}
