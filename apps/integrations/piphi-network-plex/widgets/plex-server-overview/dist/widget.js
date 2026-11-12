// node_modules/piphi-network-widget-sdk/dist/client.js
function getInjectedPiPhiWidgetHost(widgetWindow) {
  const resolvedWindow = widgetWindow ?? (typeof window !== "undefined" ? window : void 0);
  if (!resolvedWindow) {
    throw new Error("The PiPhi Widget SDK requires a browser window.");
  }
  const host2 = resolvedWindow.PiPhiWidgetHost;
  if (!host2) {
    throw new Error("PiPhiWidgetHost is not available. Run this widget inside a PiPhi dashboard or create a client bridge.");
  }
  return host2;
}

// node_modules/piphi-network-widget-sdk/dist/recovery-session.js
var RecoverySessionStoppedError = class extends Error {
  constructor() {
    super("The widget recovery session has stopped.");
    this.name = "RecoverySessionStoppedError";
  }
};
function recoveryEventName(event) {
  return String(event?.status || event?.kind || "").trim().toLowerCase();
}
function resolveRecoveryStatus(event, copy2, hasLastKnownValues = false) {
  const phase = recoveryEventName(event);
  if (["snapshot", "point", "open", "online", "ready", "connected", "live"].includes(phase)) {
    return { phase: "live", message: "", stale: false, retry: false };
  }
  if (["loading", "connecting", "reconnecting"].includes(phase)) {
    return { phase: "loading", message: copy2.updating, stale: hasLastKnownValues, retry: false };
  }
  if (phase === "stale") {
    return { phase: "stale", message: copy2.stale, stale: true, retry: true };
  }
  if (phase === "offline") {
    return { phase: "offline", message: copy2.offline, stale: hasLastKnownValues, retry: true };
  }
  if (["error", "closed", "denied"].includes(phase)) {
    return { phase: "error", message: copy2.error, stale: hasLastKnownValues, retry: true };
  }
  return { phase: "waiting", message: copy2.waiting, stale: hasLastKnownValues, retry: false };
}
var defaultTerminalEvent = (event) => ["error", "closed", "denied"].includes(recoveryEventName(event));
function createRecoverySession(options) {
  let activeRequest = null;
  let unsubscribe = null;
  let subscriptionGeneration = 0;
  let stopped = false;
  const isTerminalEvent = options.isTerminalEvent ?? defaultTerminalEvent;
  const stopQuietly = (stop2) => {
    void Promise.resolve(stop2()).catch(() => void 0);
  };
  async function installSubscription() {
    if (stopped)
      throw new RecoverySessionStoppedError();
    const generation = ++subscriptionGeneration;
    const listener = (event) => {
      if (generation !== subscriptionGeneration)
        return;
      if (isTerminalEvent(event)) {
        subscriptionGeneration += 1;
        const stop3 = unsubscribe;
        unsubscribe = null;
        if (stop3)
          stopQuietly(stop3);
      }
      options.onEvent?.(event);
    };
    const stop2 = await options.subscribe(listener);
    if (stopped || generation !== subscriptionGeneration) {
      stopQuietly(stop2);
      throw stopped ? new RecoverySessionStoppedError() : new Error("Widget subscription ended before it became ready.");
    }
    unsubscribe = stop2;
  }
  function recover(context = {}) {
    if (activeRequest)
      return activeRequest;
    if (stopped) {
      return Promise.resolve({ ok: false, error: new RecoverySessionStoppedError() });
    }
    activeRequest = (async () => {
      let outcome;
      try {
        options.onStart?.(context);
        if (stopped)
          throw new RecoverySessionStoppedError();
        const result = await options.read();
        if (stopped)
          throw new RecoverySessionStoppedError();
        options.onRead?.(result, context);
        if (stopped)
          throw new RecoverySessionStoppedError();
        if (!unsubscribe)
          await installSubscription();
        if (stopped)
          throw new RecoverySessionStoppedError();
        options.onRecovered?.(result, context);
        outcome = { ok: true };
      } catch (error) {
        outcome = { ok: false, error };
        if (!stopped) {
          try {
            options.onError?.(error, context);
          } catch (callbackError) {
            outcome = { ok: false, error: callbackError };
          }
        }
      }
      if (!stopped) {
        try {
          options.onSettled?.(context);
        } catch (callbackError) {
          outcome = { ok: false, error: callbackError };
        }
      }
      return outcome;
    })().finally(() => {
      activeRequest = null;
    });
    return activeRequest;
  }
  async function stop() {
    if (stopped)
      return;
    stopped = true;
    subscriptionGeneration += 1;
    const stopSubscription = unsubscribe;
    unsubscribe = null;
    if (stopSubscription)
      await stopSubscription();
  }
  return { recover, stop, hasSubscription: () => Boolean(unsubscribe) };
}

