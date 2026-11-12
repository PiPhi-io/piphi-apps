import { getInjectedPiPhiWidgetHost } from "piphi-network-widget-sdk";
import { formatMinutes, normalizeLifecycle, projectState } from "./view-model.js";

const CAPABILITIES = ["is_online", "is_in_game", "persona_state", "current_game_name", "recent_playtime_minutes", "owned_game_count"];
const host = getInjectedPiPhiWidgetHost();
const root = document.querySelector("#piphi-widget-root") || document.body;
const [context, settings, translatedTitle, waiting] = await Promise.all([
  host.getContext(), host.getSettings(), host.translate("widget.title"), host.translate("widget.waiting"),
]);

root.innerHTML = `
  <style>
    :root {
      color-scheme: light;
      font: 14px/1.45 Inter, ui-sans-serif, system-ui, sans-serif;
      --steam-surface: var(--piphi-widget-surface, #ffffff);
      --steam-surface-muted: var(--piphi-widget-surface-muted, #f1f5f9);
      --steam-text: var(--piphi-widget-text, #0f172a);
      --steam-text-muted: var(--piphi-widget-text-muted, #64748b);
      --steam-border: color-mix(in srgb, var(--steam-text) 14%, transparent);
    }
    :root[data-piphi-color-scheme="dark"] {
      --steam-surface: var(--piphi-widget-surface, #0f172a);
      --steam-surface-muted: var(--piphi-widget-surface-muted, #172235);
      --steam-text: var(--piphi-widget-text, #f8fafc);
      --steam-text-muted: var(--piphi-widget-text-muted, #a8b5c7);
    }
    * { box-sizing: border-box; }
    main { min-height: 250px; padding: 20px; color: var(--steam-text); background: radial-gradient(circle at 90% 0%, color-mix(in srgb, #66c0f4 17%, transparent), transparent 45%), var(--steam-surface); border: 1px solid var(--steam-border); border-radius: 22px; overflow: hidden; }
    header { display: flex; align-items: center; gap: 12px; }
    .mark { display: grid; place-items: center; width: 48px; height: 48px; border-radius: 50%; color: white; background: linear-gradient(145deg, #1b2838, #2a475e 60%, #66c0f4); font-weight: 900; letter-spacing: -.06em; box-shadow: 0 10px 28px color-mix(in srgb, #1b2838 38%, transparent); }
    h2, p { margin: 0; } h2 { font-size: 1.08rem; } .persona { color: var(--steam-text-muted); text-transform: capitalize; }
    .hero { margin: 20px 0 14px; padding: 16px; border-radius: 17px; background: color-mix(in srgb, #66c0f4 10%, var(--steam-surface-muted)); border: 1px solid color-mix(in srgb, #66c0f4 30%, var(--steam-border)); }
    .eyebrow { display: block; color: var(--steam-text-muted); font-size: .75rem; letter-spacing: .08em; text-transform: uppercase; }
    .game { display: block; margin-top: 5px; font-size: clamp(1.25rem, 5vw, 1.75rem); line-height: 1.15; overflow-wrap: anywhere; }
    .stats { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .stat { padding: 11px 13px; border: 1px solid var(--steam-border); border-radius: 14px; background: var(--steam-surface-muted); }
    .stat span { display: block; color: var(--steam-text-muted); font-size: .76rem; } .stat strong { display: block; margin-top: 3px; font-size: 1.03rem; }
    .lifecycle { display: flex; align-items: center; gap: 8px; margin-top: 15px; color: var(--steam-text-muted); }
    .dot { width: 9px; height: 9px; border-radius: 50%; background: #8b8b93; }
    main[data-state="live"] .dot { background: #66c0f4; box-shadow: 0 0 0 4px color-mix(in srgb, #66c0f4 18%, transparent); }
    main[data-state="offline"] .dot, main[data-state="error"] .dot, main[data-state="denied"] .dot { background: #d14343; }
    @media (max-width: 360px) { main { padding: 15px; } .stat { padding-inline: 10px; } }
    @media (max-width: 220px) { .stats { grid-template-columns: 1fr; } }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
  </style>
  <main data-state="loading" dir="${escapeHtml(context.localization?.direction || "ltr")}">
    <header><span class="mark" aria-hidden="true">ST</span><div><h2>${escapeHtml(String(settings.title || translatedTitle))}</h2><p class="persona" data-persona>offline</p></div></header>
    <section class="hero"><span class="eyebrow">Now playing</span><strong class="game" data-game>—</strong></section>
    <section class="stats" aria-label="Steam activity summary"><div class="stat"><span>Playtime · 2 weeks</span><strong data-playtime>—</strong></div><div class="stat"><span>Visible games</span><strong data-library>—</strong></div></section>
    <p class="lifecycle" role="status" aria-live="polite"><span class="dot" aria-hidden="true"></span><span data-status>${escapeHtml(waiting)}</span></p>
  </main>`;

const card = root.querySelector("main");
const stop = await host.subscribeState({ capabilityIds: CAPABILITIES }, (event) => {
  const lifecycle = normalizeLifecycle(event.status || event.kind);
  card.dataset.state = lifecycle;
  root.querySelector("[data-status]").textContent = lifecycle;
  if (event.kind !== "snapshot" && event.kind !== "point") return;
  const state = projectState(event.data, CAPABILITIES);
  root.querySelector("[data-persona]").textContent = state.persona_state || (state.is_online ? "online" : "offline");
  root.querySelector("[data-game]").textContent = state.current_game_name || (state.is_in_game ? "In game" : "Not currently playing");
  root.querySelector("[data-playtime]").textContent = formatMinutes(state.recent_playtime_minutes);
  root.querySelector("[data-library]").textContent = Number.isFinite(state.owned_game_count)
    ? `${state.owned_game_count} game${state.owned_game_count === 1 ? "" : "s"}`
    : "Private";
});
window.addEventListener("pagehide", stop, { once: true });
await host.ready({ height: 320 });

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}
