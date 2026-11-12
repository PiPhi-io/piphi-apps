import { getInjectedPiPhiWidgetHost } from "piphi-network-widget-sdk";
import { formatPrice, normalizeLifecycle, projectState } from "./model.js";

const CAPABILITIES = ["connected", "market_area", "current_price_per_kwh", "next_price_per_kwh", "price_unit"];
const host = getInjectedPiPhiWidgetHost();
const root = document.querySelector("#piphi-widget-root") || document.body;
const [context, settings, title, nextLabel, waiting] = await Promise.all([
  host.getContext(), host.getSettings(), host.translate("widget.title"),
  host.translate("widget.next"), host.translate("widget.waiting"),
]);
const locale = context.localization?.locale || "en";

root.innerHTML = `
  <style>
    :root { color-scheme: light dark; font: 14px/1.4 Inter, ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    main { min-height: 128px; padding: 14px; background: Canvas; color: CanvasText; border-radius: 18px; }
    header { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }
    h2, p { margin: 0; }
    h2 { font-size: .87rem; font-weight: 650; }
    .area { font-size: .75rem; opacity: .65; letter-spacing: .04em; }
    .price { display: flex; align-items: baseline; gap: 6px; margin-top: 10px; white-space: nowrap; }
    .price strong { font-size: clamp(1.85rem, 12vw, 2.5rem); line-height: 1; font-variant-numeric: tabular-nums; letter-spacing: -.04em; }
    .unit { font-size: .76rem; opacity: .68; }
    .next { margin-top: 8px; font-size: .83rem; opacity: .75; }
    .next strong { font-variant-numeric: tabular-nums; opacity: 1; }
    [role=status] { margin-top: 6px; font-size: .76rem; color: #b54736; }
    [role=status]:empty { display: none; }
    main:focus-visible { outline: 2px solid #2675df; outline-offset: -3px; }
    @media (max-width: 360px) { main { padding: 12px; } .price { flex-wrap: wrap; } }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition: none !important; animation: none !important; } }
  </style>
  <main tabindex="0" aria-label="${escapeHtml(String(settings.title || title))}" dir="${escapeHtml(context.localization?.direction || "ltr")}" data-state="loading">
    <header><h2>${escapeHtml(String(settings.title || title))}</h2><span class="area" data-area></span></header>
    <div class="price"><strong data-current>—</strong><span class="unit" data-unit></span></div>
    <p class="next">${escapeHtml(nextLabel)} <strong data-next>—</strong></p>
    <p role="status" aria-live="polite" data-status>${escapeHtml(waiting)}</p>
  </main>`;

const card = root.querySelector("main");
const status = root.querySelector("[data-status]");
const reportHeight = () => {
  queueMicrotask(() => void host.setHeight(Math.min(220, Math.max(130, root.scrollHeight + 2))));
};
const stop = await host.subscribeState({ capabilityIds: CAPABILITIES }, (event) => {
  const lifecycle = normalizeLifecycle(event.status || event.kind);
  card.dataset.state = lifecycle;
  if (event.kind === "snapshot" || event.kind === "point") {
    const state = projectState(event.data);
    root.querySelector("[data-area]").textContent = state.market_area;
    root.querySelector("[data-current]").textContent = formatPrice(state.current_price_per_kwh, locale);
    root.querySelector("[data-next]").textContent = formatPrice(state.next_price_per_kwh, locale);
    root.querySelector("[data-unit]").textContent = state.price_unit;
    status.textContent = !state.connected || state.current_price_per_kwh === null
      ? "Market data unavailable"
      : lifecycle === "stale" ? "Market prices may be old" : "";
  } else {
    status.textContent = lifecycle === "live" ? "" : lifecycle;
  }
  reportHeight();
});
window.addEventListener("pagehide", stop, { once: true });
await host.ready({ height: 140 });

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}
