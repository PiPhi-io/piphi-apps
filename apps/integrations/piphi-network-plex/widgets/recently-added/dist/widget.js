// node_modules/piphi-network-widget-sdk/dist/client.js
function getInjectedPiPhiWidgetHost(widgetWindow) {
  const resolvedWindow = widgetWindow ?? (typeof window !== "undefined" ? window : void 0);
  if (!resolvedWindow) {
    throw new Error("The PiPhi Widget SDK requires a browser window.");
  }
  const host = resolvedWindow.PiPhiWidgetHost;
  if (!host) {
    throw new Error("PiPhiWidgetHost is not available. Run this widget inside a PiPhi dashboard or create a client bridge.");
  }
  return host;
}

// widgets/live-media/widget.js
async function mountLiveMediaWidget(host, root, timer = globalThis) {
  const [settings, context] = await Promise.all([host.getSettings(), host.getContext()]);
  async function translated(key, fallback, values = {}) {
    if (typeof host.translate !== "function") return fallback;
    try {
      const value = await host.translate(key, values);
      return value && value !== key ? String(value) : fallback;
    } catch {
      return fallback;
    }
  }
  const names = {
    "io.piphi.plex.recently-added": ["plex.title.recently_added", "Recently Added"],
    "io.piphi.plex.continue-watching": ["plex.title.continue_watching", "Continue Watching"],
    "io.piphi.plex.library-search": ["plex.title.library", "Plex Search / Library"]
  };
  const runtimeWidgetId = String(context.package?.id || context.packageId || "");
  const widgetSlug = runtimeWidgetId.split("/").at(-1) || "";
  const titleCopy = names[runtimeWidgetId] || names[`io.piphi.plex.${widgetSlug}`] || ["plex.title.default", "Plex"];
  const defaultTitle = await translated(...titleCopy);
  const copy = {
    refresh: await translated("plex.action.refresh", "Refresh Plex"),
    loading: await translated("plex.status.loading", "Loading Plex\u2026"),
    reconnecting: await translated("plex.status.reconnecting", "Reconnecting to Plex\u2026"),
    live: await translated("plex.status.live", "Live \xB7 updated %TIME%"),
    stale: await translated("plex.status.stale_results", "Connection lost \xB7 showing previous results"),
    denied: await translated("plex.status.denied", "Plex access needs permission"),
    offline: await translated("plex.status.offline_retry", "Plex is offline \xB7 retrying"),
    unavailable: await translated("plex.status.unavailable_retry", "Plex is unavailable \xB7 retrying"),
    mediaLabel: await translated("plex.media.label", "Plex media"),
    empty: await translated("plex.media.empty", "No matching media on this server."),
    untitled: await translated("plex.media.untitled", "Untitled"),
    fallbackMedia: await translated("plex.media.fallback", "Media"),
    watched: await translated("plex.media.watched", "%TITLE%: %PERCENT%% watched"),
    movie: await translated("plex.media.kind.movie", "Movie"),
    episode: await translated("plex.media.kind.episode", "Episode"),
    music: await translated("plex.media.kind.music", "Music")
  };
  root.innerHTML = `<style>
    :root { color-scheme:light dark; --plex-control-text:#704800; --plex-control-bg:color-mix(in srgb,#e5a00d 9%,transparent); font:var(--piphi-widget-font-size,14px)/1.35 var(--piphi-widget-font-family,system-ui,sans-serif); }
    :root[data-piphi-color-scheme=dark] { --plex-control-text:#ffd166; --plex-control-bg:color-mix(in srgb,#ffd166 10%,transparent); }
    @media (prefers-color-scheme:dark) { :root:not([data-piphi-color-scheme=light]) { --plex-control-text:#ffd166; --plex-control-bg:color-mix(in srgb,#ffd166 10%,transparent); } }
    * { box-sizing:border-box; } main { min-height:0; padding:4px; background:transparent; color:var(--piphi-widget-text,#0f172a); overflow:hidden; }
    header { display:flex; justify-content:space-between; align-items:center; gap:10px; }
    h2 { margin:0; font-size:.9rem; line-height:1.3; } button { width:44px; min-width:44px; min-height:44px; padding:0; border:0; border-radius:9px; background:var(--plex-control-bg); color:var(--plex-control-text); font-size:1rem; font-weight:750; cursor:pointer; }
    button:disabled { opacity:.5; cursor:wait; } button:focus-visible { outline:0; box-shadow:var(--piphi-widget-focus-ring,0 0 0 3px #e5a00d66); }
    .source,.status { font-size:.75rem; line-height:1.4; color:var(--piphi-widget-text-muted,#52647a); overflow-wrap:anywhere; } .source:empty { display:none; } .status { margin:5px 0 0; }
    .status[data-state=live] { display:none; }
    .status[data-state=error],.status[data-state=offline],.status[data-state=denied],.status[data-state=stale] { color:var(--piphi-widget-danger,#b91c1c); }
    ul { list-style:none; margin:8px 0 0; padding:0; display:grid; gap:4px; }
    li { min-height:60px; display:grid; grid-template-columns:42px minmax(0,1fr); gap:9px; align-items:center; padding:5px; border-radius:10px; background:color-mix(in srgb,var(--piphi-widget-text,#0f172a) 4%,transparent); }
    .artwork { width:42px; height:54px; display:block; object-fit:cover; border-radius:7px; background:color-mix(in srgb,var(--piphi-widget-text,#0f172a) 8%,transparent); }
    .artwork-placeholder { width:42px; height:54px; display:grid; place-items:center; border-radius:7px; background:color-mix(in srgb,#e5a00d 14%,transparent); color:#9a6700; font-size:1rem; font-weight:800; }
    .media-copy { min-width:0; }
    h3 { margin:0; font-size:.875rem; line-height:1.3; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; } .meta { margin-top:2px; font-size:.75rem; color:var(--piphi-widget-text-muted,#52647a); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .summary { margin:3px 0 0; font-size:.75rem; display:-webkit-box; -webkit-line-clamp:1; -webkit-box-orient:vertical; overflow:hidden; }
    progress { width:100%; height:4px; margin-top:5px; accent-color:#e5a00d; } .empty { padding:14px 0 8px; text-align:center; color:var(--piphi-widget-text-muted,#52647a); font-size:.75rem; }
    @container (max-width:320px) { header { align-items:center; } li { grid-template-columns:38px minmax(0,1fr); } .artwork,.artwork-placeholder { width:38px; height:50px; } }
    @media (prefers-reduced-motion:reduce) { button { transition:none; } }
    @media (forced-colors:active) { button,.artwork,.artwork-placeholder { border:1px solid ButtonText; } progress { forced-color-adjust:auto; } }
  </style><main><header><h2></h2><button type="button">\u21BB</button></header>
  <div class="source"></div><p class="status" role="status" aria-live="polite"></p>
  <ul></ul><p class="empty" hidden></p></main>`;
  const title = root.querySelector("h2");
  const status = root.querySelector(".status");
  status.dataset.state = "loading";
  const list = root.querySelector("ul");
  const empty = root.querySelector(".empty");
  const button = root.querySelector("button");
  const doc = root.ownerDocument;
  const configuredTitle = String(settings.title || "").trim();
  title.textContent = configuredTitle && configuredTitle !== titleCopy[1] ? configuredTitle : defaultTitle;
  button.setAttribute("aria-label", copy.refresh);
  list.setAttribute("aria-label", copy.mediaLabel);
  empty.textContent = copy.empty;
  status.textContent = copy.loading;
  root.querySelector(".source").textContent = "Plex";
  const configuredInterval = Number(settings["refresh-seconds"] ?? settings.refreshSeconds ?? 60);
  const interval = (Number.isFinite(configuredInterval) ? Math.max(15, Math.min(300, configuredInterval)) : 60) * 1e3;
  let disposed = false;
  let busy = false;
  let handle;
  let failures = 0;
  let hasData = false;
  function syncHeight(fallback = 88) {
    if (typeof host.setHeight !== "function") return;
    const measured = Number(root.querySelector("main")?.scrollHeight);
    void host.setHeight(Math.min(220, Math.max(76, measured || fallback)));
  }
  function render(items) {
    list.replaceChildren();
    for (const item of items.slice(0, 2)) {
      const card = doc.createElement("li");
      const artworkUrl = String(item.artwork_url || "").trim();
      const artwork = doc.createElement(artworkUrl ? "img" : "span");
      artwork.className = artworkUrl ? "artwork" : "artwork-placeholder";
      if (artworkUrl) {
        artwork.src = artworkUrl;
        artwork.alt = "";
        artwork.loading = "lazy";
        artwork.addEventListener("error", () => {
          const fallback = doc.createElement("span");
          fallback.className = "artwork-placeholder";
          fallback.textContent = "P";
          fallback.setAttribute("aria-hidden", "true");
          artwork.replaceWith(fallback);
        }, { once: true });
      } else {
        artwork.textContent = "P";
        artwork.setAttribute("aria-hidden", "true");
      }
      const mediaCopy = doc.createElement("div");
      mediaCopy.className = "media-copy";
      const heading = doc.createElement("h3");
      heading.textContent = String(item.title || copy.untitled);
      const meta = doc.createElement("div");
      meta.className = "meta";
      const kind = { movie: copy.movie, episode: copy.episode, track: copy.music }[String(item.kind || "").toLowerCase()] || item.kind;
      meta.textContent = [kind, item.year, item.artist].filter(Boolean).join(" \xB7 ");
      mediaCopy.append(heading, meta);
      if (item.summary && (settings["show-summary"] ?? settings.showSummary) === true) {
        const summary = doc.createElement("p");
        summary.className = "summary";
        summary.textContent = String(item.summary);
        mediaCopy.append(summary);
      }
      const duration = Number(item.duration_seconds);
      const offset = Number(item.view_offset_seconds);
      if (Number.isFinite(duration) && duration > 0 && Number.isFinite(offset) && offset > 0) {
        const progress = doc.createElement("progress");
        progress.max = duration;
        progress.value = Math.min(duration, offset);
        progress.setAttribute("aria-label", copy.watched.replace("%TITLE%", String(item.title || copy.fallbackMedia)).replace("%PERCENT%", String(Math.round(progress.value / duration * 100))));
        mediaCopy.append(progress);
      }
      card.append(artwork, mediaCopy);
      list.append(card);
    }
    empty.hidden = items.length > 0;
    syncHeight(items.length ? 196 : 104);
  }
  async function refresh() {
    if (disposed || busy) return;
    timer.clearTimeout(handle);
    busy = true;
    button.disabled = true;
    if (failures) {
      status.dataset.state = "reconnecting";
      status.textContent = copy.reconnecting;
    }
    try {
      const result = await host.request("host.queryMedia");
      if (disposed) return;
      if (!Array.isArray(result?.items)) throw new Error("Invalid media response");
      render(result.items);
      hasData = true;
      failures = 0;
      root.querySelector(".source").textContent = String(result.serverName || "Plex");
      status.dataset.state = "live";
      status.textContent = copy.live.replace("%TIME%", (/* @__PURE__ */ new Date()).toLocaleTimeString());
    } catch (error) {
      if (disposed) return;
      failures++;
      const message = String(error?.message || "");
      status.dataset.state = hasData ? "stale" : /denied|permission/i.test(message) ? "denied" : /unavailable|offline/i.test(message) ? "offline" : "error";
      status.textContent = hasData ? copy.stale : status.dataset.state === "denied" ? copy.denied : status.dataset.state === "offline" ? copy.offline : copy.unavailable;
      syncHeight(hasData ? 196 : 88);
    } finally {
      busy = false;
      button.disabled = false;
      if (!disposed) handle = timer.setTimeout(() => void refresh(), Math.min(3e5, interval * 2 ** Math.min(failures, 3)));
    }
  }
  const click = () => void refresh();
  button.addEventListener("click", click);
  await host.ready({ height: 88 });
  void refresh();
  return () => {
    disposed = true;
    timer.clearTimeout(handle);
    button.removeEventListener("click", click);
  };
}

// widgets/live-media/entry.js
var cleanup = await mountLiveMediaWidget(
  getInjectedPiPhiWidgetHost(),
  document.querySelector("#piphi-widget-root") || document.body
);
window.addEventListener("pagehide", cleanup, { once: true });
