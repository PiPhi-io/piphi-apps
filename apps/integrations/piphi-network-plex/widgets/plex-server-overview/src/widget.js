import {
  createRecoverySession,
  getInjectedPiPhiWidgetHost,
  resolveRecoveryStatus,
} from "piphi-network-widget-sdk";

const host = getInjectedPiPhiWidgetHost();
const root = document.querySelector("#piphi-widget-root") || document.body;
const settings = await host.getSettings();

async function translated(key, fallback) {
  if (typeof host.translate !== "function") return fallback;
  try {
    const value = await host.translate(key);
    return value && value !== key ? String(value) : fallback;
  } catch {
    return fallback;
  }
}

const copy = {
  title: await translated("plex.title.servers", "Plex servers"),
  activity: await translated("plex.activity.label", "Plex server activity"),
  servers: await translated("plex.metric.servers", "Servers"),
  streams: await translated("plex.metric.streams", "Streams"),
  transcodes: await translated("plex.metric.transcodes", "Transcodes"),
  updating: await translated("plex.status.updating", "Updating Plex…"),
  stale: await translated("plex.status.stale", "Plex data may be out of date"),
  offline: await translated("plex.status.offline", "Plex is offline"),
  error: await translated("plex.status.error", "Plex readings are unavailable"),
  waiting: await translated("plex.status.waiting", "Waiting for Plex"),
  retry: await translated("common.retry", "Retry"),
};

root.innerHTML = `
  <style>
    :root { color-scheme:light dark; font:var(--piphi-widget-font-size,14px)/var(--piphi-widget-line-height,1.35) var(--piphi-widget-font-family,system-ui,sans-serif); }
    * { box-sizing:border-box; }
    main { min-height:0; padding:4px; color:var(--piphi-widget-text,#0f172a); background:transparent; overflow:hidden; }
    header { display:flex; align-items:center; justify-content:space-between; gap:12px; }
    h2 { margin:0; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:var(--piphi-widget-font-size-title,14px); line-height:1.25; }
    .issue { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-top:6px; }
    .status { margin:0; min-width:0; color:var(--piphi-widget-danger,#b91c1c); font-size:var(--piphi-widget-font-size-label,12px); overflow-wrap:anywhere; }
    .issue[hidden] { display:none; }
    .retry { min-width:44px; min-height:44px; padding:0 12px; border:1px solid var(--piphi-widget-border,#d7e0eb); border-radius:var(--piphi-widget-control-radius,10px); background:var(--piphi-widget-surface-muted,#fff); color:var(--piphi-widget-text,#0f172a); font:inherit; font-weight:700; cursor:pointer; }
    .retry:hover { border-color:var(--piphi-widget-accent,#2563eb); }
    .retry:focus-visible { outline:0; box-shadow:var(--piphi-widget-focus-ring,0 0 0 3px #2563eb57); }
    .retry:disabled { cursor:wait; opacity:.58; }
    .stats { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); margin-top:9px; border-top:1px solid var(--piphi-widget-border,#d7e0eb); }
    .stat { min-width:0; min-height:54px; padding:8px 7px 4px; }
    .stat + .stat { border-inline-start:1px solid var(--piphi-widget-border,#d7e0eb); }
    .value { font-size:var(--piphi-widget-font-size-value,18px); font-weight:760; font-variant-numeric:tabular-nums; }
    .label { margin-top:2px; color:var(--piphi-widget-text-muted,#52647a); font-size:var(--piphi-widget-font-size-label,12px); }
    @container (max-width:300px) { .stat { padding-inline:5px; } .retry { padding-inline:9px; } }
    @media (prefers-reduced-motion:reduce) { .retry { transition:none; } }
    @media (forced-colors:active) { .stats,.stat + .stat,.retry { border-color:CanvasText; } }
  </style>
  <main aria-busy="false">
    <header><h2 tabindex="-1"></h2></header>
    <div class="issue" hidden><p class="status" role="status" aria-live="polite"></p><button class="retry" type="button"></button></div>
    <section class="stats">
      <div class="stat"><div class="value servers">—</div><div class="label servers-label"></div></div>
      <div class="stat"><div class="value sessions">—</div><div class="label streams-label"></div></div>
      <div class="stat"><div class="value transcodes">—</div><div class="label transcodes-label"></div></div>
    </section>
  </main>`;

const configuredTitle = String(settings.title || "").trim();
root.querySelector("h2").textContent = configuredTitle && configuredTitle !== "Plex servers"
  ? configuredTitle
  : copy.title;