// widgets/plex-server-overview/src/widget.js
var host = getInjectedPiPhiWidgetHost();
var root = document.querySelector("#piphi-widget-root") || document.body;
var settings = await host.getSettings();
async function translated(key, fallback) {
  if (typeof host.translate !== "function") return fallback;
  try {
    const value = await host.translate(key);
    return value && value !== key ? String(value) : fallback;
  } catch {
    return fallback;
  }
}
var copy = {
  title: await translated("plex.title.servers", "Plex servers"),
  activity: await translated("plex.activity.label", "Plex server activity"),
  servers: await translated("plex.metric.servers", "Servers"),
  streams: await translated("plex.metric.streams", "Streams"),
  transcodes: await translated("plex.metric.transcodes", "Transcodes"),
  updating: await translated("plex.status.updating", "Updating Plex\u2026"),
  stale: await translated("plex.status.stale", "Plex data may be out of date"),
  offline: await translated("plex.status.offline", "Plex is offline"),
  error: await translated("plex.status.error", "Plex readings are unavailable"),
  waiting: await translated("plex.status.waiting", "Waiting for Plex"),
  retry: await translated("common.retry", "Retry")
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
      <div class="stat"><div class="value servers">\u2014</div><div class="label servers-label"></div></div>
      <div class="stat"><div class="value sessions">\u2014</div><div class="label streams-label"></div></div>
      <div class="stat"><div class="value transcodes">\u2014</div><div class="label transcodes-label"></div></div>
    </section>
  </main>`;
var configuredTitle = String(settings.title || "").trim();
root.querySelector("h2").textContent = configuredTitle && configuredTitle !== "Plex servers" ? configuredTitle : copy.title;
root.querySelector(".stats").setAttribute("aria-label", copy.activity);
root.querySelector(".servers-label").textContent = copy.servers;
root.querySelector(".streams-label").textContent = copy.streams;
root.querySelector(".transcodes-label").textContent = copy.transcodes;
var issue = root.querySelector(".issue");
var status = root.querySelector(".status");
var retry = root.querySelector(".retry");
var main = root.querySelector("main");
var heading = root.querySelector("h2");
retry.textContent = copy.retry;
var values = /* @__PURE__ */ new Map();
var problems = /* @__PURE__ */ new Map();
var slotIds = ["connected", "server-count", "active-sessions", "transcode-sessions"];
var fallbackTimers = /* @__PURE__ */ new Map();
var stateFromResult = (result) => result?.primaryState || result?.states?.[0] || null;
var stateFromEvent = (event) => event?.kind === "point" ? { value: event.data?.value } : event?.kind === "snapshot" ? stateFromResult(event.data) : null;
function syncHeight() {
  if (typeof host.setHeight === "function") void host.setHeight(problems.size ? 140 : 112);
}
function render() {
  const connectedValue = values.get("connected");
  const connected = connectedValue === void 0 || connectedValue === true || connectedValue === 1 || ["true", "on", "online", "connected"].includes(String(connectedValue).toLowerCase());
  const problemList = [...problems.values()];
  const activeProblem = problemList.find((problem) => problem.retry) || problemList[0];
  const canRetry = problemList.some((problem) => problem.retry) || !connected;
  const message = activeProblem?.message || (!connected ? copy.offline : "");
  status.textContent = message;
  issue.hidden = !message;
  retry.hidden = !canRetry;
  root.querySelector(".servers").textContent = String(values.get("server-count") ?? "\u2014");
  root.querySelector(".sessions").textContent = String(values.get("active-sessions") ?? "\u2014");
  root.querySelector(".transcodes").textContent = String(values.get("transcode-sessions") ?? "\u2014");
  syncHeight();
}
function storeState(slotId, state) {
  if (!state) return false;
  values.set(slotId, state.value ?? state.display_value);
  return true;
}
var sessions = new Map(slotIds.map((slotId) => [slotId, createRecoverySession({
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
      problems.delete(slotId);
      if (!fallbackTimers.has(slotId)) {
        const timer = window.setTimeout(() => {
          fallbackTimers.delete(slotId);
          void sessions.get(slotId)?.recover({ source: "stream-fallback" });
        }, 5e3);
        fallbackTimers.set(slotId, timer);
      }
    } else problems.set(slotId, model);
    render();
  },
  onError: () => {
    problems.set(slotId, { phase: "error", message: copy.error, stale: values.has(slotId), retry: true });
    render();
  }
})]));
var recovering = false;
async function recoverAll() {
  if (recovering) return;
  recovering = true;
  const restoreFocus = root.ownerDocument?.activeElement === retry;
  retry.disabled = true;
  retry.textContent = copy.updating;
  main.setAttribute("aria-busy", "true");
  try {
    await Promise.all([...sessions.values()].map((session) => session.recover({ source: "user" })));
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
await Promise.all([...sessions.values()].map((session) => session.recover({ source: "initial" })));
await host.ready({ height: problems.size ? 140 : 112 });
window.addEventListener("pagehide", () => {
  retry.removeEventListener("click", recoverAll);
  for (const timer of fallbackTimers.values()) window.clearTimeout(timer);
  fallbackTimers.clear();
  for (const session of sessions.values()) void session.stop();
}, { once: true });