root.querySelector(".stats").setAttribute("aria-label", copy.activity);
root.querySelector(".servers-label").textContent = copy.servers;
root.querySelector(".streams-label").textContent = copy.streams;
root.querySelector(".transcodes-label").textContent = copy.transcodes;
const issue = root.querySelector(".issue");
const status = root.querySelector(".status");
const retry = root.querySelector(".retry");
const main = root.querySelector("main");
const heading = root.querySelector("h2");
retry.textContent = copy.retry;

const values = new Map();
const problems = new Map();
const slotIds = ["connected", "server-count", "active-sessions", "transcode-sessions"];
const fallbackTimers = new Map();
const stateFromResult = (result) => result?.primaryState || result?.states?.[0] || null;
const stateFromEvent = (event) => event?.kind === "point"
  ? { value: event.data?.value }
  : event?.kind === "snapshot" ? stateFromResult(event.data) : null;

function syncHeight() {
  if (typeof host.setHeight === "function") void host.setHeight(problems.size ? 140 : 112);
}

function render() {
  const connectedValue = values.get("connected");
  const connected = connectedValue === undefined || connectedValue === true || connectedValue === 1
    || ["true", "on", "online", "connected"].includes(String(connectedValue).toLowerCase());
  const problemList = [...problems.values()];
  const activeProblem = problemList.find((problem) => problem.retry) || problemList[0];
  const canRetry = problemList.some((problem) => problem.retry) || !connected;
  const message = activeProblem?.message || (!connected ? copy.offline : "");
  status.textContent = message;
  issue.hidden = !message;
  retry.hidden = !canRetry;
  root.querySelector(".servers").textContent = String(values.get("server-count") ?? "—");
  root.querySelector(".sessions").textContent = String(values.get("active-sessions") ?? "—");
  root.querySelector(".transcodes").textContent = String(values.get("transcode-sessions") ?? "—");
  syncHeight();
}

function storeState(slotId, state) {
  if (!state) return false;
  values.set(slotId, state.value ?? state.display_value);
  return true;
}

const sessions = new Map(slotIds.map((slotId) => [slotId, createRecoverySession({
  read: () => host.getCapabilityState({ slotId }),
  subscribe: (listener) => host.subscribeState({ slotId }, listener),
  onRead: (result) => {
    if (storeState(slotId, stateFromResult(result))) problems.delete(slotId);
    render();
  },
  onEvent: (event) => {
    const state = stateFromEvent(event);
    if (state) storeState(slotId, state);
    const model = resolveRecoveryStatus(event, copy, values.has(slotId));
    if (model.phase === "live") {
      problems.delete(slotId);
      const timer = fallbackTimers.get(slotId);
      if (timer) window.clearTimeout(timer);
      fallbackTimers.delete(slotId);
    } else if (model.phase === "error" && values.has(slotId)) {
      // stream_preferred means a fresh snapshot remains authoritative when the
      // live channel closes. Keep the glance view calm and repair the stream in
      // the background instead of presenting valid readings as unavailable.
      problems.delete(slotId);
      if (!fallbackTimers.has(slotId)) {
        const timer = window.setTimeout(() => {
          fallbackTimers.delete(slotId);
          void sessions.get(slotId)?.recover({ source:"stream-fallback" });
        }, 5_000);
        fallbackTimers.set(slotId, timer);
      }
    } else problems.set(slotId, model);
    render();
  },
  onError: () => {
    problems.set(slotId, { phase:"error", message:copy.error, stale:values.has(slotId), retry:true });
    render();
  },
})]));

let recovering = false;
async function recoverAll() {
  if (recovering) return;
  recovering = true;
  const restoreFocus = root.ownerDocument?.activeElement === retry;
  retry.disabled = true;
  retry.textContent = copy.updating;
  main.setAttribute("aria-busy", "true");
  try {
    await Promise.all([...sessions.values()].map((session) => session.recover({ source:"user" })));
  } finally {
    recovering = false;
    retry.disabled = false;
    retry.textContent = copy.retry;
    main.setAttribute("aria-busy", "false");
    render();
    if (restoreFocus && issue.hidden) heading.focus();
  }
}

retry.addEventListener("click", recoverAll);
await Promise.all([...sessions.values()].map((session) => session.recover({ source:"initial" })));
await host.ready({ height:problems.size ? 140 : 112 });

window.addEventListener("pagehide", () => {
  retry.removeEventListener("click", recoverAll);
  for (const timer of fallbackTimers.values()) window.clearTimeout(timer);
  fallbackTimers.clear();
  for (const session of sessions.values()) void session.stop();
}, { once:true });
